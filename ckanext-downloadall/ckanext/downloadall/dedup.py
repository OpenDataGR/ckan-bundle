import logging
import uuid

from ckan.common import config


log = logging.getLogger(__name__)

STRATEGY_REQUEST_CACHE = 'request_cache'
STRATEGY_REDIS = 'redis'
VALID_STRATEGIES = {STRATEGY_REQUEST_CACHE, STRATEGY_REDIS}

STRATEGY_CONFIG = 'ckanext.downloadall.dedup_strategy'
LOCK_TTL_CONFIG = 'ckanext.downloadall.redis_lock_ttl'
DEFAULT_LOCK_TTL = 3600
# Περιθώριο πάνω από το timeout του job (OD-857)
LOCK_TTL_MARGIN = 300


class RedisDedupError(Exception):
    """Raised when Redis deduplication is temporarily unavailable."""


def get_strategy():
    strategy = str(config.get(
        STRATEGY_CONFIG, STRATEGY_REQUEST_CACHE)).strip().lower()
    if strategy not in VALID_STRATEGIES:
        log.warning(
            'Unknown downloadall dedup strategy %r; using %s',
            strategy, STRATEGY_REQUEST_CACHE)
        return STRATEGY_REQUEST_CACHE
    return strategy


def get_lock_ttl():
    value = config.get(LOCK_TTL_CONFIG, DEFAULT_LOCK_TTL)
    try:
        ttl = int(value)
    except (TypeError, ValueError):
        ttl = DEFAULT_LOCK_TTL
    if ttl <= 0:
        ttl = DEFAULT_LOCK_TTL
    # OD-857: το lock ζει τουλάχιστον όσο το job. Αλλιώς, σε build μεγαλύτερο
    # από το TTL, μια αλλαγή θα ξεκινούσε δεύτερο job παράλληλα για το ίδιο
    # dataset (διπλός πόρος ZIP ή διαγραφή του blob του άλλου job).
    return max(ttl, _job_timeout() + LOCK_TTL_MARGIN)


def _job_timeout():
    '''Timeout του job: ckanext.downloadall.job_timeout ή ckan.jobs.timeout.'''
    from . import config as settings
    timeout = settings.job_timeout()
    if timeout:
        return timeout
    try:
        return max(int(config.get('ckan.jobs.timeout', 180)), 0)
    except (TypeError, ValueError):
        return 180


def _keys(dataset_id):
    site_id = str(config.get('ckan.site_id', 'default'))
    # The Redis hash tag keeps both keys in the same cluster slot so the Lua
    # scripts remain valid with clustered Redis deployments.
    prefix = 'ckan:{}:downloadall:{{{}}}'.format(site_id, dataset_id)
    return '{}:lock'.format(prefix), '{}:dirty'.format(prefix)


def _force_key(dataset_id):
    '''Κλειδί του αιτήματος για νέο build ακόμη κι αν το dataset δεν άλλαξε
    (skip_if_no_changes=False, π.χ. update-all-zips --retry-failed). Ίδιο hash
    tag με τα lock/dirty, άρα ίδιο slot σε Redis cluster.'''
    return '{}:force'.format(_keys(dataset_id)[0].rsplit(':', 1)[0])


def _connect():
    try:
        from ckan.lib.redis import connect_to_redis
        return connect_to_redis()
    except Exception as exc:
        raise RedisDedupError(str(exc))


def _eval(script, keys, args):
    try:
        return _connect().eval(script, len(keys), *(keys + args))
    except RedisDedupError:
        raise
    except Exception as exc:
        raise RedisDedupError(str(exc))


# Τύποι αιτήματος για αναγκαστικό build χωρίς έλεγχο αλλαγών στο Redis force key:
#   retry: π.χ. update-all-zips --retry-failed (μετρά στο downloadall_retries)
#   refresh: π.χ. package_update που διατήρησε το ZIP (δεν μετρά ως retry)
FORCE_RETRY = 'retry'
FORCE_REFRESH = 'refresh'

_ACQUIRE_SCRIPT = """
redis.call('set', KEYS[2], '1', 'EX', ARGV[2])
if ARGV[3] == 'retry' then
    redis.call('set', KEYS[3], 'retry', 'EX', ARGV[2])
elseif ARGV[3] == 'refresh' then
    local current_force = redis.call('get', KEYS[3])
    if current_force ~= 'retry' and current_force ~= '1' then
        redis.call('set', KEYS[3], 'refresh', 'EX', ARGV[2])
    else
        -- Το retry μένει, με την ίδια διάρκεια με το lock και το dirty
        redis.call('expire', KEYS[3], ARGV[2])
    end
end
local acquired = redis.call('set', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2])
if acquired then
    return 1
end
return 0
"""

_PREPARE_SCRIPT = """
local current = redis.call('get', KEYS[1])
if not current then
    redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[2])
elseif current ~= ARGV[1] then
    return 0
else
    redis.call('expire', KEYS[1], ARGV[2])
end
redis.call('del', KEYS[2])
return 1
"""

_FINISH_SCRIPT = """
local current = redis.call('get', KEYS[1])
if current ~= ARGV[1] then
    return -1
end
if redis.call('exists', KEYS[2]) == 1 then
    redis.call('expire', KEYS[1], ARGV[2])
    redis.call('expire', KEYS[2], ARGV[2])
    return 1
end
redis.call('del', KEYS[1])
return 0
"""

_TAKE_SCRIPT = """
local value = redis.call('get', KEYS[1])
if value then
    redis.call('del', KEYS[1])
end
return value
"""

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def mark_dirty_and_acquire(dataset_id, force=False):
    """Mark a dataset changed and acquire its enqueue lock when available.

    OD-857: με force σημειώνεται και αίτημα για νέο build χωρίς έλεγχο
    αλλαγών. Αν το lock το έχει ήδη άλλο job, αυτό το βρίσκει στην επόμενη
    επεξεργασία του (take_force), αντί να χαθεί το αίτημα.

    :param force: False (χωρίς force), True / FORCE_RETRY (μετρά ως retry) ή
        FORCE_REFRESH (αναγκαστικό build χωρίς αύξηση του downloadall_retries).
    """
    if force is True:
        force_mode = FORCE_RETRY
    elif force in (FORCE_RETRY, FORCE_REFRESH):
        force_mode = force
    else:
        force_mode = ''
    token = uuid.uuid4().hex
    result = _eval(
        _ACQUIRE_SCRIPT,
        list(_keys(dataset_id)) + [_force_key(dataset_id)],
        [token, str(get_lock_ttl()), force_mode])
    return token if result == 1 else None


# Αποτυχημένα builds dataset χωρίς ZIP (OD-857): δεν υπάρχει πόρος ZIP για να
# τα καταγράψει, οπότε κρατιούνται εδώ για το όριο του --retry-failed
NO_ZIP_ATTEMPTS_TTL = 30 * 24 * 3600


def _no_zip_key(dataset_id):
    return '{}:nozip'.format(_keys(dataset_id)[0].rsplit(':', 1)[0])


def record_no_zip_attempt(dataset_id, fingerprint):
    '''Μία ακόμη αποτυχία του build για την εκδοχή fingerprint ενός dataset
    χωρίς ZIP· επιστρέφει πόσες έχουν γίνει για αυτή την εκδοχή.'''
    fingerprint_seen, attempts = no_zip_attempts(dataset_id)
    attempts = attempts + 1 if fingerprint_seen == fingerprint else 1
    try:
        _connect().set(_no_zip_key(dataset_id), '{}|{}'.format(fingerprint, attempts),
                       ex=NO_ZIP_ATTEMPTS_TTL)
    except RedisDedupError:
        raise
    except Exception as exc:
        raise RedisDedupError(str(exc))
    return attempts


def no_zip_attempts(dataset_id):
    '''(fingerprint, πλήθος) των αποτυχημένων builds ενός dataset χωρίς ZIP,
    ή (None, 0).'''
    try:
        value = _connect().get(_no_zip_key(dataset_id))
    except RedisDedupError:
        raise
    except Exception as exc:
        raise RedisDedupError(str(exc))
    if not value:
        return None, 0
    if isinstance(value, bytes):
        value = value.decode('utf-8')
    fingerprint, _sep, attempts = value.rpartition('|')
    try:
        return fingerprint, int(attempts)
    except ValueError:
        return None, 0


def clear_no_zip_attempts(dataset_id):
    try:
        _connect().delete(_no_zip_key(dataset_id))
    except RedisDedupError:
        raise
    except Exception as exc:
        raise RedisDedupError(str(exc))


def take_force(dataset_id):
    '''Επιστρέφει FORCE_RETRY / FORCE_REFRESH (truthy) αν ζητήθηκε νέο build
    χωρίς έλεγχο αλλαγών, αλλιώς False· το αίτημα σβήνεται, ώστε να ισχύσει
    για μία επεξεργασία.'''
    value = _eval(_TAKE_SCRIPT, [_force_key(dataset_id)], [])
    if not value:
        return False
    if isinstance(value, bytes):
        value = value.decode('utf-8')
    return FORCE_REFRESH if value == FORCE_REFRESH else FORCE_RETRY


def prepare_iteration(dataset_id, token):
    """Claim an iteration and clear changes already covered by its snapshot."""
    result = _eval(
        _PREPARE_SCRIPT,
        list(_keys(dataset_id)),
        [token, str(get_lock_ttl())])
    return result == 1


def finish_iteration(dataset_id, token):
    """Return True when changes made during the iteration require a rerun."""
    result = _eval(
        _FINISH_SCRIPT,
        list(_keys(dataset_id)),
        [token, str(get_lock_ttl())])
    return result == 1


def release_lock(dataset_id, token):
    """Release a lock only when it is still owned by token."""
    lock_key, _dirty_key = _keys(dataset_id)
    return _eval(_RELEASE_SCRIPT, [lock_key], [token]) == 1


def is_dirty(dataset_id):
    '''True αν το dataset άλλαξε μετά την αρχή της τρέχουσας επεξεργασίας
    (το prepare_iteration σβήνει το dirty). OD-857: μετά από αποτυχία του
    job, ώστε η αλλαγή να μη χαθεί.'''
    _lock_key, dirty_key = _keys(dataset_id)
    try:
        return bool(_connect().exists(dirty_key))
    except RedisDedupError:
        raise
    except Exception as exc:
        raise RedisDedupError(str(exc))
