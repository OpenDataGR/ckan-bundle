# -*- coding: utf-8 -*-
'''
Ένα εκκρεμές job ανά dataset και ποτέ δύο ταυτόχρονα για το ίδιο dataset.

Χρησιμοποιείται από τον archiver και το QA. Είναι ενεργό εξ ορισμού, με
διακόπτη ανά είδος job:

  ckanext.archiver.dedup_strategy = redis | none
  ckanext.qa.dedup_strategy = redis | none

Με redis (προεπιλογή) η κατάσταση κρατιέται σε κλειδιά της Redis ανά είδος
job και dataset, χωρίς σάρωση της ουράς. Με none ισχύει η παλιά συμπεριφορά
(κάθε αίτημα βάζει job): διακόπτης για απενεργοποίηση χωρίς αλλαγή κώδικα.
Τα κλειδιά:

  pending:<id>  "<ουρά>|<job id>" του job που περιμένει στην ουρά
  running:<id>  job id του job που εκτελείται
  rerun:<id>    ουρά για μία επανάληψη, όταν ζητήθηκε αλλαγή ενώ το job έτρεχε
  cancelled:<job id>  job που αντικαταστάθηκε από νεότερο και πρέπει να
                παραλειφθεί όταν έρθει η σειρά του

Κανόνες:
  - Αν υπάρχει ήδη job στην ουρά για το dataset, σε ίδια ή πιο γρήγορη ουρά,
    δεν μπαίνει δεύτερο.
  - Αίτημα priority ενώ περιμένει job στη bulk: μπαίνει νέο job στην priority
    και το παλιό σημειώνεται ως ακυρωμένο· παραλείπεται όταν έρθει η σειρά
    του (superseded). Δεν αφαιρείται από την ουρά, γιατί σε μεγάλη λίστα
    αυτό είναι ακριβό.
  - Αν το job που δείχνει το pending δεν περιμένει πια στην ουρά (δεν
    υπάρχει μετά από `ckan jobs clear`, ή έχει τελειώσει / αποτύχει), το
    κλειδί αγνοείται.
  - Όσο ένα job εκτελείται, νέο αίτημα δεν μπαίνει στην ουρά αλλά ζητά μία
    επανάληψη, που μπαίνει στην ουρά μόλις τελειώσει το job. Ο έλεγχος «τρέχει»
    και η εγγραφή της επανάληψης, όπως και το τέλος του job, γίνονται ατομικά
    (Lua script), ώστε να μη χάνεται αίτημα που φτάνει τη στιγμή που τελειώνει.
  - Αν το job που δείχνει το running δεν είναι πια started στη RQ, ή ο worker
    του δεν ζει πια (π.χ. SIGKILL σε restart του container: το job μένει
    started, αλλά το heartbeat του worker λήγει σε ~90s), το κλειδί αγνοείται.
  - Job που ξεκινά ενώ περιμένει άλλο job για το dataset: παραλείπεται μόνο αν
    εκείνο είναι σε ίδια ή πιο γρήγορη ουρά· αλλιώς εκτελείται τώρα και
    ακυρώνει το πιο αργό (π.χ. job priority από πριν το deploy, χωρίς pending).
  - Οι κανόνες ισχύουν μόνο μέσα σε RQ worker· κλήσεις εκτός worker (CLI,
    tests) εκτελούνται κανονικά.

Τα hooks του CKAN εκτελούνται πριν από το commit· γι' αυτό τα αιτήματα από
αυτά περνούν από το enqueue_after_commit.
'''
import logging
import uuid

log = logging.getLogger(__name__)

STRATEGY_NONE = 'none'
STRATEGY_REDIS = 'redis'
STRATEGIES = (STRATEGY_NONE, STRATEGY_REDIS)

# Λογικές ουρές με σειρά προτεραιότητας (μικρότερο = πιο επείγον)
QUEUE_RANK = {'priority': 0, 'bulk': 1}
DEFAULT_QUEUE = 'bulk'

# Χρόνοι ζωής κλειδιών (δευτερόλεπτα), ώστε να μη μείνουν «κολλημένα» αν
# σταματήσει απότομα ένας worker.
PENDING_TTL = 7 * 24 * 3600
RUNNING_TTL_MARGIN = 600
DEFAULT_RUNNING_TTL = 4 * 3600

QUEUED = 'queued'
ALREADY_QUEUED = 'already-queued'
RERUN_REQUESTED = 'rerun-requested'
SUPERSEDED = 'superseded'
DEFERRED = 'deferred'


def strategy_config_key(kind):
    return 'ckanext.%s.dedup_strategy' % kind


def get_strategy(kind):
    '''Η στρατηγική για το είδος job. Άγνωστη τιμή προκαλεί σφάλμα, αντί για
    σιωπηλή επιστροφή στο default.'''
    from ckan.exceptions import CkanConfigurationException
    from ckan.plugins.toolkit import config
    key = strategy_config_key(kind)
    value = str(config.get(key) or STRATEGY_REDIS).strip().lower()
    if value not in STRATEGIES:
        raise CkanConfigurationException(
            'Invalid value for %s: %r (allowed: %s)'
            % (key, value, ', '.join(STRATEGIES)))
    return value


def is_enabled(kind):
    return get_strategy(kind) == STRATEGY_REDIS


def _redis():
    from ckan.lib.redis import connect_to_redis
    return connect_to_redis()


def _text(value):
    if value is None:
        return None
    return value.decode('utf-8') if isinstance(value, bytes) else value


def _rank(queue):
    return QUEUE_RANK.get(queue, QUEUE_RANK[DEFAULT_QUEUE])


def _job_queue(kind, job):
    '''Η λογική ουρά (priority/bulk) από την οποία ήρθε το job της RQ, με βάση
    το job.origin και τις ckanext.<kind>.queue.<όνομα>.'''
    from ckan.lib.jobs import add_queue_name_prefix
    from ckan.plugins.toolkit import config
    origin = _text(getattr(job, 'origin', None))
    if origin:
        for name in QUEUE_RANK:
            real = config.get('ckanext.%s.queue.%s' % (kind, name)) or name
            if origin in (real, add_queue_name_prefix(real)):
                return name
    return DEFAULT_QUEUE


def _keys(kind, package_id):
    from ckan.plugins.toolkit import config
    prefix = 'ckanext:%s:%s:' % (config.get('ckan.site_id') or 'default', kind)
    return (prefix + 'pending:' + package_id,
            prefix + 'running:' + package_id,
            prefix + 'rerun:' + package_id)


def _cancelled_key(kind, job_id):
    from ckan.plugins.toolkit import config
    return 'ckanext:%s:%s:cancelled:%s' % (
        config.get('ckan.site_id') or 'default', kind, job_id)


# Καταστάσεις RQ στις οποίες ένα job περιμένει ακόμη να εκτελεστεί
WAITING_JOB_STATUSES = ('queued', 'deferred', 'scheduled')


def _job_is_waiting(redis_conn, job_id):
    '''True μόνο αν το job υπάρχει και περιμένει ακόμη στην ουρά.

    Ένα job που έχει τελειώσει ή αποτύχει μένει για λίγο στη Redis· αν το
    κλειδί pending δείχνει ακόμη σε αυτό (π.χ. μετά από αλλαγή της στρατηγικής),
    δεν πρέπει να εμποδίζει νέα αιτήματα.
    '''
    from rq.job import Job
    status = _text(redis_conn.hget(Job.key_for(job_id), 'status'))
    return status in WAITING_JOB_STATUSES


def _parse_pending(value):
    value = _text(value)
    if not value or '|' not in value:
        return None, None
    queue, job_id = value.split('|', 1)
    return queue, job_id


# Ατομικό αίτημα επανάληψης: αν τρέχει job για το dataset (είναι πράγματι
# started στη RQ και ο worker του ζει), καταγράφει την πιο επείγουσα ουρά για
# μία επανάληψη. Αν το job του running δεν τρέχει πια, σβήνει το κλειδί.
# Ο worker ελέγχεται μόνο όταν η RQ έχει γράψει worker_name στο job.
# KEYS: running, rerun · ARGV: ουρά, πρόθεμα κλειδιών job της RQ, ελάχιστο
# TTL, πρόθεμα κλειδιών worker της RQ
# Επιστρέφει 1 αν καταγράφηκε επανάληψη, 0 αν δεν τρέχει job.
_REQUEST_RERUN_SCRIPT = """
local running = redis.call('get', KEYS[1])
if not running then
    return 0
end
local job_key = ARGV[2] .. running
local status = redis.call('hget', job_key, 'status')
local worker = redis.call('hget', job_key, 'worker_name')
local worker_dead = worker and worker ~= '' and
    redis.call('exists', ARGV[4] .. worker) == 0
if status ~= 'started' or worker_dead then
    redis.call('del', KEYS[1])
    return 0
end
local queue = ARGV[1]
if redis.call('get', KEYS[2]) == 'priority' then
    queue = 'priority'
end
local ttl = redis.call('ttl', KEYS[1])
if ttl < tonumber(ARGV[3]) then
    ttl = tonumber(ARGV[3])
end
redis.call('set', KEYS[2], queue, 'EX', ttl)
return 1
"""

# Ατομικό τέλος job: σβήνει το running μόνο αν ανήκει στο job και επιστρέφει
# (και σβήνει) την ουρά της επανάληψης, αν ζητήθηκε. Αν το running ανήκει σε
# άλλο job, η επανάληψη αφορά εκείνο και δεν αγγίζεται.
# KEYS: running, rerun · ARGV: job id
_FINISH_SCRIPT = """
local owner = redis.call('get', KEYS[1])
if owner and owner ~= ARGV[1] then
    return false
end
if owner then
    redis.call('del', KEYS[1])
end
local rerun = redis.call('get', KEYS[2])
if rerun then
    redis.call('del', KEYS[2])
end
return rerun
"""


def _job_key_prefix():
    from rq.job import Job
    return _text(Job.redis_job_namespace_prefix)


def _worker_key_prefix():
    from rq.worker import Worker
    return _text(Worker.redis_worker_namespace_prefix)


def _request_rerun(redis_conn, running_key, rerun_key, queue):
    return redis_conn.eval(_REQUEST_RERUN_SCRIPT, 2, running_key, rerun_key,
                           queue, _job_key_prefix(), DEFAULT_RUNNING_TTL,
                           _worker_key_prefix()) == 1


def enqueue_once(kind, package_id, queue, enqueue_fn):
    '''Βάζει job στην ουρά για το dataset, εκτός αν υπάρχει ήδη.

    :param kind: είδος job, π.χ. 'qa', 'archiver'
    :param queue: λογική ουρά ('priority' ή 'bulk')
    :param enqueue_fn: συνάρτηση enqueue_fn(job_id) που βάζει το job στην
        ουρά με το συγκεκριμένο job id (None όταν η στρατηγική είναι none)
    :returns: QUEUED, ALREADY_QUEUED ή RERUN_REQUESTED
    '''
    queue = queue or DEFAULT_QUEUE
    if not is_enabled(kind):
        # Παλιά συμπεριφορά: κάθε αίτημα βάζει job (χωρίς συγκεκριμένο job id)
        enqueue_fn(None)
        return QUEUED

    redis_conn = _redis()
    pending_key, running_key, rerun_key = _keys(kind, package_id)

    if _request_rerun(redis_conn, running_key, rerun_key, queue):
        log.debug('%s job running for %s; rerun requested (%s)',
                  kind, package_id, queue)
        return RERUN_REQUESTED

    pending_raw = redis_conn.get(pending_key)
    pending_queue, pending_job = _parse_pending(pending_raw)
    pending_waiting = bool(pending_job) and _job_is_waiting(redis_conn, pending_job)
    if pending_waiting and _rank(pending_queue) <= _rank(queue):
        log.debug('%s job already queued for %s in %s',
                  kind, package_id, pending_queue)
        return ALREADY_QUEUED

    cancelled_key = None
    if pending_waiting:
        # Πιο επείγον αίτημα: το job που περιμένει στην πιο αργή ουρά ακυρώνεται
        cancelled_key = _cancelled_key(kind, pending_job)
        redis_conn.set(cancelled_key, '1', ex=PENDING_TTL)
        log.debug('%s job %s for %s superseded by a %s request',
                  kind, pending_job, package_id, queue)

    job_id = str(uuid.uuid4())
    new_pending = '%s|%s' % (queue, job_id)
    redis_conn.set(pending_key, new_pending, ex=PENDING_TTL)
    try:
        enqueue_fn(job_id)
    except Exception:
        # Το νέο job δεν μπήκε στην ουρά: επαναφορά, ώστε το παλιό να μην
        # έχει ακυρωθεί χωρίς αντικαταστάτη
        if _text(redis_conn.get(pending_key)) == new_pending:
            if pending_raw is not None:
                redis_conn.set(pending_key, pending_raw, ex=PENDING_TTL)
            else:
                redis_conn.delete(pending_key)
        if cancelled_key:
            redis_conn.delete(cancelled_key)
        raise
    return QUEUED


def run_once(kind, package_id, work_fn, requeue_fn):
    '''Εκτελεί το work_fn() για το dataset, με τους κανόνες του module.

    :param requeue_fn: συνάρτηση requeue_fn(queue) που ξαναβάζει το job στην
        ουρά (μέσω enqueue_once) όταν ζητήθηκε επανάληψη
    :returns: το αποτέλεσμα του work_fn(), ή SUPERSEDED / DEFERRED αν το job
        δεν εκτελέστηκε
    '''
    from rq import get_current_job
    job = get_current_job()
    if job is None or not is_enabled(kind):
        # Εκτός RQ worker, ή χωρίς τη στρατηγική redis: απλή εκτέλεση
        return work_fn()

    redis_conn = _redis()
    pending_key, running_key, rerun_key = _keys(kind, package_id)

    cancelled_key = _cancelled_key(kind, job.id)
    if redis_conn.exists(cancelled_key):
        redis_conn.delete(cancelled_key)
        log.info('%s job %s for %s was superseded; skipping',
                 kind, job.id, package_id)
        return SUPERSEDED

    pending_raw = redis_conn.get(pending_key)
    pending_queue, pending_job = _parse_pending(pending_raw)

    own_queue = pending_queue if pending_job == job.id else _job_queue(kind, job)
    cancel_pending = False
    if pending_job and pending_job != job.id and \
            _job_is_waiting(redis_conn, pending_job):
        if _rank(pending_queue) <= _rank(own_queue):
            # Νεότερο job για το dataset σε ίδια ή πιο γρήγορη ουρά· αυτό παραλείπεται
            log.info('%s job %s for %s superseded by %s',
                     kind, job.id, package_id, pending_job)
            return SUPERSEDED
        # Το job που περιμένει είναι σε πιο αργή ουρά: αυτό εκτελείται τώρα
        # και εκείνο ακυρώνεται, αφού αυτό ξεκίνησε μετά το αίτημά του
        cancel_pending = True

    timeout = job.timeout if isinstance(job.timeout, (int, float)) and job.timeout > 0 else None
    running_ttl = int(timeout) + RUNNING_TTL_MARGIN if timeout else DEFAULT_RUNNING_TTL
    acquired = redis_conn.set(running_key, job.id, nx=True, ex=running_ttl)
    if not acquired and not _request_rerun(redis_conn, running_key, rerun_key, own_queue):
        # Το running δεν ανήκε σε job που τρέχει πράγματι και σβήστηκε: νέα προσπάθεια
        acquired = redis_conn.set(running_key, job.id, nx=True, ex=running_ttl)
        if not acquired:
            _request_rerun(redis_conn, running_key, rerun_key, own_queue)
    if not acquired:
        # Άλλο job εκτελείται ήδη για το ίδιο dataset: ζητήθηκε επανάληψη
        log.info('%s job %s for %s deferred: another job is running',
                 kind, job.id, package_id)
        return DEFERRED

    # Το «τρέχει» μπαίνει πριν σβηστεί το «περιμένει», ώστε ένα νέο αίτημα να
    # βλέπει πάντα ένα από τα δύο.
    if pending_raw is not None and redis_conn.get(pending_key) == pending_raw:
        if cancel_pending:
            redis_conn.set(_cancelled_key(kind, pending_job), '1', ex=PENDING_TTL)
            log.info('%s job %s for %s superseded by running job %s',
                     kind, pending_job, package_id, job.id)
        redis_conn.delete(pending_key)

    try:
        return work_fn()
    finally:
        rerun_queue = _text(redis_conn.eval(
            _FINISH_SCRIPT, 2, running_key, rerun_key, job.id))
        if rerun_queue:
            log.info('%s job for %s changed while running; queueing once more (%s)',
                     kind, package_id, rerun_queue)
            try:
                requeue_fn(rerun_queue)
            except Exception:
                log.exception('Could not requeue %s job for %s', kind, package_id)


# Κλειδί στο Session.info για τα jobs που περιμένουν το commit
_AFTER_COMMIT_KEY = 'ckanext_job_dedup_after_commit'
_SESSION_HOOKS_REGISTERED = False


def enqueue_after_commit(kind, package_id, queue, enqueue_fn):
    '''Βάζει job για το dataset στην ουρά μόλις γίνει commit του session.

    Τα hooks του CKAN (IDomainObjectModification.notify, after_dataset_create /
    update) εκτελούνται πριν από το commit. Αν το job έμπαινε αμέσως στην ουρά,
    ή αν περίμενε ήδη job για το dataset (ALREADY_QUEUED) και ξεκινούσε πριν
    από το commit, θα διάβαζε την προηγούμενη εκδοχή του dataset και η αλλαγή
    θα χανόταν. Σε rollback δεν μπαίνει τίποτα. Πολλαπλά αιτήματα για το ίδιο
    dataset στο ίδιο transaction γίνονται ένα, στην πιο γρήγορη ουρά.

    Χρειάζεται register_session_hooks() (το κάνουν τα plugins στο update_config).

    :param enqueue_fn: συνάρτηση enqueue_fn(package_id, queue), π.χ.
        enqueue_archiver_package
    '''
    from ckan import model
    pending = model.Session().info.setdefault(_AFTER_COMMIT_KEY, {})
    key = (kind, package_id)
    previous = pending.get(key)
    if previous is None or _rank(queue) < _rank(previous[0]):
        pending[key] = (queue, enqueue_fn)


def _enqueue_after_commit(session):
    '''after_commit: βάζει στην ουρά τα jobs που σημειώθηκαν. Μετά το commit
    δεν επιτρέπεται SQL στο session· χρησιμοποιούνται μόνο τα ids.'''
    pending = session.info.pop(_AFTER_COMMIT_KEY, None)
    if not pending:
        return
    for (kind, package_id) in sorted(pending):
        queue, enqueue_fn = pending[(kind, package_id)]
        try:
            result = enqueue_fn(package_id, queue)
            log.debug('%s job for %s after commit: %s (queue %s)',
                      kind, package_id, result, queue)
        except Exception:
            log.exception('Could not queue %s job for %s', kind, package_id)


def _discard_after_commit(session):
    '''after_rollback: οι αλλαγές δεν αποθηκεύτηκαν, άρα δεν μπαίνει job.'''
    session.info.pop(_AFTER_COMMIT_KEY, None)


def register_session_hooks():
    '''Καταχωρεί μία φορά τα SQLAlchemy events για το enqueue_after_commit.'''
    global _SESSION_HOOKS_REGISTERED
    if _SESSION_HOOKS_REGISTERED:
        return
    from sqlalchemy import event
    from ckan.model import meta
    event.listen(meta.Session, 'after_commit', _enqueue_after_commit)
    event.listen(meta.Session, 'after_rollback', _discard_after_commit)
    _SESSION_HOOKS_REGISTERED = True
