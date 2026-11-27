# -*- coding: utf-8 -*-
'''
Δημιουργία του ZIP «Λήψη όλων» ενός dataset (OD-857).

Ροή του job:
  1. package_show (αν το dataset δεν υπάρχει πια ή δεν είναι ενεργό, τέλος)
  2. dataset που δεν πρέπει να έχει ZIP (data service, showcase, μη HVD με
     hvd_only, κανένας πόρος για το ZIP): σβήνεται το ZIP του, αν υπάρχει
  3. αν το fingerprint και το hash του datapackage.json δεν άλλαξαν, τέλος
  4. λήψη κάθε πόρου σε προσωρινό αρχείο (timeouts, όρια μεγέθους, χρονικό
     όριο πριν το timeout του job) και προσθήκη στο ZIP μαζί με το
     datapackage.json και το downloadall-manifest.json
  5. αποθήκευση του ZIP με νέο όνομα αρχείου και, μόνο μετά από επιτυχία,
     διαγραφή του προηγούμενου blob

Οι πόροι που δεν κατέβηκαν δεν σταματούν το job· καταγράφονται στο manifest.
Αν δεν κατέβηκε κανένας πόρος ή το build απέτυχε, το προηγούμενο ZIP μένει
και σημειώνεται η αποτυχημένη προσπάθεια (record_attempt).
'''
import copy
import datetime
import hashlib
import json
import logging
import math
import os
import shutil
import socket
import tempfile
import threading
import time
import zipfile
from email.utils import parsedate_to_datetime
from time import monotonic, sleep
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
import six
import sqlalchemy as sa
import ckanapi
import ckanapi.cli.utils
import ckanapi.datapackage
from rq.timeouts import JobTimeoutException

from ckan import model
from ckan.plugins import toolkit

from . import config
from . import dedup
from . import eligibility
from . import filenames
from . import freshness
from . import lib
from . import storage

log = logging.getLogger(__name__)

DATAPACKAGE_NAME = 'datapackage.json'
MANIFEST_NAME = 'downloadall-manifest.json'
CHUNK_SIZE = 64 * 1024
RETRY_DELAY_SECONDS = 2
# Επαναλήψεις της απελευθέρωσης του lock σε σύντομο σφάλμα της Redis
RELEASE_ATTEMPTS = 3
RELEASE_RETRY_SECONDS = 1

# Πότε μπαίνει νέο job μετά την απελευθέρωση του lock (_release_and_requeue)
REQUEUE_NEVER = 'never'
REQUEUE_IF_CHANGED = 'if-changed'
REQUEUE_ALWAYS = 'always'
ZIP_NAME_MAX_DATASET_CHARS = 60

STATUS_INCLUDED = 'included'
STATUS_EXCLUDED = 'excluded'
STATUS_FAILED = 'failed'

# Παράμετροι URL που μπορεί να περιέχουν μυστικά (π.χ. SAS token)· οι τιμές
# τους δεν γράφονται στο manifest
SECRET_QUERY_KEYS = ('sig', 'signature', 'token', 'access_token', 'key',
                     'apikey', 'api_key', 'password', 'secret', 'code', 'auth')

ZIP_RESOURCE_NAME = u'All resource data'
ZIP_RESOURCE_NAME_TRANSLATED = {'en': u'All resource data',
                                'el': u'Όλα τα δεδομένα πόρων'}


class DownloadError(Exception):
    """Ο πόρος δεν μπόρεσε να μπει στο ZIP.

    transient: η αποτυχία μπορεί να είναι προσωρινή (timeout, σύνδεση, 5xx,
    429), οπότε το update-all-zips --retry-failed την ξαναδοκιμάζει· οι άλλες
    (π.χ. 404, όριο μεγέθους ή χρόνου) ξαναδοκιμάζονται όταν αλλάξει το
    dataset.
    """
    def __init__(self, message="Resource download failed", transient=False):
        self.message = message
        self.transient = transient
        super(DownloadError, self).__init__(self.message)


def _call_update_zip_once(package_id, user, skip_if_no_changes, deadline,
                          count_retry=None):
    # Κρατά την κλήση 4 ορισμάτων όταν το count_retry είναι default
    # (συμβατότητα με υπάρχοντα mocks/tests).
    if count_retry is None or count_retry == (not skip_if_no_changes):
        return _update_zip_once(package_id, user, skip_if_no_changes, deadline)
    return _update_zip_once(package_id, user, skip_if_no_changes, deadline,
                            count_retry=count_retry)


def update_zip(package_id, user=None, skip_if_no_changes=True, dedup_token=None,
               timeout=None, count_retry=None):
    """Update a dataset ZIP, coalescing changes when a Redis token is given.

    Job του RQ (βλ. dedup, branch feature/downloadall-redis-coalescing). Με
    dedup_token, όσο το dataset αλλάζει κατά τη διάρκεια του build, η
    επεξεργασία επαναλαμβάνεται μέσα στο ίδιο job.

    :param user: αγνοείται· το job τρέχει ως site user
    :param skip_if_no_changes: αν το υπάρχον ZIP αντιστοιχεί ήδη στην τρέχουσα
        εκδοχή του dataset, δεν ξαναδημιουργείται
    :param timeout: δευτερόλεπτα για κλήση εκτός RQ (CLI --synchronous), ώστε
        ένας αργός server να μην κρατά την εντολή απεριόριστα
    :param count_retry: αν το αναγκαστικό build μετρά στο downloadall_retries
        (None: default, True όταν skip_if_no_changes=False· False για
        αναγκαστικό ξαναχτίσιμο μετά από package_update/harvest).
    """
    # Μία φορά ανά job: το timeout της RQ μετρά από την αρχή του job, όχι από
    # την αρχή κάθε επανάληψης
    deadline = job_deadline(timeout)
    if dedup_token is None:
        return _call_update_zip_once(
            package_id, user, skip_if_no_changes, deadline, count_retry)

    job_count_retry = (
        (not skip_if_no_changes) if count_retry is None else bool(count_retry)
    )

    while True:
        try:
            prepared = dedup.prepare_iteration(package_id, dedup_token)
        except dedup.RedisDedupError as exc:
            log.warning(
                'Redis coordination unavailable for DownloadAll job %s; '
                'running once without deduplication: %s', package_id, exc)
            try:
                return _call_update_zip_once(
                    package_id, user, skip_if_no_changes, deadline, count_retry)
            finally:
                # Αλλιώς το lock μένει ως το TTL και οι αλλαγές του dataset
                # δεν βάζουν job. Χωρίς νέο job: αν το σφάλμα επιμένει, κάθε
                # νέο job θα ξανάβαζε το επόμενο
                _release_and_requeue(package_id, dedup_token,
                                     skip_if_no_changes, REQUEUE_NEVER,
                                     count_retry=count_retry)

        if not prepared:
            log.info(
                'Skipping superseded DownloadAll job for dataset %s',
                package_id)
            return

        # Αίτημα για νέο build χωρίς έλεγχο αλλαγών (π.χ. --retry-failed ή
        # harvest) που ήρθε όσο υπήρχε ήδη αυτό το job
        forced = _take_force(package_id)
        effective_skip = skip_if_no_changes and not forced
        force_counts_retry = bool(forced) and forced != dedup.FORCE_REFRESH
        effective_count_retry = job_count_retry or force_counts_retry
        started = monotonic()
        try:
            _call_update_zip_once(package_id, user, effective_skip, deadline,
                                  effective_count_retry)
        except Exception:
            # Μια αλλαγή όσο έτρεχε το job που απέτυχε δεν πρέπει να χαθεί
            _release_and_requeue(package_id, dedup_token, skip_if_no_changes,
                                 REQUEUE_IF_CHANGED, count_retry=count_retry)
            raise
        duration = monotonic() - started
        # Οι ρυθμίσεις του job (π.χ. --retry-failed) ισχύουν μόνο για την 1η
        # επανάληψη. Οι επόμενες, και ένα νέο job λόγω χρόνου, γίνονται για
        # αλλαγή του dataset και αποφασίζονται από το :force του Redis· αλλιώς
        # ένα harvest ή μια απλή αλλαγή θα μετρούσε ξανά στο downloadall_retries
        skip_if_no_changes = True
        count_retry = None
        job_count_retry = False

        try:
            rerun = dedup.finish_iteration(package_id, dedup_token)
        except dedup.RedisDedupError as exc:
            log.warning(
                'Could not finalize Redis coordination for DownloadAll job '
                '%s: %s', package_id, exc)
            _release_and_requeue(package_id, dedup_token, skip_if_no_changes,
                                 REQUEUE_IF_CHANGED, count_retry=count_retry)
            return

        if not rerun:
            return

        # Νέα επεξεργασία μόνο αν προλαβαίνει όσο κράτησε η προηγούμενη·
        # αλλιώς οι πόροι θα έβγαιναν «time limit» και η αλλαγή θα
        # καταγραφόταν ως αποτυχημένη προσπάθεια αντί για νέο job
        if deadline is not None and monotonic() + duration > deadline:
            log.info(
                'Dataset %s changed while its DownloadAll job was running; '
                'not enough time left in this job, queueing a new one',
                package_id)
            _release_and_requeue(package_id, dedup_token, skip_if_no_changes,
                                 REQUEUE_ALWAYS, count_retry=count_retry)
            return

        log.info(
            'Dataset %s changed while its DownloadAll job was running; '
            'processing the latest state', package_id)


def _take_force(package_id):
    try:
        return dedup.take_force(package_id)
    except dedup.RedisDedupError as exc:
        log.warning('Could not read the forced-rebuild request of %s: %s',
                    package_id, exc)
        return False


def _release_and_requeue(package_id, dedup_token, skip_if_no_changes, requeue,
                         count_retry=None):
    '''Αφήνει το lock του job και βάζει νέο job για το dataset: ποτέ
    (REQUEUE_NEVER), μόνο αν το dataset άλλαξε όσο έτρεχε το job
    (REQUEUE_IF_CHANGED, dirty) ή πάντα (REQUEUE_ALWAYS).

    Σε σφάλμα της Redis ξαναδοκιμάζει λίγες φορές: ένα lock που μένει κρατά
    τις αλλαγές του dataset χωρίς job ως το TTL (dedup.get_lock_ttl).'''
    changed = False
    for attempt in range(RELEASE_ATTEMPTS):
        try:
            dedup.release_lock(package_id, dedup_token)
            if requeue == REQUEUE_IF_CHANGED:
                changed = dedup.is_dirty(package_id)
            break
        except dedup.RedisDedupError as exc:
            if attempt + 1 < RELEASE_ATTEMPTS:
                sleep(RELEASE_RETRY_SECONDS)
                continue
            log.warning('Redis coordination unavailable after the DownloadAll '
                        'job of %s; its lock expires after the TTL: %s',
                        package_id, exc)
            if requeue != REQUEUE_ALWAYS:
                return
    if requeue == REQUEUE_NEVER or (requeue == REQUEUE_IF_CHANGED and not changed):
        return
    if requeue == REQUEUE_IF_CHANGED:
        log.info('Dataset %s changed while its DownloadAll job was running; '
                 'queueing a new job', package_id)
    try:
        if count_retry is None:
            lib.enqueue_zip(package_id, skip_if_no_changes)
        else:
            lib.enqueue_zip(package_id, skip_if_no_changes,
                            count_retry=count_retry)
    except Exception:
        log.exception('Could not queue a new DownloadAll job for %s',
                      package_id)


def _context():
    return {'model': model, 'session': model.Session, 'ignore_auth': True}


def _site_ckan():
    return ckanapi.LocalCKAN()


def _update_zip_once(package_id, user=None, skip_if_no_changes=True,
                     deadline=None, count_retry=None):
    # Νέα ανάγνωση από τη βάση: σε επανάληψη μέσα στο ίδιο job ή στο
    # update-all-zips --synchronous, το session κρατά τα αντικείμενα όπως
    # ήταν όταν φορτώθηκαν (expire_on_commit=False), και το ZIP θα έβγαινε
    # από παλιά μεταδεδομένα
    model.Session.expire_all()
    try:
        dataset = toolkit.get_action('package_show')(_context(), {'id': package_id})
    except toolkit.ObjectNotFound:
        log.info('Dataset %s no longer exists; nothing to do', package_id)
        return
    if not eligibility.is_active(dataset):
        log.info('Dataset %s is %s; no DownloadAll ZIP', dataset['name'],
                 dataset.get('state'))
        return

    existing_zip = freshness.zip_resource(dataset)
    included, excluded = eligibility.split_resources(dataset)
    # Χωρίς πόρους για το ZIP δεν φτιάχνεται ZIP μόνο με μεταδεδομένα
    reason = eligibility.dataset_exclusion_reason(dataset) or \
        (None if included else eligibility.REASON_NO_RESOURCES)
    if reason:
        zips = [r for r in dataset.get('resources') or []
                if eligibility.is_zip_resource(r)]
        if not zips:
            log.info('No DownloadAll ZIP for %s (%s)', dataset['name'], reason)
        # Όλα τα ZIP, και τα διπλά: η διαγραφή είναι ενημέρωση του ίδιου του
        # job, οπότε δεν θα έμπαινε νέο job για όσα έμεναν
        for zip_res in zips:
            log.info('Removing the DownloadAll ZIP %s of %s (%s)',
                     zip_res['id'], dataset['name'], reason)
            _lock_dataset_zip(dataset['id'])
            with lib.own_update():
                _site_ckan().action.resource_delete(id=zip_res['id'])
        return

    fingerprint = freshness.compute_fingerprint(dataset)
    datapackage, pairs = generate_datapackage(dataset, included)
    datapackage_hash = hash_datapackage(datapackage)

    if skip_if_no_changes and existing_zip and existing_zip.get('size') and \
            existing_zip.get('downloadall_fingerprint') == fingerprint and \
            existing_zip.get('downloadall_datapackage_hash') == datapackage_hash:
        log.info('The DownloadAll ZIP of %s is up to date', dataset['name'])
        _retry_pending_cleanup(existing_zip)
        return

    log.info('Building the DownloadAll ZIP of %s (%d resources, %d excluded)',
             dataset['name'], len(included), len(excluded))
    build_dir = tempfile.mkdtemp(prefix='downloadall-')
    try:
        zip_path = os.path.join(build_dir, zip_filename(dataset['name']))
        manifest = write_zip(zip_path, dataset, datapackage, pairs, excluded,
                             build_dir, deadline)
        counts = manifest['counts']
        if not counts[STATUS_INCLUDED]:
            if existing_zip:
                log.warning('No resource of %s could be downloaded; keeping '
                            'the previous ZIP', dataset['name'])
                record_attempt(existing_zip['id'], fingerprint)
            else:
                log.warning('No resource of %s could be downloaded; no ZIP '
                            'created', dataset['name'])
                record_no_zip_attempt(dataset['id'], fingerprint)
            return
        save_zip(dataset, existing_zip, zip_path, fingerprint,
                 datapackage_hash, counts,
                 transient_failed=manifest.get('transient_failed', 0),
                 forced=(not skip_if_no_changes) if count_retry is None else bool(count_retry))
    except Exception:
        if existing_zip:
            record_attempt(existing_zip['id'], fingerprint)
        else:
            record_no_zip_attempt(dataset['id'], fingerprint)
        raise
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def record_no_zip_attempt(dataset_id, fingerprint):
    '''Όπως το record_attempt, για dataset χωρίς ZIP: η αποτυχία κρατιέται στη
    Redis (dedup.record_no_zip_attempt), ώστε το --retry-failed να μην το
    ξαναχτίζει κάθε βράδυ. Σφάλμα εδώ δεν κρύβει το αρχικό σφάλμα του job.'''
    try:
        dedup.record_no_zip_attempt(dataset_id, fingerprint)
    except Exception:
        log.exception('Could not record the DownloadAll attempt of dataset %s',
                      dataset_id)


def record_attempt(zip_resource_id, fingerprint):
    '''Σημειώνει στον πόρο ZIP ότι η ενημέρωσή του για την τρέχουσα εκδοχή του
    dataset δοκιμάστηκε και δεν ολοκληρώθηκε (κανένας πόρος δεν κατέβηκε, το
    dataset δεν περνά validation, timeout κ.λπ.). Έτσι το κουμπί δείχνει το
    προηγούμενο ZIP αντί να μένει κλειδωμένο χωρίς να περιμένει κανένα job
    (βλ. freshness.zip_state)· το ξαναδοκιμάζει το update-all-zips
    --retry-failed.

    Γράφεται απευθείας στη βάση και όχι με resource_patch, ώστε να γίνεται και
    όταν το dataset δεν περνά validation. Το CKAN ξαναπερνά το dataset στο Solr
    με το notify του commit. Σφάλμα εδώ δεν κρύβει το αρχικό σφάλμα του job.
    '''
    try:
        # Μετά από σφάλμα της βάσης το session χρειάζεται rollback
        model.Session.rollback()
        resource = model.Session.query(model.Resource).get(zip_resource_id)
        if resource is None:
            return
        extras = dict(resource.extras or {})
        if extras.get(freshness.ATTEMPTED_FIELD) == fingerprint:
            # Νέα αποτυχία της ίδιας εκδοχής (π.χ. --retry-failed)
            extras[freshness.ATTEMPTS_FIELD] = \
                freshness.build_count(extras, freshness.ATTEMPTS_FIELD) + 1
        else:
            extras[freshness.ATTEMPTED_FIELD] = fingerprint
            extras[freshness.ATTEMPTS_FIELD] = 1
        resource.extras = extras
        with lib.own_update():
            model.Session.commit()
    except Exception:
        log.exception('Could not record the DownloadAll attempt on resource %s',
                      zip_resource_id)
        model.Session.rollback()


def generate_datapackage(dataset, included):
    '''Το datapackage.json (μεταδεδομένα) και τα ζεύγη (πόρος CKAN, πόρος
    datapackage) για τους πόρους που μπαίνουν στο ZIP.'''
    datapackage = ckanapi.datapackage.dataset_to_datapackage(
        dict(dataset, resources=included))
    pairs = list(zip(included, datapackage.get('resources', [])))
    local_ckan = _site_ckan()
    for resource, datapackage_resource in pairs:
        try:
            ckanapi.datapackage.populate_datastore_res_fields(
                ckan=local_ckan, res=resource)
            ckanapi.datapackage.populate_schema_from_datastore(
                cres=resource, dres=datapackage_resource)
        except JobTimeoutException:
            raise
        except Exception as e:
            log.warning('Could not read the datastore schema of resource %s: %s',
                        resource.get('id'), e)
    for key in config.dataset_fields_to_add():
        datapackage[key] = dataset.get(key)
    return datapackage, pairs


def zip_filename(dataset_name):
    '''Νέο όνομα αρχείου σε κάθε build, ώστε το νέο ZIP να είναι ξεχωριστό blob
    από το προηγούμενο. Το όνομα του dataset κόβεται, ώστε η χρονοσφραγίδα να
    μη χαθεί στο όριο μήκους των ονομάτων αρχείων του CKAN.'''
    stamp = datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    base = (dataset_name or 'dataset')[:ZIP_NAME_MAX_DATASET_CHARS]
    return '%s-%s.zip' % (base, stamp)


def job_deadline(timeout=None):
    '''Χρονική στιγμή (time.monotonic) μετά την οποία δεν συνεχίζεται η λήψη
    πόρων, ώστε να μείνει χρόνος για την αποθήκευση του ZIP πριν το timeout
    του job. Μέσα σε RQ ισχύει το timeout του job, αλλιώς το timeout (π.χ.
    του CLI). None χωρίς κανένα από τα δύο.

    Το περιθώριο είναι 10% του timeout, τουλάχιστον 120 δευτερόλεπτα, αλλά
    ποτέ πάνω από το μισό· αλλιώς ένα μικρό timeout δεν θα άφηνε χρόνο για
    καμία λήψη.'''
    from rq import get_current_job
    job = get_current_job()
    if job is not None:
        timeout = getattr(job, 'timeout', None)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        return None
    margin = min(max(timeout * 0.1, 120), timeout / 2.0)
    return monotonic() + timeout - margin


def public_url(resource):
    '''URL του πόρου για το manifest, χωρίς στοιχεία σύνδεσης και χωρίς τιμές
    παραμέτρων που μπορεί να είναι μυστικά.'''
    url = resource.get('url') or ''
    try:
        parts = urlsplit(url)
    except ValueError:
        return ''
    netloc = parts.netloc.rsplit('@', 1)[-1]
    query = urlencode([
        (key, 'REDACTED' if key.lower() in SECRET_QUERY_KEYS else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)])
    return urlunsplit((parts.scheme, netloc, parts.path, query, ''))


def _manifest_entry(resource):
    return {'id': resource.get('id'), 'name': resource.get('name'),
            'format': resource.get('format'), 'url': public_url(resource)}


def write_zip(zip_path, dataset, datapackage, pairs, excluded, work_dir,
              deadline=None):
    '''Δημιουργεί το ZIP στο zip_path. Επιστρέφει το manifest.'''
    entries = []
    used = {DATAPACKAGE_NAME.lower(), MANIFEST_NAME.lower()}
    max_count = config.max_resources()
    max_total = config.max_total_size()
    total_size = 0
    included_count = 0
    transient_failed = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True,
                         strict_timestamps=False) as zipf:
        for position, (resource, datapackage_resource) in enumerate(pairs):
            entry = _manifest_entry(resource)
            if max_count and included_count >= max_count:
                entry.update(status=STATUS_EXCLUDED,
                             reason='resource limit (%d)' % max_count)
            elif deadline is not None and monotonic() > deadline:
                entry.update(status=STATUS_FAILED, reason='time limit')
            else:
                budget = max_total - total_size if max_total else None
                try:
                    filename, size = download_resource_into_zip(
                        resource, position, zipf, used, work_dir, deadline, budget)
                except DownloadError as e:
                    log.info('Resource %s not included: %s', resource.get('id'), e)
                    entry.update(status=STATUS_FAILED, reason=e.message)
                    if e.transient:
                        transient_failed += 1
                else:
                    total_size += size
                    included_count += 1
                    entry.update(status=STATUS_INCLUDED, filename=filename, size=size)
                    save_local_path_in_datapackage_resource(
                        datapackage_resource, resource, filename)
            entries.append(entry)
        for resource, reason in excluded:
            entry = _manifest_entry(resource)
            entry.update(status=STATUS_EXCLUDED, reason=reason)
            entries.append(entry)

        counts = dict((status, sum(1 for e in entries if e['status'] == status))
                      for status in (STATUS_INCLUDED, STATUS_EXCLUDED, STATUS_FAILED))
        manifest = {
            'dataset': dataset.get('name'),
            'generated': datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
            'counts': counts,
            'resources': entries,
        }
        _writestr(zipf, DATAPACKAGE_NAME, ckanapi.cli.utils.pretty_json(datapackage))
        _writestr(zipf, MANIFEST_NAME, json.dumps(
            manifest, indent=2, ensure_ascii=False).encode('utf-8'))
    log.info('ZIP %s: %d included, %d excluded, %d failed, %s',
             os.path.basename(zip_path), counts[STATUS_INCLUDED],
             counts[STATUS_EXCLUDED], counts[STATUS_FAILED],
             format_bytes(os.path.getsize(zip_path)))
    # Για τον πόρο ZIP (freshness.needs_retry)· δεν γράφεται στο ZIP
    manifest['transient_failed'] = transient_failed
    return manifest


def _writestr(zipf, name, data):
    info = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    zipf.writestr(info, data)


def save_local_path_in_datapackage_resource(datapackage_resource, res,
                                            filename):
    # Το path στο datapackage.json δείχνει πλέον στο αρχείο μέσα στο ZIP
    title = datapackage_resource.get('title') or res.get('title') \
        or res.get('name', '')
    datapackage_resource['sources'] = [
        {'title': title, 'path': datapackage_resource.get('path')}]
    datapackage_resource['path'] = filename


def _check_size(size, budget):
    max_size = config.max_resource_size()
    if max_size and size > max_size:
        raise DownloadError('larger than the limit of %s' % format_bytes(max_size))
    if budget is not None and size > budget:
        raise DownloadError('total size limit reached')


def _local_upload_path(resource):
    '''Διαδρομή του αρχείου ενός upload στην τοπική αποθήκευση του CKAN, αν
    υπάρχει (όχι με cloudstorage).'''
    if resource.get('url_type') != 'upload' or storage.cloudstorage_enabled():
        return None
    from ckan.lib.uploader import get_resource_uploader
    try:
        path = get_resource_uploader(dict(resource)).get_path(resource['id'])
    except (AttributeError, TypeError):
        return None
    return path if path and os.path.isfile(path) else None


def _download_url(resource):
    '''Από πού κατεβαίνει ο πόρος: για upload στο cloudstorage ένα signed URL
    (λειτουργεί και για ιδιωτικά datasets), αλλιώς το URL του πόρου.'''
    if resource.get('url_type') == 'upload' and storage.cloudstorage_enabled():
        try:
            from ckanext.cloudstorage.storage import ResourceCloudStorage
            signed = ResourceCloudStorage(dict(resource)).get_path(resource['id'])
            if signed:
                return signed
        except JobTimeoutException:
            raise
        except Exception as e:
            log.warning('Could not get the cloud storage URL of resource %s: %s',
                        resource.get('id'), e)
    return resource.get('url')


def _open(url, deadline):
    '''GET με streaming, timeouts και περιορισμένες επαναλήψεις για προσωρινές
    αποτυχίες (timeout, σύνδεση, 429, 5xx).'''
    retries = config.retries()
    timeout = (config.connect_timeout(), config.read_timeout())
    message = 'download failed'
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, stream=True, timeout=timeout)
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            message = 'connection failed: %s' % e
        except requests.exceptions.RequestException as e:
            raise DownloadError('invalid request: %s' % e)
        except JobTimeoutException:
            raise
        except Exception as e:
            # Π.χ. LocationParseError του urllib3 (host με πολύ μεγάλο όνομα,
            # και μετά από ανακατεύθυνση): αποτυχία του πόρου, όχι του ZIP
            raise DownloadError('invalid request: %s' % e)
        else:
            if response.status_code < 400:
                return response
            response.close()
            message = 'HTTP %s' % response.status_code
            if response.status_code != 429 and response.status_code < 500:
                raise DownloadError(message)
        if attempt < retries and (deadline is None or
                                  monotonic() + RETRY_DELAY_SECONDS < deadline):
            sleep(RETRY_DELAY_SECONDS)
        else:
            break
    # Εδώ φτάνουν μόνο οι προσωρινές αποτυχίες (σύνδεση, timeout, 429, 5xx)
    raise DownloadError(message, transient=True)


def _response_socket(response):
    '''Το socket της απάντησης (urllib3 1.x και 2.x), αν είναι διαθέσιμο.
    Όταν ο server κλείνει τη σύνδεση μετά την απάντηση (HTTP/1.0,
    «Connection: close»), η http.client αφήνει το connection.sock κενό και
    το socket μένει μόνο στο αντικείμενο που διαβάζει το σώμα.'''
    raw = getattr(response, 'raw', None)
    connection = getattr(raw, '_connection', None) or \
        getattr(raw, 'connection', None)
    sock = getattr(connection, 'sock', None)
    if sock is None:
        reader = getattr(getattr(raw, '_fp', None), 'fp', None)
        sock = getattr(getattr(reader, 'raw', None), '_sock', None)
    return sock


class _DeadlineGuard(object):
    '''Κόβει τη σύνδεση ενός πόρου στο χρονικό όριο του job.

    Το read_timeout ισχύει για κάθε ανάγνωση από το socket· ένας server που
    στέλνει λίγα bytes κάθε λίγο κρατά μία ανάγνωση των CHUNK_SIZE bytes για
    ώρες, και ο έλεγχος του ορίου ανάμεσα στα chunks δεν φτάνει ποτέ. Τότε το
    timeout της RQ θα έκοβε όλο το job και θα χανόταν όλο το ZIP. Το
    shutdown του socket από άλλο thread τελειώνει αμέσως την ανάγνωση.'''

    def __init__(self, response, deadline):
        self.fired = False
        self._timer = None
        sock = _response_socket(response) if deadline is not None else None
        if sock is None:
            return
        self._timer = threading.Timer(max(deadline - monotonic(), 0),
                                      self._fire, [sock])
        self._timer.daemon = True
        self._timer.start()

    def _fire(self, sock):
        self.fired = True
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except (OSError, ValueError):
            pass

    def cancel(self):
        if self._timer is not None:
            self._timer.cancel()


def _last_modified(response):
    value = response.headers.get('Last-Modified')
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def download_resource_into_zip(resource, position, zipf, used, work_dir,
                               deadline=None, budget=None):
    '''Κατεβάζει τον πόρο σε προσωρινό αρχείο (χωρίς να τον φορτώνει στη μνήμη)
    και τον προσθέτει στο ZIP. Επιστρέφει (όνομα στο ZIP, μέγεθος).

    Κάθε σφάλμα είναι αποτυχία του πόρου (DownloadError), όχι όλου του ZIP,
    εκτός από το JobTimeoutException της RQ, που σταματά πράγματι το job.
    '''
    try:
        local_path = _local_upload_path(resource)
    except JobTimeoutException:
        raise
    except Exception as e:
        # Π.χ. ο uploader δεν μπορεί να δημιουργήσει τον φάκελο αποθήκευσης
        raise DownloadError('could not read the uploaded file: %s' % e)
    if local_path:
        try:
            size = os.path.getsize(local_path)
            _check_size(size, budget)
            filename = filenames.make_unique(
                filenames.choose_filename(resource, position), used)
            zipf.write(local_path, arcname=filename)
        except (DownloadError, JobTimeoutException):
            raise
        except Exception as e:
            # Π.χ. δικαιώματα ή αρχείο που σβήστηκε στο μεταξύ: αποτυχία του
            # πόρου, όχι όλου του job
            raise DownloadError('could not read the uploaded file: %s' % e)
        return filename, size

    url = _download_url(resource)
    if not url:
        raise DownloadError('resource has no URL')
    response = _open(url, deadline)
    guard = _DeadlineGuard(response, deadline)
    tmp_path = os.path.join(work_dir, 'resource-%d.part' % position)
    try:
        length = response.headers.get('Content-Length')
        if length and length.isdigit():
            _check_size(int(length), budget)
        size = 0
        with open(tmp_path, 'wb') as out:
            for chunk in response.iter_content(CHUNK_SIZE):
                if not chunk:
                    continue
                size += len(chunk)
                _check_size(size, budget)
                if deadline is not None and monotonic() > deadline:
                    raise DownloadError('time limit')
                out.write(chunk)
        if guard.fired:
            # Η σύνδεση κόπηκε στο όριο· το αρχείο είναι μισό
            raise DownloadError('time limit')
        mtime = _last_modified(response)
        if mtime:
            os.utime(tmp_path, (mtime, mtime))
        filename = filenames.make_unique(filenames.choose_filename(
            resource, position,
            content_disposition=response.headers.get('Content-Disposition'),
            content_type=response.headers.get('Content-Type')), used)
        zipf.write(tmp_path, arcname=filename)
        return filename, size
    except JobTimeoutException:
        raise
    except Exception as e:
        if guard.fired:
            raise DownloadError('time limit')
        if isinstance(e, DownloadError):
            raise
        # Π.χ. σύνδεση που κόπηκε στη μέση της λήψης
        raise DownloadError('download failed: %s' % e, transient=isinstance(
            e, (requests.exceptions.RequestException, OSError)))
    finally:
        guard.cancel()
        response.close()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _pending_cleanup(zip_resource):
    return config.as_list(
        (zip_resource or {}).get('downloadall_cleanup_pending'), split=False)


def _cleanup(resource_id, current_filename, names, current_size=None):
    '''Σβήνει τα blobs των παλιών ZIP, μόνο αν το τρέχον ZIP υπάρχει στο
    storage με το σωστό μέγεθος (storage.blob_verified). Αλλιώς δεν σβήνεται
    κανένα και μένουν για επόμενη προσπάθεια. Επιστρέφει όσα δεν σβήστηκαν.'''
    # Ίδιο όνομα με το τρέχον: το blob αντικαταστάθηκε από το νέο ZIP
    names = [name for name in dict.fromkeys(names) if name != current_filename]
    if not names:
        return []
    if not storage.blob_verified(resource_id, current_filename, current_size):
        log.error('Keeping the previous DownloadAll ZIP blobs of resource %s: '
                  'the current ZIP could not be verified in the storage',
                  resource_id)
        return names
    remaining = []
    for name in names:
        if not storage.delete_upload_blob(resource_id, name):
            remaining.append(name)
    return remaining


def _store_pending(resource_id, attempted, remaining):
    '''Ενημερώνει το downloadall_cleanup_pending του πόρου ZIP μετά από
    διαγραφές blobs: βγαίνουν όσα σβήστηκαν (attempted χωρίς remaining) και
    μπαίνουν όσα δεν σβήστηκαν.

    Γράφει μόνο αυτό το πεδίο, απευθείας στη βάση και κάτω από το lock του
    dataset, με νέα ανάγνωση του πόρου. Ένα resource_patch θα ξανάγραφε όλο τον
    πόρο από παλιότερη ανάγνωση, π.χ. το url και το fingerprint ενός ZIP που
    στο μεταξύ αποθήκευσε άλλο job.'''
    package_id = model.Session.query(model.Resource.package_id) \
        .filter(model.Resource.id == resource_id).scalar()
    if package_id is None:
        return
    _lock_dataset_zip(package_id)
    resource = model.Session.query(model.Resource).populate_existing() \
        .filter(model.Resource.id == resource_id).first()
    current = _pending_cleanup(resource.extras if resource is not None else None)
    deleted = set(attempted) - set(remaining)
    current_file = storage.upload_filename(
        {'url': resource.url, 'url_type': resource.url_type}) if resource else None
    pending = [name for name in dict.fromkeys(
        [n for n in current if n not in deleted] + list(remaining))
        if name != current_file]
    if resource is None or pending == current:
        model.Session.rollback()
        return
    extras = dict(resource.extras or {})
    extras['downloadall_cleanup_pending'] = json.dumps(pending) if pending else ''
    resource.extras = extras
    with lib.own_update():
        model.Session.commit()


def _retry_pending_cleanup(zip_resource):
    pending = _pending_cleanup(zip_resource)
    if not pending:
        return
    remaining = _cleanup(zip_resource['id'],
                         storage.upload_filename(zip_resource), pending,
                         zip_resource.get('size'))
    _store_pending(zip_resource['id'], pending, remaining)


def _lock_dataset_zip(dataset_id):
    '''Κλειδώνει ως το commit την αποθήκευση του ZIP του dataset, ώστε δύο
    jobs που τελειώνουν μαζί (π.χ. δύο πρώτα builds) να μη φτιάξουν δύο πόρους
    ZIP ή να σβήσει το ένα το αρχείο του άλλου. Advisory lock της PostgreSQL:
    δεν μπλοκάρει τις αλλαγές των χρηστών στο dataset.'''
    digest = hashlib.sha1(('ckanext-downloadall:' + dataset_id).encode('utf-8'))
    key = int(digest.hexdigest()[:15], 16)
    model.Session.execute(sa.text('SELECT pg_advisory_xact_lock(:key)'),
                          {'key': key})


def _current_zip(dataset_id):
    '''Ο πόρος ZIP του dataset όπως είναι τώρα στη βάση (freshness.zip_resource:
    ο πρώτος με τη σειρά των πόρων), ως dict, ή None.'''
    resources = model.Session.query(model.Resource) \
        .filter(model.Resource.package_id == dataset_id) \
        .filter(model.Resource.state == 'active') \
        .order_by(model.Resource.position) \
        .populate_existing()
    for resource in resources:
        if eligibility.is_zip_model_resource(resource):
            return dict(resource.extras or {}, id=resource.id,
                        url=resource.url, url_type=resource.url_type)
    return None


def save_zip(dataset, existing_zip, zip_path, fingerprint, datapackage_hash,
             counts, transient_failed=0, forced=False):
    '''Αποθηκεύει το ZIP ως πόρο του dataset και, μετά την επιτυχία, σβήνει
    ακριβώς το blob του προηγούμενου ZIP. Αν η αποθήκευση αποτύχει, το
    προηγούμενο ZIP μένει ανέπαφο.

    Ο πόρος ZIP και το dataset ξαναδιαβάζονται κάτω από το lock του dataset,
    γιατί είναι από την αρχή του build: στο μεταξύ μπορεί άλλο job να έφτιαξε
    ή να άλλαξε το ZIP, ή να άλλαξε το dataset (handoff του OD-857, §3: πριν
    ενεργοποιηθεί το νέο ZIP, επανελέγχεται το τρέχον fingerprint):

      - το dataset δεν δικαιούται πια ZIP (π.χ. έγινε ιδιωτικό): δεν
        αποθηκεύεται, και μπαίνει job για το καθάρισμα·
      - το dataset άλλαξε και υπάρχει ήδη ZIP της νέας εκδοχής: δεν
        αποθηκεύεται, για να μη γραφτεί παλιότερο build πάνω σε νεότερο·
      - το dataset άλλαξε χωρίς νεότερο ZIP: αποθηκεύεται με το fingerprint
        της εκδοχής που χτίστηκε (άρα δεν φαίνεται ενημερωμένο) και μπαίνει
        μία ακόμη επεξεργασία της τελευταίας κατάστασης.

    :param forced: build χωρίς έλεγχο αλλαγών (π.χ. --retry-failed)· μόνο αυτά
        μετρούν στο όριο downloadall_retries
    :returns: ο πόρος ZIP που αποθηκεύτηκε, ή None αν δεν αποθηκεύτηκε'''
    _lock_dataset_zip(dataset['id'])
    # Το resource_patch/create ξαναδιαβάζει το dataset (package_show) και το
    # γράφει ολόκληρο (package_update)· χωρίς expire θα έγραφε τα μεταδεδομένα
    # όπως ήταν στην αρχή του build, πάνω σε αλλαγές που έγιναν στο μεταξύ
    model.Session.expire_all()
    existing_zip = _current_zip(dataset['id'])
    changed = False
    try:
        latest = toolkit.get_action('package_show')(_context(), {'id': dataset['id']})
    except toolkit.ObjectNotFound:
        model.Session.rollback()
        log.info('Dataset %s was deleted during its DownloadAll build', dataset['name'])
        return None
    if not eligibility.is_active(latest) or \
            eligibility.dataset_exclusion_reason(latest) or \
            not freshness.included_resources(latest):
        model.Session.rollback()
        log.info('Dataset %s no longer gets a DownloadAll ZIP; not saving the '
                 'build', dataset['name'])
        _queue_follow_up(dataset['id'])
        return None
    latest_fingerprint = freshness.compute_fingerprint(latest)
    if latest_fingerprint != fingerprint:
        if existing_zip and \
                existing_zip.get('downloadall_fingerprint') == latest_fingerprint:
            model.Session.rollback()
            log.info('A newer DownloadAll ZIP of %s is already saved; discarding '
                     'this build', dataset['name'])
            return None
        changed = True
    old_filename = storage.upload_filename(existing_zip)
    pending = _pending_cleanup(existing_zip)
    # Builds χωρίς έλεγχο αλλαγών της ίδιας εκδοχής: όριο για το --retry-failed
    previous_retries = freshness.build_count(existing_zip, freshness.RETRIES_FIELD)
    if existing_zip and existing_zip.get('downloadall_fingerprint') == fingerprint:
        retries = previous_retries + 1 if forced else previous_retries
    else:
        retries = 0
    fields = dict(
        package_id=dataset['id'],
        url=os.path.basename(zip_path),
        name=ZIP_RESOURCE_NAME,
        name_translated=ZIP_RESOURCE_NAME_TRANSLATED,
        format=u'ZIP',
        downloadall_metadata_modified=dataset['metadata_modified'],
        downloadall_datapackage_hash=datapackage_hash,
        downloadall_fingerprint=fingerprint,
        downloadall_built_at=datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
        downloadall_included=counts[STATUS_INCLUDED],
        downloadall_excluded=counts[STATUS_EXCLUDED],
        downloadall_failed=counts[STATUS_FAILED],
        downloadall_failed_transient=transient_failed,
        downloadall_retries=retries,
        downloadall_cleanup_pending=json.dumps(pending) if pending else '',
        # Το νέο ZIP αντιστοιχεί στο fingerprint του· μια παλιά αποτυχημένη
        # προσπάθεια δεν πρέπει να κάνει «ready» ένα ZIP άλλης εκδοχής
        downloadall_attempted_fingerprint='',
        downloadall_attempts='',
    )
    local_ckan = _site_ckan()
    try:
        with open(zip_path, 'rb') as fp, lib.own_update():
            if existing_zip:
                saved = local_ckan.action.resource_patch(
                    id=existing_zip['id'], upload=fp, **fields)
            else:
                saved = local_ckan.action.resource_create(upload=fp, **fields)
    except toolkit.ValidationError as e:
        log.error('Cannot save the DownloadAll ZIP of %s: the dataset does not '
                  'pass validation: %s', dataset['name'], e.error_dict)
        raise
    log.info('Saved the DownloadAll ZIP of %s (resource %s)',
             dataset['name'], saved['id'])
    try:
        dedup.clear_no_zip_attempts(dataset['id'])
    except dedup.RedisDedupError:
        pass

    names = list(pending)
    if old_filename:
        names.append(old_filename)
    # Το blob του νέου ZIP ελέγχεται με το μέγεθος του αρχείου που ανέβηκε
    remaining = _cleanup(saved['id'], storage.upload_filename(saved), names,
                         os.path.getsize(zip_path))
    _store_pending(saved['id'], names, remaining)
    if changed:
        log.info('Dataset %s changed during its DownloadAll build; the saved '
                 'ZIP is not current, processing the latest state', dataset['name'])
        _queue_follow_up(dataset['id'])
    return saved


def _queue_follow_up(package_id):
    '''Μία ακόμη επεξεργασία του dataset. Με redis, μέσα στο job το lock είναι
    δικό μας: σημειώνεται dirty και το ίδιο job ξαναεπεξεργάζεται το dataset.'''
    try:
        lib.enqueue_zip(package_id)
    except Exception:
        log.exception('Could not queue a new DownloadAll job for %s', package_id)


def hash_datapackage(datapackage):
    '''Returns a hash of the canonized version of the given datapackage
    (metadata).
    '''
    canonized = canonized_datapackage(datapackage)
    m = hashlib.md5(six.text_type(make_hashable(canonized)).encode('utf8'))
    return m.hexdigest()


def make_hashable(obj):
    if isinstance(obj, (tuple, list)):
        return tuple((make_hashable(e) for e in obj))
    if isinstance(obj, dict):
        return tuple(sorted((k, make_hashable(v)) for k, v in obj.items()))
    return obj


def canonized_datapackage(datapackage):
    '''
    The given datapackage is 'canonized', so that an exsting one can be
    compared with a freshly generated one, to see if the zip needs
    regenerating.

    Datapackages resources have either:
    * local paths (downloaded into the package) OR
    * OR remote paths (URLs)
    To allow datapackages to be compared, the canonization converts local
    resources to remote ones.
    '''
    datapackage_ = copy.deepcopy(datapackage)
    # Ο τίτλος της άδειας μεταφράζεται και διαφέρει ανάμεσα στο Solr και στη
    # βάση (βλ. freshness)· μετρά μόνο το license_id
    license_ = datapackage_.get('license')
    if isinstance(license_, dict):
        license_.pop('title', None)
        license_.pop('url', None)
    for res in datapackage_.get('resources', []):
        try:
            remote_path = res['sources'][0]['path']
        except (KeyError, IndexError):
            continue
        res['path'] = remote_path
        del res['sources']
    return datapackage_


def format_bytes(size_bytes):
    if size_bytes == 0:
        return "0 bytes"
    size_name = ("bytes", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 1)
    return '{} {}'.format(s, size_name[i])
