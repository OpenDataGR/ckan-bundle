from builtins import str
import logging
import ckan.plugins as p
from ckan.exceptions import CkanConfigurationException

from ckanext.archiver.tasks import update_package, update_resource

log = logging.getLogger(__name__)

# Τρόπος λειτουργίας του archiver.
# archive: η ιστορική ροή (GET, download, hash, αντίγραφο στο Azure).
# check_only: έλεγχος μόνο του resource.url, χωρίς λήψη ή αποθήκευση αρχείου.
ARCHIVER_MODE_CONFIG = 'ckanext.archiver.mode'
ARCHIVER_MODE_ARCHIVE = 'archive'
ARCHIVER_MODE_CHECK_ONLY = 'check_only'
ARCHIVER_MODES = (ARCHIVER_MODE_ARCHIVE, ARCHIVER_MODE_CHECK_ONLY)

# Λογικά ονόματα ουρών· το πραγματικό όνομα ορίζεται παραμετρικά, π.χ.
# ckanext.archiver.queue.bulk = archiver_bulk
LOGICAL_QUEUES = ('priority', 'bulk')


def archiver_mode():
    '''Επιστρέφει τον ενεργό τρόπο λειτουργίας του archiver.

    Άγνωστη τιμή προκαλεί σφάλμα, αντί για σιωπηλή επιστροφή στο default.
    '''
    value = p.toolkit.config.get(ARCHIVER_MODE_CONFIG) or ARCHIVER_MODE_ARCHIVE
    value = str(value).strip().lower()
    if value not in ARCHIVER_MODES:
        raise CkanConfigurationException(
            'Invalid value for %s: %r (allowed: %s)'
            % (ARCHIVER_MODE_CONFIG, value, ', '.join(ARCHIVER_MODES)))
    return value


def is_check_only_mode():
    return archiver_mode() == ARCHIVER_MODE_CHECK_ONLY


def resolve_queue(queue):
    '''Μετατρέπει λογικό όνομα ουράς (priority/bulk) στο πραγματικό όνομα
    που έχει οριστεί για τον archiver. Άλλα ονόματα επιστρέφονται όπως είναι.'''
    if queue in LOGICAL_QUEUES:
        return p.toolkit.config.get('ckanext.archiver.queue.%s' % queue) or queue
    return queue


# Προεπιλεγμένο timeout (δευτερόλεπτα) των archiver jobs στο check_only, όταν
# δεν έχει οριστεί ckanext.archiver.job_timeout: ένα job ελέγχει όλους τους
# πόρους ενός dataset και το γενικό ckan.jobs.timeout (180) δεν αρκεί όταν
# κάποιοι σύνδεσμοι δεν απαντούν.
CHECK_ONLY_DEFAULT_JOB_TIMEOUT = 3600


def _config_int(key, default, minimum=None):
    '''Ακέραια ρύθμιση με ελάχιστη τιμή (None: χωρίς ελάχιστη). Κενή → default·
    μη έγκυρη → default με προειδοποίηση (το 0 είναι έγκυρη τιμή, όχι «κενή»).'''
    value = p.toolkit.config.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        value = int(value)
    except (TypeError, ValueError):
        log.warning('Invalid integer for %s: %r; using %r', key, value, default)
        return default
    if minimum is not None and value < minimum:
        log.warning('%s=%r is below %r; using %r', key, value, minimum, minimum)
        return minimum
    return value


def check_only_timeout():
    '''Timeout (δευτερόλεπτα) κάθε HTTP αιτήματος στο check_only.'''
    return _config_int('ckanext.archiver.check_only.timeout', 15, 1)


def check_only_host_timeout_limit():
    '''Μετά από τόσους συνεχόμενους συνδέσμους ενός server που έληξαν με
    timeout μέσα στο ίδιο job, οι υπόλοιποι σύνδεσμοί του σε αυτό το job δεν
    ζητούνται (βλ. tasks.HostTimeouts). 0: απενεργοποίηση.'''
    return _config_int('ckanext.archiver.check_only.host_timeout_limit', 3, 0)


def check_only_retries():
    '''Επαναλήψεις μετά από προσωρινή αποτυχία στο check_only.'''
    return _config_int('ckanext.archiver.check_only.retries', 1, 0)


def check_only_failure_threshold():
    '''Συνεχόμενες αποτυχίες μετά τις οποίες ένα URL θεωρείται broken.'''
    return _config_int('ckanext.archiver.check_only.failure_threshold', 3, 1)


def _job_rq_kwargs():
    '''Timeout για τα archiver jobs (ckanext.archiver.job_timeout), ανεξάρτητο
    από το γενικό ckan.jobs.timeout. Στο check_only, αν δεν οριστεί, 3600.
    Τιμή 0 ή αρνητική: καμία παράκαμψη, ισχύει το ckan.jobs.timeout.'''
    default = CHECK_ONLY_DEFAULT_JOB_TIMEOUT if is_check_only_mode() else None
    timeout = _config_int('ckanext.archiver.job_timeout', default)
    if not timeout or timeout <= 0:
        return None
    return {'timeout': timeout}


def compat_enqueue(name, fn, queue, args=None, job_id=None):
    u'''
    Enqueue a background job using Celery or RQ.

    Το λογικό όνομα της ουράς περνά και ως όρισμα στο job, ώστε το
    package-archived να φτάνει στο QA με την ίδια ουρά (priority ή bulk).
    '''
    args = list(args or [])
    try:
        # Try to use RQ
        from ckan.plugins.toolkit import enqueue_job
        rq_kwargs = _job_rq_kwargs() or {}
        if job_id:
            rq_kwargs['job_id'] = job_id
        enqueue_job(fn, args=args + [queue], queue=resolve_queue(queue),
                    rq_kwargs=rq_kwargs or None)
    except ImportError:
        # Fallback to Celery
        import uuid
        from ckan.lib.celery_app import celery
        celery.send_task(name, args=args + [queue], task_id=str(uuid.uuid4()))


def create_archiver_resource_task(resource, queue):
    if p.toolkit.check_ckan_version(max_version='2.2.99'):
        # earlier CKANs had ResourceGroup
        package = resource.resource_group.package
    else:
        package = resource.package

    compat_enqueue('archiver.update_resource', update_resource, queue, [resource.id])

    log.debug('Archival of resource put into celery queue %s: %s/%s url=%r',
              queue, package.name, resource.id, resource.url)


def create_archiver_package_task(package, queue):
    result = enqueue_archiver_package(package.id, queue)
    log.debug('Archival of package %s: %s (queue %s)',
              package.name, result, queue)


def enqueue_archiver_package(package_id, queue):
    '''Βάζει archiver job για το dataset, ένα εκκρεμές ανά dataset
    (βλ. job_dedup).'''
    from ckanext.archiver import job_dedup

    def _enqueue(job_id):
        compat_enqueue('archiver.update_package', update_package, queue,
                       [package_id], job_id=job_id)

    return job_dedup.enqueue_once('archiver', package_id, queue, _enqueue)


def get_extra_from_pkg_dict(pkg_dict, key, default=None):
    for extra in pkg_dict.get('extras', []):
        if extra['key'] == key:
            return extra['value']
    return default
