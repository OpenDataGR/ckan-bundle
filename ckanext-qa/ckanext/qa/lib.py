import os
import json
import re
import logging
from ckan.plugins import toolkit as tk
from ckan.exceptions import CkanConfigurationException

from ckan import plugins as p
from ckanext.qa.tasks import update_package, update

log = logging.getLogger(__name__)

config = tk.config
enqueue_job = tk.enqueue_job

_RESOURCE_FORMAT_SCORES = None

# Τρόπος υπολογισμού της ανοικτότητας (openness).
# archival: η ιστορική ροή, μετά τον archiver, με archival status και content sniffing.
# metadata_only: μόνο από άδεια, κατάληξη URL και resource.format, ανεξάρτητα από τον archiver.
OPENNESS_MODE_CONFIG = 'ckanext.qa.openness_mode'
OPENNESS_MODE_ARCHIVAL = 'archival'
OPENNESS_MODE_METADATA_ONLY = 'metadata_only'
OPENNESS_MODES = (OPENNESS_MODE_ARCHIVAL, OPENNESS_MODE_METADATA_ONLY)

# Λογικά ονόματα ουρών· το πραγματικό όνομα ορίζεται παραμετρικά, π.χ.
# ckanext.qa.queue.priority = qa_priority
LOGICAL_QUEUES = ('priority', 'bulk')


def openness_mode():
    '''Επιστρέφει τον ενεργό τρόπο υπολογισμού ανοικτότητας.

    Άγνωστη τιμή προκαλεί σφάλμα, αντί για σιωπηλή επιστροφή στο default.
    '''
    value = (config.get(OPENNESS_MODE_CONFIG) or OPENNESS_MODE_ARCHIVAL)
    value = str(value).strip().lower()
    if value not in OPENNESS_MODES:
        raise CkanConfigurationException(
            'Invalid value for %s: %r (allowed: %s)'
            % (OPENNESS_MODE_CONFIG, value, ', '.join(OPENNESS_MODES)))
    return value


def is_metadata_only_mode():
    return openness_mode() == OPENNESS_MODE_METADATA_ONLY


def resolve_queue(queue):
    '''Μετατρέπει λογικό όνομα ουράς (priority/bulk) στο πραγματικό όνομα
    που έχει οριστεί για το QA. Άλλα ονόματα επιστρέφονται όπως είναι.'''
    if queue in LOGICAL_QUEUES:
        return config.get('ckanext.qa.queue.%s' % queue) or queue
    return queue


def compat_enqueue(name, fn, queue, args=None, job_id=None):

    u'''
    Enqueue a background job using Celery or RQ.
    '''
    try:
        # Try to use RQ
        log.debug('Trying to use RQ')
        rq_kwargs = {'job_id': job_id} if job_id else None
        enqueue_job(fn, args=args, queue=resolve_queue(queue), rq_kwargs=rq_kwargs)
    except ImportError:
        # Fallback to Celery
        log.debug('RQ not installed, falling back to Celery')
        import uuid
        from ckan.lib.celery_app import celery
        celery.send_task(name, args=args + [queue], task_id=str(uuid.uuid4()))


def resource_format_scores():
    ''' Returns the resource formats scores as a dict keyed by format shortname
    (usually extension)

    :param key:  format shortname (usually extension) as defined in ckan's
                 resource_format.json
    :param value:  string
    :returns: openness score (int) - assuming it is accessible and has an open
              licence

    Fuller description of the fields are described in
    `ckan/config/resource_formats.json`.
    '''
    global _RESOURCE_FORMAT_SCORES
    if not _RESOURCE_FORMAT_SCORES:
        _RESOURCE_FORMAT_SCORES = {}
        json_filepath = config.get('qa.resource_format_openness_scores_json')
        if not json_filepath:
            json_filepath = os.path.join(
                os.path.dirname(os.path.realpath(__file__)),
                'resource_format_openness_scores.json'
            )
        with open(json_filepath) as format_file:
            try:
                file_resource_formats = json.loads(format_file.read())
            except ValueError as e:
                # includes simplejson.decoder.JSONDecodeError
                raise ValueError('Invalid JSON syntax in %s: %s' %
                                 (json_filepath, e))

            for format_line in file_resource_formats:
                if format_line[0] == '_comment':
                    continue
                format_, score = format_line
                if not isinstance(score, int):
                    raise ValueError('Score must be integer in %s: %s: %r'
                                     % json_filepath, format_, score)
                if format_ in _RESOURCE_FORMAT_SCORES:
                    raise ValueError('Duplicate resource format '
                                     'identifier in %s: %s' %
                                     (json_filepath, format_))
                _RESOURCE_FORMAT_SCORES[format_] = score

    return _RESOURCE_FORMAT_SCORES


def munge_format_to_be_canonical(format_name):
    '''Tries some things to help try and get a resource format to match one of
    the canonical ones
    '''
    format_name = format_name.strip().lower()
    if format_name.startswith('.'):
        format_name = format_name[1:]
    return re.sub('[^a-z/+]', '', format_name)


def create_qa_update_package_task(package, queue):

    result = enqueue_qa_package(package.id, queue)
    log.debug('QA of package %s: %s (queue %s)', package.name, result, queue)


def enqueue_qa_package(package_id, queue):
    '''Βάζει QA job για το dataset, ένα εκκρεμές ανά dataset
    (βλ. ckanext.archiver.job_dedup).'''
    from ckanext.archiver import job_dedup

    def _enqueue(job_id):
        compat_enqueue('qa.update_package', update_package, queue,
                       args=[package_id], job_id=job_id)

    return job_dedup.enqueue_once('qa', package_id, queue, _enqueue)


def queue_openness_after_commit(package_id):
    '''Σημειώνει ένα dataset ώστε να μπει στην ουρά priority του QA μόλις
    γίνει commit.

    Τα hooks after_dataset_create/update εκτελούνται πριν από το commit του
    package_create/package_update. Αν το job έμπαινε αμέσως στην ουρά, ο worker
    μπορεί να διάβαζε την προηγούμενη εκδοχή του dataset
    (βλ. ckanext.archiver.job_dedup.enqueue_after_commit).
    '''
    from ckanext.archiver import job_dedup
    job_dedup.enqueue_after_commit('qa', package_id, 'priority', enqueue_qa_package)


def register_session_hooks():
    '''Καταχωρεί τα SQLAlchemy events για το queue_openness_after_commit.'''
    from ckanext.archiver import job_dedup
    job_dedup.register_session_hooks()


def create_qa_update_task(resource, queue):
    if p.toolkit.check_ckan_version(max_version='2.2.99'):
        package = resource.resource_group.package
    else:
        package = resource.package

    compat_enqueue('qa.update', update, queue, args=[resource.id])

    log.debug('QA of resource put into queue %s: %s/%s url=%r',
              queue, package.name, resource.id, resource.url)
