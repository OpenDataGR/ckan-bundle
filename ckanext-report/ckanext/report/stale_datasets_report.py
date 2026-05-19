'''
Stale datasets report - identifies datasets that haven't been updated according to their frequency.
'''

from ckan import model
from datetime import date, datetime
from ckan.plugins import toolkit
import six

try:
    from collections import OrderedDict  # from python 2.7
except ImportError:
    from sqlalchemy.util import OrderedDict

from ckanext.report import lib


# STRICT Frequency mapping - maps frequency values to EXACT time intervals in days
# Each frequency value corresponds EXACTLY to its literal meaning
# Supports both simple strings and EU authority URIs
# Based on the comprehensive vocabulary list with all 42 possible frequency values
FREQUENCY_MAP = {
    # Minute-based frequencies (EXACT minute intervals converted to days)
    "1MIN": 1/1440,     # Every minute = 1/1440 days (1 minute exactly)
    "5MIN": 5/1440,     # Every 5 minutes = 5/1440 days (5 minutes exactly)
    "10MIN": 10/1440,   # Every 10 minutes = 10/1440 days (10 minutes exactly)
    "15MIN": 15/1440,   # Every 15 minutes = 15/1440 days (15 minutes exactly)
    "30MIN": 30/1440,   # Every 30 minutes = 30/1440 days (30 minutes exactly)
    
    # Hour-based frequencies (EXACT hour intervals)
    "HOURLY": 1/24,     # Every hour = 1/24 days (1 hour exactly)
    "BIHOURLY": 2/24,   # Every 2 hours = 2/24 days (2 hours exactly)
    "TRIHOURLY": 3/24,  # Every 3 hours = 3/24 days (3 hours exactly)
    "12HRS": 12/24,     # Every 12 hours = 12/24 days (12 hours exactly)
    
    # Daily frequencies (EXACT day intervals)
    "DAILY": 1,         # Daily update = 1 day exactly
    "DAILY_2": 0.5,     # Twice daily = 0.5 days (12 hours exactly)
    
    # Weekly frequencies (EXACT weekly intervals)
    "WEEKLY": 7,        # Weekly update = 7 days exactly
    "WEEKLY_2": 7/2,    # Twice weekly = 7/2 days (3.5 days exactly)
    "WEEKLY_3": 7/3,    # Three times weekly = 7/3 days (2.33 days exactly)
    "WEEKLY_5": 7/5,    # Five times weekly = 7/5 days (1.4 days exactly)
    "BIWEEKLY": 14,     # Every two weeks = 14 days exactly
    
    # Monthly frequencies (EXACT monthly intervals)
    "MONTHLY": 30,      # Monthly update = 30 days exactly
    "MONTHLY_2": 15,    # Twice monthly = 15 days exactly (fortnightly)
    "MONTHLY_3": 10,    # Three times monthly = 10 days exactly
    "BIMONTHLY": 60,    # Every two months = 60 days exactly
    
    # Quarterly and annual frequencies (EXACT intervals)
    "QUARTERLY": 90,    # Quarterly = 90 days exactly (every 3 months)
    "ANNUAL": 365,      # Annual = 365 days exactly
    "ANNUAL_2": 182.5,  # Semi-annual = 365/2 days (182.5 days exactly)
    "ANNUAL_3": 365/3,  # Three times yearly = 365/3 days (121.67 days exactly)
    
    # Multi-year frequencies
    "BIENNIAL": 730,        # Every two years
    "TRIENNIAL": 1095,      # Every three years
    "QUADRENNIAL": 1460,    # Every four years
    "QUINQUENNIAL": 1825,   # Every five years
    "DECENNIAL": 3650,      # Every ten years
    "BIDECENNIAL": 7300,    # Every twenty years
    "TRIDECENNIAL": 10950,  # Every thirty years
    
    # Special frequencies - excluded from stale checking
    "AS_NEEDED": None,      # As needed - no fixed schedule
    "CONT": None,           # Continuous - always updating
    "IRREG": None,          # Irregular - no fixed pattern
    "NEVER": None,          # Never updated
    "NOT_PLANNED": None,    # Not planned for updates
    "OTHER": None,          # Other frequency not specified
    "UNKNOWN": None,        # Unknown frequency
    "UPDATE_CONT": None,    # Continuous update
    
    # Legacy mappings for backward compatibility
    "CONTINUOUS": None,     # Legacy mapping
    "IRREGULAR": None,      # Legacy mapping
    "REAL_TIME": 1,        # Legacy mapping
    "ONGOING": None,       # Legacy mapping
    "HALF_YEARLY": 182,    # Legacy mapping (same as ANNUAL_2)
    "EVERY_2_YEARS": 730,  # Legacy mapping (same as BIENNIAL)
    "EVERY_3_YEARS": 1095, # Legacy mapping (same as TRIENNIAL)
    "EVERY_5_YEARS": 1825, # Legacy mapping (same as QUINQUENNIAL)
    "EVERY_10_YEARS": 3650, # Legacy mapping (same as DECENNIAL)
    
    # EU Authority URI format - EXACT time intervals (matching simple format)
    "http://publications.europa.eu/resource/authority/frequency/1MIN": 1/1440,
    "http://publications.europa.eu/resource/authority/frequency/5MIN": 5/1440,
    "http://publications.europa.eu/resource/authority/frequency/10MIN": 10/1440,
    "http://publications.europa.eu/resource/authority/frequency/15MIN": 15/1440,
    "http://publications.europa.eu/resource/authority/frequency/30MIN": 30/1440,
    "http://publications.europa.eu/resource/authority/frequency/HOURLY": 1/24,
    "http://publications.europa.eu/resource/authority/frequency/BIHOURLY": 2/24,
    "http://publications.europa.eu/resource/authority/frequency/TRIHOURLY": 3/24,
    "http://publications.europa.eu/resource/authority/frequency/12HRS": 12/24,
    "http://publications.europa.eu/resource/authority/frequency/DAILY": 1,
    "http://publications.europa.eu/resource/authority/frequency/DAILY_2": 0.5,
    "http://publications.europa.eu/resource/authority/frequency/WEEKLY": 7,
    "http://publications.europa.eu/resource/authority/frequency/WEEKLY_2": 7/2,
    "http://publications.europa.eu/resource/authority/frequency/WEEKLY_3": 7/3,
    "http://publications.europa.eu/resource/authority/frequency/WEEKLY_5": 7/5,
    "http://publications.europa.eu/resource/authority/frequency/BIWEEKLY": 14,
    "http://publications.europa.eu/resource/authority/frequency/MONTHLY": 30,
    "http://publications.europa.eu/resource/authority/frequency/MONTHLY_2": 15,
    "http://publications.europa.eu/resource/authority/frequency/MONTHLY_3": 10,
    "http://publications.europa.eu/resource/authority/frequency/BIMONTHLY": 60,
    "http://publications.europa.eu/resource/authority/frequency/QUARTERLY": 90,
    "http://publications.europa.eu/resource/authority/frequency/ANNUAL": 365,
    "http://publications.europa.eu/resource/authority/frequency/ANNUAL_2": 182.5,
    "http://publications.europa.eu/resource/authority/frequency/ANNUAL_3": 365/3,
    "http://publications.europa.eu/resource/authority/frequency/BIENNIAL": 730,
    "http://publications.europa.eu/resource/authority/frequency/TRIENNIAL": 1095,
    "http://publications.europa.eu/resource/authority/frequency/QUADRENNIAL": 1460,
    "http://publications.europa.eu/resource/authority/frequency/QUINQUENNIAL": 1825,
    "http://publications.europa.eu/resource/authority/frequency/DECENNIAL": 3650,
    "http://publications.europa.eu/resource/authority/frequency/BIDECENNIAL": 7300,
    "http://publications.europa.eu/resource/authority/frequency/TRIDECENNIAL": 10950,
    "http://publications.europa.eu/resource/authority/frequency/AS_NEEDED": None,
    "http://publications.europa.eu/resource/authority/frequency/CONT": None,
    "http://publications.europa.eu/resource/authority/frequency/IRREG": None,
    "http://publications.europa.eu/resource/authority/frequency/NEVER": None,
    "http://publications.europa.eu/resource/authority/frequency/NOT_PLANNED": None,
    "http://publications.europa.eu/resource/authority/frequency/OTHER": None,
    "http://publications.europa.eu/resource/authority/frequency/UNKNOWN": None,
    "http://publications.europa.eu/resource/authority/frequency/UPDATE_CONT": None,
    
    # Legacy EU Authority URI mappings
    "http://publications.europa.eu/resource/authority/frequency/CONTINUOUS": None,
    "http://publications.europa.eu/resource/authority/frequency/IRREGULAR": None,
}


def normalize_frequency(frequency_value):
    """
    Normalize frequency value by handling empty strings and whitespace.
    Returns None for empty/invalid values.
    """
    if frequency_value is None:
        return None
    if not isinstance(frequency_value, six.string_types):
        frequency_value = six.text_type(frequency_value)
    if not frequency_value or not frequency_value.strip():
        return None
    return frequency_value.strip()


def get_frequency_display_name(frequency_value):
    """
    Get a user-friendly display name for frequency values.
    Converts frequency codes to translatable display names.
    """
    if not frequency_value:
        return toolkit._("Unknown")
    
    # Normalize input by trimming whitespace
    frequency_value = frequency_value.strip()
    
    if not frequency_value:
        return toolkit._("Unknown")
    
    # Handle EU authority URIs
    if frequency_value.startswith("http://publications.europa.eu/resource/authority/frequency/"):
        freq_code = frequency_value.split("/")[-1]
        frequency_value = freq_code
    
    # Map frequency codes to translatable display names
    frequency_translations = {
        # Minute-based frequencies
        "1MIN": toolkit._("Every minute"),
        "5MIN": toolkit._("Every 5 minutes"), 
        "10MIN": toolkit._("Every 10 minutes"),
        "15MIN": toolkit._("Every 15 minutes"),
        "30MIN": toolkit._("Every 30 minutes"),
        
        # Hour-based frequencies
        "HOURLY": toolkit._("Hourly"),
        "BIHOURLY": toolkit._("Every 2 hours"),
        "TRIHOURLY": toolkit._("Every 3 hours"),
        "12HRS": toolkit._("Every 12 hours"),
        
        # Daily frequencies
        "DAILY": toolkit._("Daily"),
        "DAILY_2": toolkit._("Twice daily"),
        
        # Weekly frequencies
        "WEEKLY": toolkit._("Weekly"),
        "WEEKLY_2": toolkit._("Twice weekly"),
        "WEEKLY_3": toolkit._("Three times weekly"),
        "WEEKLY_5": toolkit._("Five times weekly"),
        "BIWEEKLY": toolkit._("Every 2 weeks"),
        
        # Monthly frequencies
        "MONTHLY": toolkit._("Monthly"),
        "MONTHLY_2": toolkit._("Twice monthly"),
        "MONTHLY_3": toolkit._("Three times monthly"),
        "BIMONTHLY": toolkit._("Every 2 months"),
        
        # Quarterly and annual frequencies
        "QUARTERLY": toolkit._("Quarterly"),
        "ANNUAL": toolkit._("Annually"),
        "ANNUAL_2": toolkit._("Twice yearly"),
        "ANNUAL_3": toolkit._("Three times yearly"),
        
        # Multi-year frequencies
        "BIENNIAL": toolkit._("Every 2 years"),
        "TRIENNIAL": toolkit._("Every 3 years"),
        "QUADRENNIAL": toolkit._("Every 4 years"),
        "QUINQUENNIAL": toolkit._("Every 5 years"),
        "DECENNIAL": toolkit._("Every 10 years"),
        "BIDECENNIAL": toolkit._("Every 20 years"),
        "TRIDECENNIAL": toolkit._("Every 30 years"),
        
        # Special frequencies
        "AS_NEEDED": toolkit._("As needed"),
        "CONT": toolkit._("Continuous"),
        "IRREG": toolkit._("Irregular"),
        "NEVER": toolkit._("Never"),
        "NOT_PLANNED": toolkit._("Not planned"),
        "OTHER": toolkit._("Other"),
        "UNKNOWN": toolkit._("Unknown"),
        "UPDATE_CONT": toolkit._("Continuously updated"),
    }
    
    # Return translated name if available, otherwise format the raw value
    return frequency_translations.get(frequency_value, frequency_value.replace("_", " ").title())

STATUS_STALE = 'STALE'
STATUS_OK = 'OK'
STATUS_NA = 'Non-evaluable'


def _active_datasets_query():
    q = model.Session.query(model.Package) \
             .filter(model.Package.state == 'active')
    return lib.filter_datasets_only(q)


def _package_extra(pkg, key):
    extras = getattr(pkg, 'extras', None)
    if not extras:
        return None
    if hasattr(extras, 'get'):
        return extras.get(key)
    for extra in extras:
        if getattr(extra, 'key', None) == key:
            return getattr(extra, 'value', None)
    return None


def _metadata_modified_date(pkg):
    metadata_modified = getattr(pkg, 'metadata_modified', None)
    if isinstance(metadata_modified, datetime):
        return metadata_modified.date()
    if isinstance(metadata_modified, date):
        return metadata_modified
    return None


def _empty_counts():
    return {
        'total_packages': 0,
        'num_stale': 0,
        'num_ok': 0,
        'num_na': 0,
    }


def _accumulate_counts(counts, status_code):
    counts['total_packages'] += 1
    if status_code == STATUS_STALE:
        counts['num_stale'] += 1
    elif status_code == STATUS_OK:
        counts['num_ok'] += 1
    else:
        counts['num_na'] += 1


def _merge_counts(total_counts, counts):
    for key in ('total_packages', 'num_stale', 'num_ok', 'num_na'):
        total_counts[key] += counts.get(key, 0)


def _counts_with_percentage(counts):
    data = counts.copy()
    data['stale_percentage'] = lib.percent(
        counts['num_stale'],
        counts['total_packages']
    )
    return data


def _classification_for_package(pkg, today):
    raw_frequency = _package_extra(pkg, 'frequency')
    frequency = normalize_frequency(raw_frequency)
    threshold_days = FREQUENCY_MAP.get(frequency)
    frequency_display = toolkit._("M/Δ")
    last_modified_date = None
    days_since_update = None
    status_code = STATUS_NA

    if frequency in FREQUENCY_MAP:
        frequency_display = get_frequency_display_name(frequency)
        if threshold_days is not None:
            last_modified_date = _metadata_modified_date(pkg)
            if last_modified_date is not None:
                days_since_update = (today - last_modified_date).days
                if days_since_update > threshold_days:
                    status_code = STATUS_STALE
                else:
                    status_code = STATUS_OK

    return {
        'frequency': frequency,
        'frequency_display': frequency_display,
        'last_modified_date': last_modified_date,
        'days_since_update': days_since_update,
        'status_code': status_code,
        'status': toolkit._(status_code),
        'is_stale': status_code == STATUS_STALE,
        'is_evaluable': status_code in (STATUS_STALE, STATUS_OK),
    }


def _organization_title(org):
    return org.title or org.name


def _package_organization(pkg, organization_cache):
    owner_org = getattr(pkg, 'owner_org', None)
    if not owner_org:
        return {'name': '', 'title': ''}
    if owner_org not in organization_cache:
        try:
            org = model.Group.get(owner_org)
            organization_cache[owner_org] = {
                'name': org.name if org else owner_org,
                'title': (
                    getattr(org, 'display_name', None) or _organization_title(org)
                ) if org else owner_org,
            }
        except Exception:
            organization_cache[owner_org] = {
                'name': owner_org,
                'title': owner_org,
            }
    return organization_cache[owner_org]


def _dataset_row(pkg, classification, organization_cache):
    title = lib.resolve_dataset_title(pkg)
    notes = lib.dataset_notes(pkg) or ''
    last_modified_date = classification['last_modified_date']
    organization = _package_organization(pkg, organization_cache)

    return OrderedDict([
        ('name', pkg.name),
        ('title', title),
        ('organization', organization['title']),
        ('organization_name', organization['name']),
        ('frequency', classification['frequency_display']),
        ('frequency_raw', classification['frequency']),
        ('last_modified', str(last_modified_date) if last_modified_date else None),
        ('days_since_update', classification['days_since_update']),
        ('status', classification['status']),
        ('status_code', classification['status_code']),
        ('is_stale', classification['is_stale']),
        ('is_evaluable', classification['is_evaluable']),
        ('notes', notes),
    ])


def _counts_for_packages(packages, today):
    counts = _empty_counts()
    for pkg in packages:
        classification = _classification_for_package(pkg, today)
        _accumulate_counts(counts, classification['status_code'])
    return counts


def _report_data(table, counts, total_organizations=None):
    counts = _counts_with_percentage(counts)
    data = {
        'table': table,
        'num_packages': counts['total_packages'],
        'total_packages': counts['total_packages'],
        'num_stale': counts['num_stale'],
        'num_ok': counts['num_ok'],
        'num_na': counts['num_na'],
        'stale_percentage': counts['stale_percentage'],
        'total_datasets': counts['total_packages'],
    }
    if total_organizations is not None:
        data['total_organizations'] = total_organizations
    return data


def _index_report_data(table, counts):
    data = _report_data(table, counts, total_organizations=len(table))
    data['_requires_post_access_filter'] = True
    return data


def stale_datasets_index():
    '''Returns stale dataset counts grouped by organization.'''
    today = date.today()
    total_counts = _empty_counts()
    table = []

    orgs = model.Session.query(model.Group) \
        .filter(model.Group.type == 'organization') \
        .filter(model.Group.state == 'active') \
        .order_by(model.Group.title, model.Group.name)

    for org in orgs:
        counts = _counts_for_packages(
            _active_datasets_query().filter(model.Package.owner_org == org.id),
            today
        )
        if counts['total_packages'] == 0:
            continue

        _merge_counts(total_counts, counts)
        counts = _counts_with_percentage(counts)
        table.append(OrderedDict((
            ('organization_name', org.name),
            ('organization_title', _organization_title(org)),
            ('total_packages', counts['total_packages']),
            ('num_stale', counts['num_stale']),
            ('num_ok', counts['num_ok']),
            ('num_na', counts['num_na']),
            ('stale_percentage', counts['stale_percentage']),
        )))

    return _index_report_data(table, total_counts)


def stale_datasets_for_organization(organization):
    '''Returns dataset-level stale status rows for a specific organization.'''
    q = _active_datasets_query()
    if organization:
        q = lib.filter_by_organizations(q, organization, False)

    today = date.today()
    counts = _empty_counts()
    rows = []
    organization_cache = {}

    for pkg in q:
        classification = _classification_for_package(pkg, today)
        _accumulate_counts(counts, classification['status_code'])
        rows.append(_dataset_row(pkg, classification, organization_cache))

    return _report_data(rows, counts)


def stale_datasets_report(organization=None):
    '''
    Produces a report on datasets that are stale based on their frequency.

    The default view returns one aggregate row per organization. Passing an
    organization returns the dataset-level rows for that organization.
    '''
    if organization is None:
        return stale_datasets_index()
    return stale_datasets_for_organization(organization)


def stale_datasets_option_combinations():
    '''Generate option combinations for the report'''
    for organization in lib.all_organizations(include_none=True):
        yield {'organization': organization}


def _aggregate_rows(table):
    return bool(
        table and
        isinstance(table[0], dict) and
        'organization_name' in table[0] and
        'total_packages' in table[0] and
        'name' not in table[0]
    )


def _package_is_visible(pkg, context, package_access_cache):
    package_id = getattr(pkg, 'id', None) or getattr(pkg, 'name', None)
    if not package_id:
        return False

    cached_access = package_access_cache.get(package_id)
    if cached_access is not None:
        return cached_access

    try:
        import ckan.logic as logic
    except Exception:
        package_access_cache[package_id] = False
        return False

    try:
        if hasattr(toolkit, 'fresh_context'):
            action_context = toolkit.fresh_context(context or {})
        else:
            action_context = dict(context or {})
        logic.check_access('package_show', action_context, {'id': package_id})
    except toolkit.NotAuthorized:
        package_access_cache[package_id] = False
    except Exception:
        package_access_cache[package_id] = False
    else:
        package_access_cache[package_id] = True

    return package_access_cache[package_id]


def _visible_packages(packages, context, package_access_cache):
    for pkg in packages:
        if _package_is_visible(pkg, context, package_access_cache):
            yield pkg


def _access_filtered_stale_datasets_index(context):
    today = date.today()
    total_counts = _empty_counts()
    table = []
    package_access_cache = {}

    orgs = model.Session.query(model.Group) \
        .filter(model.Group.type == 'organization') \
        .filter(model.Group.state == 'active') \
        .order_by(model.Group.title, model.Group.name)

    for org in orgs:
        packages = _active_datasets_query() \
            .filter(model.Package.owner_org == org.id)
        counts = _counts_for_packages(
            _visible_packages(packages, context, package_access_cache),
            today
        )
        if counts['total_packages'] == 0:
            continue

        _merge_counts(total_counts, counts)
        counts = _counts_with_percentage(counts)
        table.append(OrderedDict((
            ('organization_name', org.name),
            ('organization_title', _organization_title(org)),
            ('total_packages', counts['total_packages']),
            ('num_stale', counts['num_stale']),
            ('num_ok', counts['num_ok']),
            ('num_na', counts['num_na']),
            ('stale_percentage', counts['stale_percentage']),
        )))

    return _report_data(table, total_counts, total_organizations=len(table))


def _status_code_from_row(row):
    if not isinstance(row, dict):
        return STATUS_NA

    status_code = row.get('status_code')
    if status_code in (STATUS_STALE, STATUS_OK, STATUS_NA):
        return status_code

    def _as_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    # Locale-agnostic fallback for legacy cached rows.
    frequency_raw = normalize_frequency(row.get('frequency_raw'))
    threshold_days = FREQUENCY_MAP.get(frequency_raw)
    days_since_update = _as_float(row.get('days_since_update'))
    if threshold_days is not None and days_since_update is not None:
        return STATUS_STALE if days_since_update > threshold_days else STATUS_OK

    if row.get('is_stale') is True:
        return STATUS_STALE
    if row.get('is_stale') is False and row.get('days_since_update') is not None:
        return STATUS_OK

    # Last-resort compatibility fallback.
    status = row.get('status')
    if isinstance(status, six.string_types):
        status = status.strip()
        if status.upper() == STATUS_STALE:
            return STATUS_STALE
        if status.upper() == STATUS_OK:
            return STATUS_OK
    return STATUS_NA


def stale_datasets_post_access_filter(data, context):
    table = data.get('table', [])

    if data.pop('_requires_post_access_filter', None) or _aggregate_rows(table):
        return _access_filtered_stale_datasets_index(context)

    counts = _empty_counts()
    for row in table:
        _accumulate_counts(counts, _status_code_from_row(row))

    counts = _counts_with_percentage(counts)
    data['num_packages'] = counts['total_packages']
    data['total_packages'] = counts['total_packages']
    data['num_stale'] = counts['num_stale']
    data['num_ok'] = counts['num_ok']
    data['num_na'] = counts['num_na']
    data['stale_percentage'] = counts['stale_percentage']
    data['total_datasets'] = counts['total_packages']
    return data


# Report configuration
stale_datasets_report_info = {
    'name': 'stale-datasets',
    'title': toolkit._('Stale Datasets'),
    'description': toolkit._('Datasets that have not been updated according to their frequency schedule'),
    'option_defaults': OrderedDict((
        ('organization', None),
    )),
    'option_combinations': stale_datasets_option_combinations,
    'generate': stale_datasets_report,
    'post_access_filter': stale_datasets_post_access_filter,
    'template': 'report/stale-datasets.html',
}
