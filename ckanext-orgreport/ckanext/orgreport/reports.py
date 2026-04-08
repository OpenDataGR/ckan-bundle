"""
Organization Email Report
=========================
Αναφορά ελέγχου email φορέων για κεντρικούς διαχειριστές.
Χρησιμοποιεί το ckanext-report IReport interface.
"""

import logging
from collections import OrderedDict

import ckan.plugins.toolkit as toolkit
import ckan.model as model

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Βοηθητικές συναρτήσεις
# ---------------------------------------------------------------------------

def _all_organizations_for_options(include_none=True):
    """
    Επιστρέφει λίστα organization names για τα option_combinations.
    Αν include_none=True, προσθέτει None (= όλοι οι φορείς).
    """
    context = {'model': model, 'ignore_auth': True}
    org_names = toolkit.get_action('organization_list')(
        context, {'all_fields': False}
    )
    if include_none:
        org_names = [None] + org_names
    return org_names


# ---------------------------------------------------------------------------
# Report generate function
# ---------------------------------------------------------------------------

def org_email_report(organization=None):
    """
    Κύρια συνάρτηση αναφοράς. Επιστρέφει dict σύμφωνα με τη δομή
    που περιμένει το ckanext-report:
        {
            'table': [...],
            'total': N,
            'with_email': N,
            'without_email': N,
        }
    """
    context = {'model': model, 'ignore_auth': True}

    if organization:
        org_names = [organization]
    else:
        org_names = toolkit.get_action('organization_list')(
            context, {'all_fields': False}
        )

    table = []
    for org_name in org_names:
        try:
            org = toolkit.get_action('organization_show')(
                context, {'id': org_name}
            )
        except toolkit.ObjectNotFound:
            log.warning('Organization not found: %s', org_name)
            continue
        except Exception as e:
            log.error('Error fetching org %s: %s', org_name, e)
            continue

        email = (org.get('email') or '').strip()
        table.append({
            'name': org.get('name', ''),
            'title': org.get('display_name') or org.get('title', org_name),
            'email': email,
            'has_email': bool(email),
            'package_count': org.get('package_count', 0),
            'state': org.get('state', ''),
            'created': org.get('created', ''),
        })

    # Ταξινόμηση: πρώτα χωρίς email, μετά αλφαβητικά
    table.sort(key=lambda o: (o['has_email'], o['title'].lower()))

    total = len(table)
    with_email = sum(1 for row in table if row['has_email'])
    without_email = total - with_email

    return {
        'table': table,
        'total': total,
        'with_email': with_email,
        'without_email': without_email,
    }


# ---------------------------------------------------------------------------
# Option combinations (για pre-generation cache)
# ---------------------------------------------------------------------------

def org_email_report_option_combinations():
    """
    Επιστρέφει τους συνδυασμούς options για τους οποίους
    θα γίνει pre-generate η αναφορά.
    """
    for organization in _all_organizations_for_options(include_none=True):
        yield {'organization': organization}


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

def org_email_report_authorize(user, options):
    """
    Μόνο sysadmin μπορεί να δει αυτή την αναφορά.
    """
    if user and user.sysadmin:
        return True
    return False


# ---------------------------------------------------------------------------
# Report info dict (εγγραφή στο ckanext-report)
# ---------------------------------------------------------------------------

org_email_report_info = {
    'name': 'org-email-status',
    'title': u'Κατάσταση Email Φορέων',
    'description': u'Αναφορά ελέγχου αν οι φορείς έχουν συμπληρωμένο email '
                   u'στο προφίλ τους. Χρήσιμο για τους κεντρικούς διαχειριστές.',
    'option_defaults': OrderedDict([
        ('organization', None),
    ]),
    'option_combinations': org_email_report_option_combinations,
    'generate': org_email_report,
    'template': 'report/org_email_status.html',
    'authorize': org_email_report_authorize,
}