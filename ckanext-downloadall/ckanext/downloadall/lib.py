# -*- coding: utf-8 -*-
'''
Ουρά των jobs του DownloadAll (OD-857).

Τα jobs μπαίνουν στην ουρά ckanext.downloadall.queue. Ο συντονισμός «ένα job
ανά dataset» είναι αυτός του branch feature/downloadall-redis-coalescing
(dedup.py):

  request_cache (προεπιλογή): ένα job ανά dataset σε κάθε commit (από τα
         hooks) ή μέσα στο ίδιο αίτημα (λοιπές κλήσεις)
  redis: ένα εκκρεμές/ενεργό job ανά dataset (κλειδιά lock/dirty στη Redis)·
         αλλαγή όσο τρέχει το job προκαλεί νέα επεξεργασία μέσα στο ίδιο job

Τα αιτήματα από τα hooks του CKAN μπαίνουν στην ουρά μετά το commit
(enqueue_zip_after_commit), ώστε το job να διαβάζει πάντα την αποθηκευμένη
εκδοχή του dataset.
'''
import contextlib
import contextvars
import logging

from ckan.plugins import toolkit

from . import config
from . import dedup

log = logging.getLogger(__name__)

QUEUED = 'queued'
ALREADY_QUEUED = 'already-queued'

# Ενεργό όσο το job αποθηκεύει τον δικό του πόρο ZIP. Το notify το ελέγχει,
# ώστε η ενημέρωση του ZIP να μην ξαναβάζει job για το ίδιο dataset.
_OWN_UPDATE = contextvars.ContextVar('downloadall_own_update', default=False)

# Ενεργό όσο εκτελείται resource_delete, με τα ids των πόρων που διαγράφονται.
# Το chained package_update το ελέγχει ώστε να μην επαναφέρει ZIP που
# διαγράφεται ρητά με resource_delete (από το DownloadAll ή από χρήστη/API).
_DELETING_RESOURCE_IDS = contextvars.ContextVar(
    'downloadall_deleting_resource_ids', default=frozenset())

# Κλειδιά στο Session.info για τα datasets που περιμένουν το commit
_AFTER_COMMIT_KEY = 'ckanext_downloadall_after_commit'
_AFTER_COMMIT_FORCE_KEY = 'ckanext_downloadall_after_commit_force'
_SESSION_HOOKS_REGISTERED = False


@contextlib.contextmanager
def own_update():
    token = _OWN_UPDATE.set(True)
    try:
        yield
    finally:
        _OWN_UPDATE.reset(token)


def in_own_update():
    return _OWN_UPDATE.get()


@contextlib.contextmanager
def deleting_resource(resource_id):
    if not resource_id:
        yield
        return
    current = _DELETING_RESOURCE_IDS.get()
    token = _DELETING_RESOURCE_IDS.set(current | {str(resource_id)})
    try:
        yield
    finally:
        _DELETING_RESOURCE_IDS.reset(token)


def is_deleting_resource(resource_id):
    return bool(resource_id) and str(resource_id) in _DELETING_RESOURCE_IDS.get()


def _request_queued_dataset_ids():
    """Return the per-request set of datasets already handled, if available."""
    try:
        queued_dataset_ids = getattr(
            toolkit.g, '_downloadall_queued_dataset_ids', None)
    except (RuntimeError, TypeError):
        return None

    if queued_dataset_ids is None:
        queued_dataset_ids = set()
        toolkit.g._downloadall_queued_dataset_ids = queued_dataset_ids

    return queued_dataset_ids


def _enqueue_job(package_id, dedup_token=None, skip_if_no_changes=True,
                 count_retry=None):
    from .tasks import update_zip
    job_args = [package_id, None, skip_if_no_changes]
    if dedup_token is not None:
        job_args.append(dedup_token)
    job_kwargs = {'count_retry': count_retry} if count_retry is not None else None
    timeout = config.job_timeout()
    toolkit.enqueue_job(
        update_zip, job_args,
        kwargs=job_kwargs,
        title=u'DownloadAll {}'.format(package_id),
        queue=config.queue_name(),
        rq_kwargs={'timeout': timeout} if timeout else None)


def enqueue_zip(package_id, skip_if_no_changes=True, per_request=True,
                count_retry=None):
    '''Βάζει job για το ZIP του dataset στην ουρά, εκτός αν υπάρχει ήδη
    (βλ. dedup). Επιστρέφει QUEUED ή ALREADY_QUEUED.

    :param skip_if_no_changes: False για νέο build ακόμη κι αν το ZIP
        αντιστοιχεί στο dataset (π.χ. για να ξαναδοκιμαστούν πόροι που
        απέτυχαν ή μετά από harvest που διατήρησε το ZIP). Με redis, αν
        υπάρχει ήδη job, το αίτημα περνά σε αυτό.
    :param per_request: με request_cache, ένα job ανά dataset σε όλο το
        αίτημα. False για το enqueue μετά από κάθε commit: ένα job που μπήκε
        σε προηγούμενο commit του ίδιου αιτήματος μπορεί να έχει ήδη
        ξεκινήσει με την προηγούμενη εκδοχή του dataset.
    :param count_retry: αν το αναγκαστικό build μετρά στο downloadall_retries
        του --retry-failed (None: default, True όταν skip_if_no_changes=False·
        False για harvest/package_update που διατήρησε το ZIP).
    '''
    request_dataset_ids = _request_queued_dataset_ids()
    redis = dedup.get_strategy() == dedup.STRATEGY_REDIS
    # Με redis η αλλαγή σημειώνεται πάντα ως dirty (OD-857): ένα job που
    # μπήκε νωρίτερα στο ίδιο αίτημα μπορεί να έχει ήδη ξεκινήσει, και χωρίς
    # dirty δεν θα ξαναεπεξεργαζόταν το dataset
    if not redis and per_request and request_dataset_ids is not None and \
            package_id in request_dataset_ids:
        return ALREADY_QUEUED

    if skip_if_no_changes:
        force = False
    elif count_retry is False:
        force = dedup.FORCE_REFRESH
    else:
        force = dedup.FORCE_RETRY

    dedup_token = None
    if redis:
        try:
            dedup_token = dedup.mark_dirty_and_acquire(
                package_id, force=force)
        except dedup.RedisDedupError as exc:
            # Enqueue without cross-request deduplication. If Redis itself is
            # unavailable, enqueue_job will raise its normal queueing error.
            log.warning(
                'Redis deduplication unavailable for dataset %s; falling '
                'back to blind enqueue: %s', package_id, exc)
            if per_request and request_dataset_ids is not None and \
                    package_id in request_dataset_ids:
                return ALREADY_QUEUED
        else:
            if dedup_token is None:
                log.debug('Downloadall job already pending for dataset %s',
                          package_id)
                return ALREADY_QUEUED

    try:
        _enqueue_job(package_id, dedup_token, skip_if_no_changes,
                     count_retry=count_retry)
    except Exception:
        if dedup_token is not None:
            try:
                dedup.release_lock(package_id, dedup_token)
            except dedup.RedisDedupError as exc:
                log.warning(
                    'Could not release DownloadAll Redis lock after enqueue '
                    'failure for dataset %s: %s', package_id, exc)
        raise

    if per_request and request_dataset_ids is not None:
        request_dataset_ids.add(package_id)
    return QUEUED


def enqueue_zip_after_commit(package_id):
    '''Σημειώνει το dataset ώστε να μπει job στην ουρά μόλις γίνει commit.

    Τα hooks του CKAN (notify) εκτελούνται πριν από το commit. Αν το job έμπαινε
    αμέσως στην ουρά, ένας ελεύθερος worker μπορεί να διάβαζε την προηγούμενη
    εκδοχή του dataset, να έχτιζε παλιό ZIP και η αλλαγή να χανόταν. Σε
    rollback δεν μπαίνει τίποτα.
    '''
    from ckan import model
    model.Session().info.setdefault(_AFTER_COMMIT_KEY, set()).add(package_id)


def mark_forced_rebuild_after_commit(package_id):
    '''Σημειώνει το dataset ώστε το job μετά το commit να ξαναχτίσει το ZIP
    χωρίς έλεγχο αλλαγών και χωρίς αύξηση του downloadall_retries (όταν το
    chained package_update διατήρησε το υπάρχον ZIP).

    Επιστρέφει True αν η σημείωση προστέθηκε τώρα, ώστε να μπορεί να αφαιρεθεί
    αν το package_update αποτύχει πριν το rollback/commit.
    '''
    from ckan import model
    forced = model.Session().info.setdefault(_AFTER_COMMIT_FORCE_KEY, set())
    if package_id in forced:
        return False
    forced.add(package_id)
    return True


def unmark_forced_rebuild_after_commit(package_id):
    from ckan import model
    forced = model.Session().info.get(_AFTER_COMMIT_FORCE_KEY)
    if forced:
        forced.discard(package_id)


def _enqueue_after_commit(session):
    '''after_commit: μόνο ids, γιατί μετά το commit δεν επιτρέπεται SQL.
    Ένα job ανά dataset σε κάθε commit (το σύνολο στο Session.info)· για
    datasets όπου διατηρήθηκε το ZIP στο package_update ζητείται αναγκαστικό
    ξαναχτίσιμο χωρίς αύξηση του downloadall_retries.'''
    package_ids = set(session.info.pop(_AFTER_COMMIT_KEY, None) or ())
    force_ids = set(session.info.pop(_AFTER_COMMIT_FORCE_KEY, None) or ())
    for package_id in sorted(package_ids | force_ids):
        try:
            if package_id in force_ids:
                enqueue_zip(package_id, skip_if_no_changes=False,
                            per_request=False, count_retry=False)
            else:
                enqueue_zip(package_id, per_request=False)
        except Exception:
            log.exception('Could not queue DownloadAll job for %s', package_id)


def _discard_after_commit(session):
    session.info.pop(_AFTER_COMMIT_KEY, None)
    session.info.pop(_AFTER_COMMIT_FORCE_KEY, None)


def register_session_hooks():
    '''Καταχωρεί μία φορά τα SQLAlchemy events για το enqueue μετά το commit.'''
    global _SESSION_HOOKS_REGISTERED
    if _SESSION_HOOKS_REGISTERED:
        return
    from sqlalchemy import event
    from ckan.model import meta
    event.listen(meta.Session, 'after_commit', _enqueue_after_commit)
    event.listen(meta.Session, 'after_rollback', _discard_after_commit)
    _SESSION_HOOKS_REGISTERED = True


def check_config():
    log.info('DownloadAll queue: %s, dedup strategy: %s',
             config.queue_name(), dedup.get_strategy())
    register_session_hooks()
