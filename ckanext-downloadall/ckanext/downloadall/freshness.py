# -*- coding: utf-8 -*-
'''
Fingerprint του περιεχομένου του ZIP και κατάσταση του κουμπιού «Λήψη όλων»
(OD-857).

Το fingerprint υπολογίζεται από τα μεταδεδομένα του dataset και των πόρων που
μπαίνουν στο ZIP, και αποθηκεύεται στον πόρο ZIP (downloadall_fingerprint).
Επειδή αποθηκεύεται στη βάση, ένα restart της Redis δεν κάνει ποτέ ένα παλιό
ZIP να φαίνεται ενημερωμένο. Υπολογίζεται με τον ίδιο τρόπο στον worker και
στη σελίδα, από το αποτέλεσμα του package_show.

Δεν περιλαμβάνει πεδία που αλλάζουν χωρίς να αλλάζει το περιεχόμενο του ZIP:
metadata_modified, qa, archiver, MQA, το ίδιο το ZIP και τα extras του
dataset. Τα extras ξανατακτοποιούνται από το scheming σε κάθε package_update
(π.χ. στην πρώτη αποθήκευση του ZIP), οπότε θα έκαναν ένα μόλις
δημιουργημένο ZIP να φαίνεται μη ενημερωμένο.

Ούτε τα license_title και license_url: προκύπτουν από το license_id (που
μετρά) και ο τίτλος μεταφράζεται, οπότε διαφέρει ανάμεσα στην εγγραφή του
Solr και στο dataset από τη βάση (π.χ. αγγλικός στο παλιό index, ελληνικός
μετά την πρώτη αποθήκευση του ZIP).
'''
import hashlib
import json

from . import config
from . import eligibility

DATASET_FIELDS = (
    'name', 'title', 'title_translated', 'notes', 'notes_translated',
    'version', 'url', 'license_id',
    'author', 'author_email', 'maintainer', 'maintainer_email',
)
RESOURCE_FIELDS = (
    'id', 'name', 'name_translated', 'description', 'description_translated',
    'url_type', 'format', 'mimetype', 'size', 'last_modified', 'hash',
    'schema',
)

STATE_READY = 'ready'
STATE_STALE = 'stale'
STATE_NONE = 'none'
STATE_HIDDEN = 'hidden'

# Fingerprint της εκδοχής του dataset για την οποία η ενημέρωση του ZIP
# δοκιμάστηκε και δεν ολοκληρώθηκε (βλ. tasks.record_attempt)
ATTEMPTED_FIELD = 'downloadall_attempted_fingerprint'
# Διαδοχικές αποτυχημένες προσπάθειες για αυτό το fingerprint
ATTEMPTS_FIELD = 'downloadall_attempts'
# Πόροι του τελευταίου build με αποτυχία που μπορεί να είναι προσωρινή
# (timeout, σύνδεση, 5xx, 429)
TRANSIENT_FIELD = 'downloadall_failed_transient'
# Διαδοχικά builds της ίδιας εκδοχής του dataset (--retry-failed)
RETRIES_FIELD = 'downloadall_retries'


def zip_resource(dataset):
    '''Ο πόρος ZIP του dataset. Αν υπάρχουν περισσότεροι (π.χ. από δύο
    ταυτόχρονα πρώτα builds), ο πρώτος με τη σειρά των πόρων: αυτόν
    ενημερώνει το job, αυτόν δείχνει η σελίδα και αυτόν κρατά το cleanup.'''
    for resource in dataset.get('resources') or []:
        if eligibility.is_zip_resource(resource):
            return resource
    return None


def included_resources(dataset):
    '''Οι πόροι που μπαίνουν στο ZIP, με τη σειρά τους.'''
    return eligibility.split_resources(dataset)[0]


def _resource_url(resource):
    url = resource.get('url') or ''
    if resource.get('url_type') == 'upload':
        # Το πλήρες URL ενός upload περιέχει το ckan.site_url· κρατιέται μόνο
        # το όνομα αρχείου, ώστε να μην εξαρτάται από τη διεύθυνση του site
        return url.rstrip('/').rsplit('/', 1)[-1]
    return url


def compute_fingerprint(dataset):
    tags = sorted((t.get('name') or '') if isinstance(t, dict) else str(t)
                  for t in dataset.get('tags') or [])
    payload = {
        'dataset': dict((key, dataset.get(key)) for key in DATASET_FIELDS),
        'tags': tags,
        'extra_fields': dict((key, dataset.get(key))
                             for key in config.dataset_fields_to_add()),
        'resources': [
            dict([(key, resource.get(key)) for key in RESOURCE_FIELDS],
                 url=_resource_url(resource))
            for resource in included_resources(dataset)
        ],
    }
    text = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def zip_state(dataset, zip_res=None):
    '''Κατάσταση του κουμπιού «Λήψη όλων» για το dataset.

    hidden: το dataset δεν αποκτά ZIP (μη ενεργό, ιδιωτικό, μη HVD με
        hvd_only κ.λπ.) ή
        κανένας πόρος του δεν μπαίνει σε ZIP
    none: δεν υπάρχει ακόμη ZIP
    stale: υπάρχει ZIP, αλλά το dataset άλλαξε από τότε
    ready: το ZIP αντιστοιχεί στην τρέχουσα εκδοχή του dataset

    Ready είναι και:
      - ένα ZIP χωρίς fingerprint (από πριν το OD-857), όπως πριν·
      - το προηγούμενο ZIP, όταν η ενημέρωσή του για την τρέχουσα εκδοχή
        δοκιμάστηκε και απέτυχε. Αλλιώς το κουμπί θα έμενε κλειδωμένο χωρίς
        να περιμένει κανένα job· ξαναδοκιμάζεται με update-all-zips
        --retry-failed.

    :param zip_res: ο πόρος ZIP, αν έχει ήδη αφαιρεθεί από το dataset
        (helpers.pop_zip_resource)
    '''
    if not eligibility.is_active(dataset) or \
            eligibility.dataset_exclusion_reason(dataset) or \
            not included_resources(dataset):
        return STATE_HIDDEN
    zip_res = zip_res or zip_resource(dataset)
    if not zip_res:
        return STATE_NONE
    stored = zip_res.get('downloadall_fingerprint')
    if not stored:
        return STATE_READY
    current = compute_fingerprint(dataset)
    if current in (stored, zip_res.get(ATTEMPTED_FIELD)):
        return STATE_READY
    return STATE_STALE


def build_count(zip_res, key):
    '''Ένας μετρητής του τελευταίου build (downloadall_included, _excluded,
    _failed)· 0 αν λείπει ή δεν είναι αριθμός.'''
    try:
        return int((zip_res or {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0


def failed_count(zip_res):
    '''Πόσοι πόροι δεν κατέβηκαν στο τελευταίο build του ZIP.'''
    return build_count(zip_res, 'downloadall_failed')


def _within_limit(count):
    limit = config.retry_failed_limit()
    return not limit or count < limit


def needs_retry(dataset):
    '''True αν το dataset χρειάζεται νέο build από το update-all-zips
    --retry-failed (ημερήσιο cron):

      - δεν έχει ZIP, ή το ZIP δεν αντιστοιχεί στην τρέχουσα εκδοχή του
        (π.χ. χάθηκε το job)· αν όμως το build αυτής της εκδοχής απέτυχε,
        το πολύ retry_failed_limit νέες προσπάθειες (για dataset χωρίς ZIP
        οι αποτυχίες κρατιούνται στη Redis, dedup.no_zip_attempts)·
      - στο τελευταίο build απέτυχαν πόροι με αποτυχία που μπορεί να είναι
        προσωρινή (timeout, σύνδεση, 5xx, 429), το πολύ retry_failed_limit
        φορές για την ίδια εκδοχή, μαζί με τα builds της που απέτυχαν όλα.

    Οι μόνιμες αποτυχίες (π.χ. 404, 403, όριο μεγέθους ή χρόνου) δεν
    ξαναδοκιμάζονται κάθε βράδυ· ξαναδοκιμάζονται όταν αλλάξει το dataset.

    Ένα ZIP από πριν το OD-857 (χωρίς fingerprint) θεωρείται ενημερωμένο,
    όπως και στη σελίδα (zip_state): δεν ξαναχτίζεται αυτόματα, γιατί αυτό θα
    έσβηνε και το παλιό blob. Η μετάβαση γίνεται ρητά, με update-all-zips.
    '''
    if not eligibility.is_active(dataset) or \
            eligibility.dataset_exclusion_reason(dataset) or \
            not included_resources(dataset):
        return False
    zip_res = zip_resource(dataset)
    current = compute_fingerprint(dataset)
    if not zip_res:
        attempted, attempts = _no_zip_attempts(dataset)
        if attempted == current:
            # Η πρώτη αποτυχία δεν μετρά ως νέα προσπάθεια
            return _within_limit(attempts - 1)
        return True
    if not zip_res.get('downloadall_fingerprint'):
        return False
    if zip_res.get('downloadall_fingerprint') != current:
        if zip_res.get(ATTEMPTED_FIELD) == current:
            # Η πρώτη αποτυχία δεν μετρά ως νέα προσπάθεια
            return _within_limit(build_count(zip_res, ATTEMPTS_FIELD) - 1)
        return True
    if zip_res.get(TRANSIENT_FIELD) in (None, ''):
        # ZIP από πριν την καταμέτρηση: όπως πριν, κάθε αποτυχημένος πόρος
        failing = failed_count(zip_res) > 0
    else:
        failing = build_count(zip_res, TRANSIENT_FIELD) > 0
    retries = build_count(zip_res, RETRIES_FIELD)
    if zip_res.get(ATTEMPTED_FIELD) == current:
        # Νέα builds της ίδιας εκδοχής που απέτυχαν όλα (π.χ. validation)
        retries += build_count(zip_res, ATTEMPTS_FIELD)
    return failing and _within_limit(retries)


def _no_zip_attempts(dataset):
    from . import dedup
    if not dataset.get('id'):
        return None, 0
    try:
        return dedup.no_zip_attempts(dataset['id'])
    except dedup.RedisDedupError:
        return None, 0
