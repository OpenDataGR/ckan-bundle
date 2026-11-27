# -*- coding: utf-8 -*-
'''
Ρυθμίσεις του ckanext-downloadall (OD-857). Οι προεπιλογές αντιστοιχούν στη
συμπεριφορά πριν την αλλαγή. Οι ρυθμίσεις του συντονισμού των jobs
(dedup_strategy, redis_lock_ttl) διαβάζονται στο dedup.py.

Όλες οι ρυθμίσεις δηλώνονται στο config_declaration.yaml.
'''
import json
import logging

from ckan.plugins import toolkit

log = logging.getLogger(__name__)


def _get(key, default):
    value = toolkit.config.get(key, default)
    return default if value is None else value


def _int(key, default, minimum=0):
    value = _get(key, default)
    try:
        value = int(value)
    except (TypeError, ValueError):
        log.warning('Invalid integer for %s: %r; using %r', key, value, default)
        return default
    return max(value, minimum)


def as_list(value, split=True):
    '''Λίστα από Python list, JSON list ή κείμενο. Κενές τιμές αγνοούνται.

    Με split=True (ρυθμίσεις) το κείμενο χωρίζεται σε κόμματα και νέες
    γραμμές. Με split=False ένα κείμενο που δεν είναι JSON list είναι μία τιμή
    (π.χ. κατηγορία HVD ή όνομα αρχείου, που μπορεί να έχει κόμμα).
    '''
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        text = str(value).strip()
        if not text:
            return []
        items = None
        if text.startswith('['):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if isinstance(parsed, list):
                items = parsed
            elif split:
                log.warning('Invalid JSON list: %r', text)
                text = text.strip('[]')
        if items is None:
            items = text.replace('\n', ',').split(',') if split else [text]
    cleaned = (str(item).strip().strip('"\'').strip()
               for item in items if item is not None)
    return [item for item in cleaned if item]


def queue_name():
    '''Η πραγματική ουρά RQ των jobs του DownloadAll.'''
    return str(_get('ckanext.downloadall.queue', 'bulk')).strip() or 'bulk'


def hvd_only():
    return toolkit.asbool(_get('ckanext.downloadall.hvd_only', False))


def hvd_field():
    return str(_get('ckanext.downloadall.hvd_field', 'hvd_category')).strip() \
        or 'hvd_category'


def excluded_formats():
    return set(f.lower() for f in as_list(
        _get('ckanext.downloadall.exclude_resource_formats', '')))


def excluded_name_patterns():
    return [p.lower() for p in as_list(
        _get('ckanext.downloadall.exclude_resource_name_patterns', ''))]


def connect_timeout():
    return _int('ckanext.downloadall.connect_timeout', 10, 1)


def read_timeout():
    return _int('ckanext.downloadall.read_timeout', 60, 1)


def retries():
    return _int('ckanext.downloadall.retries', 1, 0)


def retry_failed_limit():
    '''Πόσες φορές το update-all-zips --retry-failed ξαναχτίζει την ίδια
    εκδοχή ενός dataset (0 = χωρίς όριο).'''
    return _int('ckanext.downloadall.retry_failed_limit', 3, 0)


def job_timeout():
    '''Timeout του job ενός dataset· None σημαίνει ckan.jobs.timeout.'''
    value = _int('ckanext.downloadall.job_timeout', 1800, 0)
    return value or None


def max_resources():
    return _int('ckanext.downloadall.max_resources', 0, 0)


def max_resource_size():
    return _int('ckanext.downloadall.max_resource_size', 0, 0)


def max_total_size():
    return _int('ckanext.downloadall.max_total_size', 0, 0)


def dataset_fields_to_add():
    return str(_get('ckanext.downloadall.dataset_fields_to_add_to_datapackage',
                    '')).split()
