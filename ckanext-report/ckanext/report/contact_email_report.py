# encoding: utf-8

import json

from ckan import model

try:
    from collections import OrderedDict  # from python 2.7
except ImportError:
    from sqlalchemy.util import OrderedDict

from ckanext.report import lib


DISPLAY_EMPTY = '(κενό)'
YES_LABEL = 'Ναι'
NO_LABEL = 'Όχι'
REPORT_NAME = 'contact-email-coverage'

SUMMARY_COLUMNS = (
    'Οργανισμός',
    'Σύνολο δεδομένων',
    'Έχει τουλάχιστον ένα email σε σημείο επικοινωνίας;',
    'Όλα τα emails σημείων επικοινωνίας',
)


def _clean_string(value):
    if value is None:
        return None
    if not isinstance(value, str):
        value = '{}'.format(value)
    value = value.strip()
    return value or None


def format_display_value(value):
    cleaned = _clean_string(value)
    return cleaned if cleaned is not None else DISPLAY_EMPTY


def _sort_value(value):
    cleaned = _clean_string(value)
    return cleaned.casefold() if cleaned else ''


def _parse_contacts(raw_contacts):
    if isinstance(raw_contacts, str):
        raw_contacts = raw_contacts.strip()
        if not raw_contacts:
            return []
        try:
            raw_contacts = json.loads(raw_contacts)
        except (TypeError, ValueError):
            return []

    if isinstance(raw_contacts, dict):
        raw_contacts = [raw_contacts]
    elif not isinstance(raw_contacts, list):
        return []

    contacts = []
    for contact in raw_contacts:
        if not isinstance(contact, dict):
            continue
        contacts.append({
            'name': _clean_string(contact.get('name')),
            'email': _clean_string(contact.get('email')),
            'uri': _clean_string(contact.get('uri')),
            'url': _clean_string(contact.get('url')),
        })
    return contacts


def _unique_non_empty(values):
    unique_values = []
    seen_values = set()
    for value in values:
        if not value or value in seen_values:
            continue
        unique_values.append(value)
        seen_values.add(value)
    return unique_values


def _iter_dataset_packages(organization=None):
    query = model.Session.query(model.Package)
    query = query.filter(model.Package.state == 'active')
    query = lib.filter_datasets_only(query)
    if organization:
        query = lib.filter_by_organizations(query, organization, False)
    return query.all()


def _get_organization(owner_org, organization_cache):
    if not owner_org:
        return None
    if owner_org not in organization_cache:
        organization_cache[owner_org] = model.Group.get(owner_org)
    return organization_cache[owner_org]


def _dataset_base_values(pkg, organization_cache):
    organization = _get_organization(pkg.owner_org, organization_cache)
    organization_title = None
    if organization:
        organization_title = (
            _clean_string(organization.title) or _clean_string(organization.name)
        )

    dataset_title = _clean_string(lib.resolve_dataset_title(pkg)) or _clean_string(pkg.name)
    dataset_name = _clean_string(pkg.name)

    base_values = OrderedDict((
        ('Οργανισμός', format_display_value(organization_title)),
        ('Σύνολο δεδομένων', format_display_value(dataset_title)),
    ))

    sort_key = (
        _sort_value(organization_title),
        _sort_value(dataset_title),
        _sort_value(dataset_name),
    )

    return base_values, dataset_name, sort_key


def sysadmin_only(user, options):
    return bool(user and getattr(user, 'sysadmin', False))


def organization_option_combinations():
    for organization in lib.all_organizations(include_none=True):
        yield {'organization': organization}


def generate_contact_email_coverage(organization=None):
    rows = []
    datasets_with_email = 0
    dataset_names = []
    organization_cache = {}

    for pkg in _iter_dataset_packages(organization=organization):
        base_values, dataset_name, sort_key = _dataset_base_values(pkg, organization_cache)
        contacts = _parse_contacts(pkg.extras.get('contact'))
        emails = _unique_non_empty([contact.get('email') for contact in contacts])
        if emails:
            datasets_with_email += 1

        row = OrderedDict()
        for column in SUMMARY_COLUMNS[:2]:
            row[column] = base_values[column]
        row[SUMMARY_COLUMNS[2]] = YES_LABEL if emails else NO_LABEL
        row[SUMMARY_COLUMNS[3]] = ', '.join(emails) if emails else DISPLAY_EMPTY
        rows.append((sort_key, row, dataset_name))

    rows.sort(key=lambda item: item[0])
    for _, _, dataset_name in rows:
        dataset_names.append(dataset_name)

    return {
        'table': [row for _, row, _ in rows],
        'datasets_with_email': datasets_with_email,
        'datasets_without_email': len(rows) - datasets_with_email,
        'total_datasets': len(rows),
        'dataset_names': dataset_names,
    }


contact_email_coverage_report_info = {
    'name': REPORT_NAME,
    'title': 'Κάλυψη emails σημείων επικοινωνίας',
    'description': 'Σύνοψη ανά σύνολο δεδομένων για την ύπαρξη email στα σημεία επικοινωνίας.',
    'option_defaults': OrderedDict((('organization', None),)),
    'option_combinations': organization_option_combinations,
    'generate': generate_contact_email_coverage,
    'authorize': sysadmin_only,
    'template': 'report/contact-email-coverage.html',
}
