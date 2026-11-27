NON_EVALUABLE = 'non_evaluable'
BROKEN = 'broken'

TABLEDESIGNER_REASON = 'Resource is a Table Designer resource'
NO_URL_REASON = 'Resource has no URL'
DOWNLOADALL_REASON = 'Resource is a Download All ZIP resource'


def _resource_field(resource, key, default=None):
    if isinstance(resource, dict):
        return resource.get(key, default)

    if hasattr(resource, key):
        return getattr(resource, key)

    extras = getattr(resource, 'extras', None)
    if extras:
        return extras.get(key, default)

    return default


def _normalized_url(resource):
    return (_resource_field(resource, 'url') or '').strip()


def get_non_evaluable_resource_reason(resource):
    if _resource_field(resource, 'downloadall_metadata_modified'):
        return DOWNLOADALL_REASON
    if _resource_field(resource, 'url_type') == 'tabledesigner':
        return TABLEDESIGNER_REASON
    if not _normalized_url(resource):
        return NO_URL_REASON
    return None


def get_resource_evaluation_state(resource, archival):
    if get_non_evaluable_resource_reason(resource):
        return NON_EVALUABLE
    if archival and archival.is_broken is True:
        return BROKEN
    return None


# Καταστάσεις του τελευταίου ελέγχου URL (κυρίως για check_only)
CHECK_AVAILABLE = 'available'
CHECK_CONFIRMED_BROKEN = 'confirmed_broken'
CHECK_TRANSIENT_FAILURE = 'transient_failure'
CHECK_UNKNOWN = 'unknown'
CHECK_STALE = 'stale'

STALE_AFTER_DAYS_CONFIG = 'ckanext.archiver.check_only.stale_after_days'
DEFAULT_STALE_AFTER_DAYS = 14


def get_url_check_state(archival, now=None):
    '''Κατάσταση του τελευταίου ελέγχου του resource.url.

    unknown: δεν υπάρχει έλεγχος ή δεν ήταν δυνατός (π.χ. Chose not to download)
    stale: (μόνο στο check_only) ο τελευταίος έλεγχος είναι παλαιότερος από
        stale_after_days. Στο archive mode το updated δεν ανανεώνεται όταν το
        περιεχόμενο δεν έχει αλλάξει (ίδιο ETag), οπότε δεν είναι ένδειξη ελέγχου.
    available: το URL απάντησε επιτυχώς
    confirmed_broken: το URL χαρακτηρίστηκε broken
    transient_failure: προσωρινή/αβέβαιη αποτυχία (π.χ. timeout, 429, 5xx)
    '''
    import datetime
    from ckanext.archiver.lib import _config_int, is_check_only_mode
    from ckanext.archiver.model import Status

    if archival is None or archival.status_id is None:
        return CHECK_UNKNOWN

    if is_check_only_mode():
        stale_after_days = _config_int(STALE_AFTER_DAYS_CONFIG,
                                       DEFAULT_STALE_AFTER_DAYS, 0)
        now = now or datetime.datetime.now()
        if archival.updated and stale_after_days > 0 and \
                now - archival.updated > datetime.timedelta(days=stale_after_days):
            return CHECK_STALE

    if Status.is_ok(archival.status_id):
        return CHECK_AVAILABLE
    if archival.is_broken is True:
        return CHECK_CONFIRMED_BROKEN
    if archival.status_id == Status.by_text('Chose not to download'):
        return CHECK_UNKNOWN
    return CHECK_TRANSIENT_FAILURE
