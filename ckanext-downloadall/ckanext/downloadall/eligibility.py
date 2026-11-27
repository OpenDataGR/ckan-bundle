# -*- coding: utf-8 -*-
'''
Ποια datasets αποκτούν ZIP «Λήψη όλων» και ποιοι πόροι μπαίνουν σε αυτό
(OD-857).

Οι αποκλεισμένοι πόροι δεν αφαιρούνται από το dataset· απλώς δεν μπαίνουν στο
ZIP και καταγράφονται στο downloadall-manifest.json.
'''
import json

from ckan.plugins import toolkit

from . import config
from . import helpers

# Τύποι datasets χωρίς ZIP (όπως πριν το OD-857)
NOT_ELIGIBLE_TYPES = ('showcase',)

# Αιτίες αποκλεισμού (γράφονται στο manifest)
REASON_DATA_SERVICE = 'data service'
REASON_TYPE = 'dataset type'
REASON_PRIVATE = 'private dataset'
REASON_NOT_HVD = 'not a high-value dataset'
REASON_NO_RESOURCES = 'no resources for the zip'
REASON_FORMAT = 'excluded format'
REASON_MARKER = 'marked downloadall_exclude'
REASON_NAME = 'excluded name'


ZIP_MARKER = 'downloadall_metadata_modified'


def is_zip_resource(resource):
    '''Ο πόρος (dict) είναι το ίδιο το ZIP του DownloadAll.'''
    return bool(resource.get(ZIP_MARKER))


def is_zip_model_resource(resource):
    '''Το ίδιο για model.Resource.'''
    return bool((resource.extras or {}).get(ZIP_MARKER))


def is_active(dataset):
    '''Μόνο τα ενεργά datasets έχουν ZIP· όχι τα πρόχειρα (draft), που αλλιώς
    θα μπορούσαν να δημοσιευτούν με μόνο πόρο το ZIP, ούτε τα διαγραμμένα.'''
    return (dataset.get('state') or 'active') == 'active'


def _field(dataset, key):
    '''Πεδίο του dataset: στο πρώτο επίπεδο (scheming) ή στα extras.'''
    if dataset.get(key) is not None:
        return dataset.get(key)
    extras = dataset.get('extras')
    if isinstance(extras, dict):
        return extras.get(key)
    for extra in extras or []:
        if isinstance(extra, dict) and extra.get('key') == key:
            return extra.get('value')
    return None


def has_hvd(dataset):
    '''True αν το dataset έχει τουλάχιστον μία κατηγορία HVD. Διαβάζει το
    πεδίο του dataset (όχι το is_hvd του Solr, που ανανεώνεται μόνο στο
    reindex).'''
    return bool(config.as_list(_field(dataset, config.hvd_field()), split=False))


def is_private(dataset):
    '''Ιδιωτικό dataset. Το ZIP του θα έπρεπε να κατεβάσει τους πόρους που
    σερβίρει το ίδιο το CKAN (π.χ. datastore dump) με στοιχεία σύνδεσης, που
    ο worker δεν έχει· παίρνει ZIP όταν γίνει δημόσιο.'''
    try:
        return toolkit.asbool(dataset.get('private') or False)
    except ValueError:
        return False


def dataset_exclusion_reason(dataset):
    '''None αν το dataset πρέπει να έχει ZIP, αλλιώς η αιτία.'''
    if helpers.is_data_service(dataset):
        return REASON_DATA_SERVICE
    if dataset.get('type') in NOT_ELIGIBLE_TYPES:
        return REASON_TYPE
    if is_private(dataset):
        return REASON_PRIVATE
    if config.hvd_only() and not has_hvd(dataset):
        return REASON_NOT_HVD
    return None


def _resource_names(resource):
    names = [resource.get('name')]
    translated = resource.get('name_translated')
    if isinstance(translated, str):
        try:
            translated = json.loads(translated)
        except ValueError:
            translated = {'': translated}
    if isinstance(translated, dict):
        names.extend(translated.values())
    return [str(name).lower() for name in names if name]


def _marked(value):
    '''Τιμή του downloadall_exclude. Μια τιμή που δεν είναι boolean (π.χ.
    «ναι») αγνοείται, αντί να ρίξει τη σελίδα του dataset και το job.'''
    try:
        return toolkit.asbool(value or False)
    except ValueError:
        return False


def resource_exclusion_reason(resource):
    '''None αν ο πόρος μπαίνει στο ZIP, αλλιώς η αιτία αποκλεισμού.'''
    resource_format = (resource.get('format') or '').strip().lower()
    if resource_format and resource_format in config.excluded_formats():
        return REASON_FORMAT
    if _marked(resource.get('downloadall_exclude')):
        return REASON_MARKER
    patterns = config.excluded_name_patterns()
    if patterns:
        names = _resource_names(resource)
        for pattern in patterns:
            if any(pattern in name for name in names):
                return REASON_NAME
    return None


def split_resources(dataset):
    '''(πόροι που μπαίνουν στο ZIP με τη σειρά τους, [(αποκλεισμένος πόρος,
    αιτία)]). Το ίδιο το ZIP δεν περιλαμβάνεται σε κανένα από τα δύο.'''
    included, excluded = [], []
    for resource in dataset.get('resources') or []:
        if is_zip_resource(resource):
            continue
        reason = resource_exclusion_reason(resource)
        if reason:
            excluded.append((resource, reason))
        else:
            included.append(resource)
    return included, excluded


def model_view(package):
    '''Ελαφριά εικόνα ενός model.Package για τον έλεγχο επιλεξιμότητας στο
    notify, χωρίς package_show (τρέχει πριν από το commit).'''
    return {'type': package.type, 'private': package.private,
            'extras': dict(package.extras or {})}


def package_needs_job(package):
    '''True αν μια αλλαγή στο model.Package πρέπει να βάλει job: όταν το
    dataset αποκτά ZIP, ή όταν δεν το δικαιούται αλλά έχει ακόμη (για να
    σβηστεί). Έτσι, με hvd_only, οι αλλαγές σε μη HVD datasets δεν γεμίζουν
    την ουρά. Τα πρόχειρα και τα διαγραμμένα datasets δεν βάζουν job. Ένα
    ιδιωτικό dataset που γίνεται δημόσιο βάζει job για το πρώτο ZIP του.'''
    if package.state != 'active':
        return False
    if dataset_exclusion_reason(model_view(package)) is None:
        return True
    return any(is_zip_model_resource(resource) for resource in package.resources)
