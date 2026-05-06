import logging
import json
import re
import time
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from html import unescape as html_unescape
from datetime import datetime, timedelta, date as date_cls
import ckan.plugins.toolkit as toolkit
from ckan import model
from ckan.common import g, asbool
from ckan.lib import helpers as core_helpers
from ckan.lib.helpers import lang
from ckan.model.system_info import get_system_info
from ckan.plugins.toolkit import render_snippet, _  # Import για το σύστημα μετάφρασης
from flask_login import current_user as _cu
from typing import (cast, Union)
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import aliased, joinedload

from ckanext.data_gov_gr import organization_stats
from ckanext.data_gov_gr.stats import DataGovStats
try:
    from ckanext.showcase.model import ShowcasePackageAssociation
except Exception:
    ShowcasePackageAssociation = None


# Background refresh μηχανισμός (ώστε η αρχική να μην μπλοκάρει από Matomo calls).
_HOME_REUSE_STATS_EXECUTOR = ThreadPoolExecutor(max_workers=1)
_HOME_REUSE_STATS_IN_FLIGHT: set[str] = set()
_HOME_REUSE_STATS_IN_FLIGHT_LOCK = threading.Lock()


_MONTH_ABBREV_EN = {
    1: 'JAN',
    2: 'FEB',
    3: 'MAR',
    4: 'APR',
    5: 'MAY',
    6: 'JUN',
    7: 'JUL',
    8: 'AUG',
    9: 'SEP',
    10: 'OCT',
    11: 'NOV',
    12: 'DEC',
}

_MONTH_ABBREV_EL = {
    1: 'ΙΑΝ',
    2: 'ΦΕΒ',
    3: 'ΜΑΡ',
    4: 'ΑΠΡ',
    5: 'ΜΑΙ',
    6: 'ΙΟΥΝ',
    7: 'ΙΟΥΛ',
    8: 'ΑΥΓ',
    9: 'ΣΕΠ',
    10: 'ΟΚΤ',
    11: 'ΝΟΕ',
    12: 'ΔΕΚ',
}


def _month_abbrev(month: int, locale: str) -> str:
    locale_clean = (locale or '').lower()
    mapping = _MONTH_ABBREV_EL if locale_clean.startswith('el') else _MONTH_ABBREV_EN
    return mapping.get(int(month), str(month))

def _month_start(d: date_cls) -> date_cls:
    return date_cls(d.year, d.month, 1)


def _add_months(d: date_cls, delta: int) -> date_cls:
    """
    Προσθέτει/αφαιρεί μήνες (πάντα επιστρέφει 1η του μήνα).
    """
    y, m = d.year, d.month
    m += int(delta)
    while m > 12:
        y += 1
        m -= 12
    while m < 1:
        y -= 1
        m += 12
    return date_cls(y, m, 1)


def _get_home_stats_catalog():
    """
    Σταθερός κατάλογος με τα διαθέσιμα στατιστικά που μπορούν να
    εμφανιστούν ως πλακίδια στην αρχική σελίδα.

    Κάθε στοιχείο επιστρέφεται ως dict με:
      - id: μοναδικό κλειδί ρύθμισης
      - route: Flask route name για το url_for
      - icon: CSS κλάση Font Awesome
      - title: μετάφραση τίτλου
      - description: σύντομη περιγραφή
    """
    return [
        {
            'id': 'datasets_by_theme',
            'route': 'stats.datasets_by_theme',
            'icon': 'fa fa-chart-pie',
            'title': _('Datasets Per Theme'),
            'description': _('Number of Datasets per Thematic Category.')
        },
        {
            'id': 'datasets_by_publisher_type',
            'route': 'dataset_type.stats_datasets_by_publisher_type',
            'icon': 'fa fa-sitemap',
            'title': _('Datasets Per Publisher Type'),
            'description': _('Number of Datasets per Publisher Type.')
        },
        {
            'id': 'datasets_by_organization',
            'route': 'dataset_type.stats_datasets_per_organization',
            'icon': 'fa fa-building',
            'title': _('Datasets Per Organization'),
            'description': _('Number of Datasets per Organization.')
        },
        {
            'id': 'datasets_vs_services',
            'route': 'dataset_type.stats_datasets_vs_services',
            'icon': 'fa fa-balance-scale',
            'title': _('Datasets vs Data Services'),
            'description': _('Comparison between Datasets and Data Services.')
        },
        {
            'id': 'datasets_by_hvd_category',
            'route': 'dataset_type.stats_datasets_by_hvd_category',
            'icon': 'fa fa-star',
            'title': _('Datasets Per High-Value Category'),
            'description': _('Number of HVD Datasets per Category.')
        },
        {
            'id': 'organizations_by_publisher_type',
            'route': 'stats.organizations_by_publisher_type',
            'icon': 'fa fa-building',
            'title': _('Organizations Per Publisher Type'),
            'description': _('Number of Organizations per Publisher Type.')
        },
        {
            'id': 'total_datasets',
            'route': 'dataset_type.stats_total_datasets',
            'icon': 'fa fa-chart-line',
            'title': _('Total Number of Packages'),
            'description': _('Trend of the Total Number of Packages over Time.')
        },
        {
            'id': 'dataset_revisions',
            'route': 'dataset_type.stats_dataset_revisions',
            'icon': 'fa fa-chart-area',
            'title': _('Package Revisions per Week'),
            'description': _('Package Updates and New Publications per Week.')
        },
        {
            'id': 'most_edited',
            'route': 'dataset_type.stats_most_edited',
            'icon': 'fa fa-edit',
            'title': _('Most Edited Packages'),
            'description': _('Packages with the Most Changes.')
        },
        {
            'id': 'largest_groups',
            'route': 'dataset_type.stats_largest_groups',
            'icon': 'fa fa-users',
            'title': _('Largest Groups'),
            'description': _('Groups with the Most Connected Packages.')
        },
        {
            'id': 'top_tags',
            'route': 'dataset_type.stats_top_tags',
            'icon': 'fa fa-tags',
            'title': _('Top Tags'),
            'description': _('Most Popular Dataset Tags.')
        },
        {
            'id': 'top_creators',
            'route': 'dataset_type.stats_top_creators',
            'icon': 'fa fa-user',
            'title': _('Users Creating Most Datasets'),
            'description': _('Users who Have Created the Most Datasets.'),
            'requires_sysadmin': True,
        },
        {
            'id': 'powerbi',
            'route': 'dataset_type.stats_powerbi',
            'icon': 'fa fa-chart-bar',
            'title': _('Power BI Reports'),
            'description': _('Advanced Reports and Dashboards from Power BI.')
        },
    ]


def _current_user_is_sysadmin() -> bool:
    current_user = cast(Union["Model.User", "Model.AnonymousUser"], _cu)
    if not getattr(current_user, 'is_authenticated', False):
        return False

    context = {
        'user': getattr(current_user, 'name', None),
        'auth_user_obj': current_user,
    }
    try:
        toolkit.check_access('sysadmin', context, {})
    except toolkit.NotAuthorized:
        return False
    return True


log = logging.getLogger(__name__)

HOME_DATASET_RESOURCES_SNAPSHOT_KEY = (
    'ckanext.data_gov_gr.home.dataset_resources_snapshot'
)

_VOCAB_CACHE_VERSION_KEY = 'ckanext:vocabulary_admin:cache_version'
_VOCAB_CACHE_FALLBACK_TTL_SECONDS = 30
_VOCAB_TAGS_CACHE = {}
_VOCAB_TAGS_CACHE_VERSION = None
_VOCAB_TAGS_CACHE_LOCK = threading.Lock()
_VOCAB_TAGS_FALLBACK_VERSION = 1
_VOCAB_TAGS_FALLBACK_EXPIRES_AT = 0.0


def _decode_cache_version(value, default=1):
    """Μετατρέπει Redis τιμή version σε ακέραιο με ασφαλές fallback."""
    if value is None:
        return default
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'ignore')
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_vocab_cache_fallback_version():
    """Τοπικό fallback version όταν δεν είναι διαθέσιμο το Redis."""
    global _VOCAB_TAGS_FALLBACK_VERSION, _VOCAB_TAGS_FALLBACK_EXPIRES_AT
    now = time.time()
    with _VOCAB_TAGS_CACHE_LOCK:
        if now >= _VOCAB_TAGS_FALLBACK_EXPIRES_AT:
            _VOCAB_TAGS_FALLBACK_VERSION += 1
            _VOCAB_TAGS_FALLBACK_EXPIRES_AT = now + _VOCAB_CACHE_FALLBACK_TTL_SECONDS
        return _VOCAB_TAGS_FALLBACK_VERSION


def _get_vocab_cache_version():
    """Παίρνει το shared cache version από Redis ή fallback τοπικά."""
    try:
        from ckan.lib.redis import connect_to_redis  # type: ignore
        redis_conn = connect_to_redis()
        current = redis_conn.get(_VOCAB_CACHE_VERSION_KEY)
        if current is None:
            redis_conn.set(_VOCAB_CACHE_VERSION_KEY, 1, nx=True)
            current = redis_conn.get(_VOCAB_CACHE_VERSION_KEY)
        return _decode_cache_version(current, default=1)
    except Exception:
        return _get_vocab_cache_fallback_version()


# ---------------------------------------------------------------------------------------

def map_search_basemap_key() -> str:
    return toolkit.config.get('ckanext.data_gov_gr.map_search.basemap', 'carto_light_all').strip()

# ---------------------------------------------------------------------------------------

def decisions_menu_enabled() -> bool:
    return asbool(toolkit.config.get("ckanext.data_gov_gr.menu.decisions.enabled", False))

# ---------------------------------------------------------------------------------------

def google_analytics_snippet():
    return render_snippet("google_analytics/snippets/google_analytics.html")

# ---------------------------------------------------------------------------------------

def _get_vocabulary_tags(vocabulary_id_or_name):
    """
    Ανακτά τα tags ενός λεξιλογίου από τη βάση δεδομένων.
    """
    global _VOCAB_TAGS_CACHE_VERSION
    cache_version = _get_vocab_cache_version()
    with _VOCAB_TAGS_CACHE_LOCK:
        if _VOCAB_TAGS_CACHE_VERSION != cache_version:
            _VOCAB_TAGS_CACHE.clear()
            _VOCAB_TAGS_CACHE_VERSION = cache_version

        cached_tags = _VOCAB_TAGS_CACHE.get(vocabulary_id_or_name)
        if cached_tags is not None:
            return cached_tags

    try:
        vocabulary_data = toolkit.get_action('vocabularyadmin_vocabulary_show')(
            {}, {'id': vocabulary_id_or_name}
        )
        tags = vocabulary_data.get('tags', [])

        with _VOCAB_TAGS_CACHE_LOCK:
            _VOCAB_TAGS_CACHE[vocabulary_id_or_name] = tags

        return tags
    except toolkit.ObjectNotFound:
        log.warning(f'Vocabulary not found: "{vocabulary_id_or_name}"')
        return []
    except Exception as e:
        log.exception(f'Error retrieving vocabulary "{vocabulary_id_or_name}": {e}')
        return []

def _get_label_by_language(tag):
    current_lang = lang()

    if current_lang == 'el':
        return tag.get('label_el') or tag.get('label_en') or tag.get('display_name')
    elif current_lang == 'en':
        return tag.get('label_en') or tag.get('display_name')

    return tag.get('display_name')

def vocabulary_facet_item_label(name):
    """
    Μέθοδος για αλλαγή του label ενός facet item.
    Ανακτά τα δεδομένα από τη βάση αντί για hardcoded τιμές.
    """
    lang_system = lang()
    display_name = name['display_name']

    # Μεταφράζουμε τις boolean τιμές που το CKAN εμφανίζει ως 'Yes'/'No'
    # Οι πραγματικές τιμές στο Solr είναι 'true' και 'false'.
    # Ο έλεγχος γίνεται case-insensitive για ασφάλεια.
    if str(display_name).lower() == 'true' or str(display_name).lower() == 'yes':
        return _('Yes') if lang_system == 'en' else _('Ναι')

    if str(display_name).lower() == 'false' or str(display_name).lower() == 'no':
        return _('No') if lang_system == 'en' else _('Όχι')

    if display_name.startswith('http://purl.org/adms/publishertype/'):
        code = display_name.split('/')[-1]
        tags = _get_vocabulary_tags('Publisher type')
        for tag in tags:
            if tag.get('value_uri') == display_name or tag.get('name') == code:
                return _get_label_by_language(tag) or code
        return code

    # Έλεγχος για το λεξιλόγιο Access right
    if display_name.startswith('http://publications.europa.eu/resource/authority/access-right/'):
        access_code = display_name.split('/')[-1]
        tags = _get_vocabulary_tags('Access right')

        for tag in tags:
            if tag.get('value_uri') == display_name or tag.get('name') == access_code:
                return _get_label_by_language(tag) or access_code

        return access_code

    # Έλεγχος για το λεξιλόγιο Planned availability
    if display_name.startswith('http://publications.europa.eu/resource/authority/planned-availability/'):
        availability_code = display_name.split('/')[-1]
        tags = _get_vocabulary_tags('Planned availability')

        for tag in tags:
            if tag.get('value_uri') == display_name or tag.get('name') == availability_code:
                return _get_label_by_language(tag) or availability_code

        return availability_code

    # Έλεγχος για το λεξιλόγιο Frequency
    if display_name.startswith('http://publications.europa.eu/resource/authority/frequency/'):
        frequency_code = display_name.split('/')[-1]
        tags = _get_vocabulary_tags('Frequency')

        for tag in tags:
            if tag.get('value_uri') == display_name or tag.get('name') == frequency_code:
                return _get_label_by_language(tag) or frequency_code

        return frequency_code

        # Έλεγχος για το λεξιλόγιο Licence
    if display_name.startswith('http://publications.europa.eu/resource/authority/licence/'):
            licence_code = display_name.split('/')[-1]
            tags = _get_vocabulary_tags('Licence')

            import logging
            log = logging.getLogger(__name__)
            log.debug(f"LICENSE_DEBUG: Attempting to translate URL -> {display_name}")

            for tag in tags:
                log.debug(f"LICENSE_DEBUG: Checking against tag data -> {tag}")

                if tag.get('value_uri') == display_name or tag.get('name') == licence_code:
                    return tag.get('display_name', licence_code)

            return licence_code

    # Έλεγχος για facet dataset_type
    if display_name.startswith('data-service'):
        return 'API'
    if display_name.startswith('dataset'):
        return 'Σύνολο Δεδομένων' if lang_system == 'el' else 'Dataset'

    # Αν δεν ταιριάζει με κανένα από τα παραπάνω, επιστρέφουμε το αρχικό display_name
    return display_name


def vocabulary_facet_title(title):
    """
    Μέθοδος για αλλαγή του τίτλου facet.
    Ανακτά τα δεδομένα από τη βάση αντί για hardcoded τιμές.
    """
    lang_system = lang()

    # Αντιστοίχιση των facet τίτλων με τα vocabulary IDs
    vocabulary_mapping = {
        'access_rights': 'Access right',
        'theme': 'Data theme',
        'dcat_type': 'Dataset type',
        'hvd_category': 'High-value dataset categories',
        'frequency': 'Frequency',
        'availability': 'Planned availability',
        'license': 'Licence',
        'publishertype': {'el': 'Τύπος Οργανισμού', 'en': 'Organization Type'},
        'is_hvd': {'el': 'Σύνολο Δεδομένων Υψηλής Αξίας', 'en': 'High-Value Dataset'},
        'is_nsip': {'el': 'Σύνολο προστατευόμενων Δεδομένων', 'en': 'Protected Dataset'},

    }

    # Αν ο τίτλος αντιστοιχεί σε ένα λεξιλόγιο, προσπαθούμε να πάρουμε την περιγραφή του
    if title in vocabulary_mapping:
        vocabulary_id = vocabulary_mapping[title]

        # Προσπαθούμε να πάρουμε την περιγραφή του λεξιλογίου
        # Αν αποτύχει, χρησιμοποιούμε τις προκαθορισμένες μεταφράσεις
        try:
            # Εδώ θα μπορούσαμε να χρησιμοποιήσουμε την περιγραφή του λεξιλογίου
            # αλλά προς το παρόν χρησιμοποιούμε τις προκαθορισμένες μεταφράσεις
            # για συμβατότητα με την υπάρχουσα υλοποίηση
            if title == 'access_rights':
                return 'Δικαιώματα πρόσβασης' if lang_system == 'el' else 'Access rights'
            elif title == 'theme':
                return 'Κατηγορίες' if lang_system == 'el' else 'Categories'
            elif title == 'dcat_type':
                return 'Τύποι' if lang_system == 'el' else 'Types'
            elif title == 'hvd_category':
                return 'Κατηγορίες HVD' if lang_system == 'el' else 'HVD Categories'
            elif title == 'frequency':
                return 'Συχνότητα' if lang_system == 'el' else 'Frequency'
            elif title == 'availability':
                return 'Διαθεσιμότητα' if lang_system == 'el' else 'Availability'
            elif title == 'license':
                return 'Άδειες' if lang_system == 'el' else 'Licenses'
            elif title == 'publishertype':
                return 'Τύπος Οργανισμού' if lang_system == 'el' else 'Organization Type'
            elif title == 'is_hvd':
                return 'Σύνολο Δεδομένων Υψηλής Αξίας' if lang_system == 'el' else 'High-Value Dataset'
            elif title == 'is_nsip':
                return 'Σύνολο προστατευόμενων Δεδομένων' if lang_system == 'el' else 'Protected Dataset'
        except Exception as e:
            log.exception(f'Error retrieving vocabulary description for "{vocabulary_id}": {e}')

    if title == 'dataset_type':
        return 'Υπηρεσία/Σύνολο Δεδομένων' if lang_system == 'el' else 'Service/Dataset'
    if title == 'tags':
        return 'Λέξεις-κλειδιά' if lang_system == 'el' else 'Keywords'
    if title == 'organization':
        return 'Οργανισμός' if lang_system == 'el' else 'Organization'
    if title == 'res_format':
        return 'Μορφότυποι' if lang_system == 'el' else 'Format'
    if title == 'qa_mqa_rating':
        return 'Ποιότητα μεταδεδομένων' if lang_system == 'el' else 'Metadata quality'
    if title == 'qa_openness_score':
        return 'Βαθμολογία Ανοιχτότητας' if lang_system == 'el' else 'Openness score'

    return title


def get_vocabulary_id_for_field(field_name):
    """
    Επιστρέφει το αναγνωριστικό του λεξιλογίου για ένα συγκεκριμένο πεδίο.
    Χρησιμοποιεί ένα mapping που θα μπορούσε να ανακτηθεί από τη βάση δεδομένων.
    """
    # Αντιστοίχιση των πεδίων με τα vocabulary IDs
    # Αυτό θα μπορούσε να ανακτηθεί από τη βάση δεδομένων σε μελλοντική έκδοση
    vocabulary_mapping = {
        'theme': 'Data theme',
        'dcat_type': 'Dataset type',
        'hvd_category': 'High-value dataset categories',
        'access_rights': 'Access right',
        'frequency': 'Frequency',
        'availability': 'Planned availability',
        'license': 'Licence',
        'publishertype': 'Publisher type'
    }

    # Προσπαθούμε να βρούμε το vocabulary ID για το συγκεκριμένο πεδίο
    vocabulary_id = vocabulary_mapping.get(field_name)

    if vocabulary_id:
        # Επαληθεύουμε ότι το vocabulary υπάρχει στη βάση δεδομένων
        try:
            toolkit.get_action('vocabularyadmin_vocabulary_show')(
                {}, {'id': vocabulary_id}
            )
            # Αν φτάσουμε εδώ, το vocabulary υπάρχει
            return vocabulary_id
        except toolkit.ObjectNotFound:
            log.warning(f'Vocabulary not found: "{vocabulary_id}" for field "{field_name}"')
            return None
        except Exception as e:
            log.exception(f'Error retrieving vocabulary "{vocabulary_id}" for field "{field_name}": {e}')
            # Επιστρέφουμε το vocabulary_id ακόμα και αν υπάρχει σφάλμα
            # για να διατηρήσουμε τη συμβατότητα με την υπάρχουσα υλοποίηση
            return vocabulary_id

    return None


def build_mqa_nav_icon(pkg_id, dataset_type='dataset'):
    """
    Build the MQA tab navigation icon for the dataset view.

    Args:
        pkg_id: The ID of the dataset
        dataset_type: The type of the dataset (default: 'dataset')

    Returns:
        HTML for the MQA tab navigation icon
    """
    from ckan.lib.helpers import build_nav_icon
    return build_nav_icon(dataset_type + '_type.mqa', _('Metadata Quality'), id=pkg_id, package_type=dataset_type, icon='check-square')

def fluent_language_is_required(field, lang):
    """
    Return True if the given language is required for the field.
    This typically checks field['required_languages'] or a similar schema setting.
    """
    if not isinstance(field, dict):
        log.warning(f"Expected field to be dict, got {type(field)}: {field}")
        return False
    required_languages = field.get('required_languages', [])
    return lang in required_languages

def get_organizations_stats():
    """Returns statistics about organizations and their publisher types"""
    try:
        organizations = toolkit.get_action('organization_list')({}, {
            'all_fields': True,
            'include_extras': True
        })

        total_orgs = len(organizations)
        orgs_with_type = sum(1 for org in organizations
                             if org.get('publishertype'))

        return {
            'total': total_orgs,
            'with_type': orgs_with_type,
            'without_type': total_orgs - orgs_with_type,
            'type_percentage': round((orgs_with_type / total_orgs * 100) if total_orgs > 0 else 0, 1)
        }
    except Exception as e:
        log.error(f'Error getting organizations statistics: {str(e)}')
        return {
            'total': 0,
            'with_type': 0,
            'without_type': 0,
            'type_percentage': 0
        }

def get_access_rights_type():
    """
    Επιστρέφει το access_rights_type από το request αν υπάρχει.
    """
    from ckan.common import request
    return request.params.get('access_rights_type', '')


def get_dataset_legislation_default():
    """
    Επιστρέφει την προεπιλεγμένη τιμή για το πεδίο Εφαρμοστέα Νομοθεσία
    κατά τη δημιουργία συνόλου δεδομένων, με βάση το access_rights_type.
    """
    access_type = get_access_rights_type()

    if access_type == 'open':
        # Προεπιλεγμένη νομοθεσία για ανοιχτά δεδομένα
        return get_config_value('ckanext.data_gov_gr.dataset.legislation.open', '')
    if access_type == 'protected':
        # Προεπιλεγμένη νομοθεσία για προστατευόμενα δεδομένα
        return get_config_value('ckanext.data_gov_gr.dataset.legislation.protected', 'DGA')

    return ''


def _normalize_config_string(value, default=""):
    """
    Κανονικοποιεί τιμές config (CKAN) που μπορεί να είναι string ή list, σε ασφαλές string.

    Σε ορισμένες περιπτώσεις, τιμές από το /ckan-admin/config μπορεί να
    αποθηκευτούν ως λίστες (π.χ. συνδυασμοί hidden+checkbox). Σε αυτή την
    περίπτωση, χρησιμοποιούμε την τελευταία τιμή.
    """
    if value is None:
        return default
    if isinstance(value, list):
        if not value:
            return default
        value = value[-1]
    try:
        value = str(value)
    except Exception:
        return default
    value = value.strip()
    return value if value else default


def get_resource_license_default(package_id=None):
    """
    Επιστρέφει την προεπιλεγμένη τιμή για το πεδίο 'license' σε νέους πόρους.

    - Από /ckan-admin/config: ckanext.data_gov_gr.resource.license.default
    - Προεπιλογή (fallback): CC BY 4.0

    Αν δοθεί package_id, προσπαθεί να εφαρμόσει το default μόνο για datasets
    με access_rights = .../PUBLIC (δηλ. ανοικτά δεδομένα).
    """
    configured = _normalize_config_string(
        toolkit.config.get('ckanext.data_gov_gr.resource.license.default'),
        default='http://publications.europa.eu/resource/authority/licence/CC_BY_4_0',
    )

    # Δυνατότητα απενεργοποίησης του default: αν το key υπάρχει αλλά είναι κενό.
    if toolkit.config.get('ckanext.data_gov_gr.resource.license.default') in ("", [], None):
        if 'ckanext.data_gov_gr.resource.license.default' in toolkit.config:
            return ''

    if not package_id:
        return configured

    try:
        pkg = toolkit.get_action('package_show')(
            {'ignore_auth': True},
            {'id': package_id},
        )
    except Exception:
        # Αν δεν μπορούμε να διαβάσουμε το dataset, επιστρέφουμε το configured default.
        return configured

    access_rights_value = pkg.get('access_rights') or ''
    if isinstance(access_rights_value, str) and access_rights_value.endswith('/PUBLIC'):
        return configured

    return ''


def get_dataset_spatial_coverage_default():
    """
    Επιστρέφει προεπιλεγμένη τιμή για το πεδίο `spatial_coverage` σε νέα datasets.

    Είναι repeating field, οπότε επιστρέφει λίστα από dicts με κλειδιά:
      - uri, text, geom, bbox, centroid

    Κλειδί ρύθμισης (admin) στο /ckan-admin/config:
      - ckanext.data_gov_gr.dataset.spatial_coverage.default
        (τιμές: ''=καμία, 'greece'=Ελλάδα)

    Συμβατότητα προς τα πίσω (παλιό/advanced σχήμα):
      - ckanext.data_gov_gr.dataset.spatial_coverage.default.geonames_id
      - ckanext.data_gov_gr.dataset.spatial_coverage.default.text
      - ckanext.data_gov_gr.dataset.spatial_coverage.default.lng
      - ckanext.data_gov_gr.dataset.spatial_coverage.default.lat

    Προεπιλογή (fallback): Ελλάδα (GeoNames 390903) με centroid/geom στο (22, 39).
    """
    selection_key = 'ckanext.data_gov_gr.dataset.spatial_coverage.default'
    selection_raw = toolkit.config.get(selection_key)
    selection = _normalize_config_string(selection_raw, default='')

    # Αν το key υπάρχει αλλά είναι κενό -> απενεργοποίηση default.
    if selection_raw in ("", [], None) and selection_key in toolkit.config:
        return []

    # Νέος (απλός) τρόπος ρύθμισης
    if selection:
        if selection.lower() in ('greece', 'ellada', 'ελλάδα', 'gr', 'greece (ellada)', 'greece (greece)'):
            geonames_id = '390903'
            label = 'Greece'
            lng, lat = 22.0, 39.0
        else:
            # Δεχόμαστε GeoNames ID ή URI ως εναλλακτική τιμή (best-effort)
            geonames_id = selection.strip().rstrip('/').split('/')[-1]
            label = 'Greece' if geonames_id == '390903' else ''
            lng, lat = (22.0, 39.0) if geonames_id == '390903' else (None, None)
    else:
        # Backward-compatible (advanced) τρόπος ρύθμισης
        geonames_id = _normalize_config_string(
            toolkit.config.get('ckanext.data_gov_gr.dataset.spatial_coverage.default.geonames_id'),
            default='390903',
        )

        # Δυνατότητα απενεργοποίησης του default: αν το key υπάρχει αλλά είναι κενό.
        if toolkit.config.get('ckanext.data_gov_gr.dataset.spatial_coverage.default.geonames_id') in ("", [], None):
            if 'ckanext.data_gov_gr.dataset.spatial_coverage.default.geonames_id' in toolkit.config:
                return []

        label = _normalize_config_string(
            toolkit.config.get('ckanext.data_gov_gr.dataset.spatial_coverage.default.text'),
            default='Greece',
        )

        lng_raw = _normalize_config_string(
            toolkit.config.get('ckanext.data_gov_gr.dataset.spatial_coverage.default.lng'),
            default='22',
        )
        lat_raw = _normalize_config_string(
            toolkit.config.get('ckanext.data_gov_gr.dataset.spatial_coverage.default.lat'),
            default='39',
        )

        try:
            lng = float(lng_raw)
        except Exception:
            lng = 22.0
        try:
            lat = float(lat_raw)
        except Exception:
            lat = 39.0

    if lng is None or lat is None:
        geom = ''
    else:
        point = {"type": "Point", "coordinates": [lng, lat]}
        try:
            geom = json.dumps(point, ensure_ascii=False)
        except Exception:
            geom = '{"type":"Point","coordinates":[22,39]}'

    uri = f'http://sws.geonames.org/{geonames_id}/'

    return [{
        'uri': uri,
        'text': label,
        'geom': geom,
        'bbox': '',
        'centroid': geom,
    }]


def get_dataset_temporal_coverage_default():
    """
    Επιστρέφει προεπιλεγμένη τιμή για το πεδίο `temporal_coverage` σε νέα datasets.

    Είναι repeating field, οπότε επιστρέφει λίστα από dicts με κλειδιά:
      - start, end

    Προεπιλογή (fallback): 1900-01-01 έως 2099-12-31.
    """
    return [{
        'start': '1900-01-01',
        'end': '2099-12-31',
    }]


def data_gov_gr_get_organizations():
    """
    Επιστρέφει λίστα οργανισμών για dropdown (id, name, title).
    """
    try:
        orgs = toolkit.get_action('organization_list')(
            {'ignore_auth': True},
            {'all_fields': True, 'include_extras': False}
        )
        # ταξινόμηση αλφαβητικά με βάση το title ή name
        orgs_sorted = sorted(
            orgs,
            key=lambda o: (o.get('title') or o.get('name') or '').lower()
        )
        return orgs_sorted
    except Exception as e:
        log.error(f'Error loading organizations for contact form: {e}')
        return []

def get_config_as_bool(key, default=False):
    """
    Get configuration value as boolean.

    Args:
        key (str): Configuration key
        default (bool): Default value if key not found

    Returns:
        bool: Boolean value of the configuration
    """
    value = toolkit.config.get(key, default)

    # Some runtime-edited values can end up as lists (eg hidden+checkbox
    # combinations). In that case, use the last submitted value.
    if isinstance(value, list):
        if not value:
            return default
        value = value[-1]

    try:
        return toolkit.asbool(value)
    except Exception:
        log.warning('Invalid boolean config %s=%r, using default=%r', key, value, default)
        return default

def get_config_value(key, default=""):
    """
    Retrieve a raw configuration value with an optional default.
    """
    value = toolkit.config.get(key)
    return value if value is not None else default

def should_include_relationships_in_show():
    """
    Feature flag: whether to enrich package_show output with relationships
    when they are missing/empty due to Solr cached dict.

    Default: True (enabled).
    Config key:
      - ckanext.data_gov_gr.include_relationships_in_show
    """
    return get_config_as_bool(
        'ckanext.data_gov_gr.include_relationships_in_show',
        default=True,
    )

def get_powerbi_embed_url():
    """
    Return the configured Power BI embed URL.

    Priority:
    1. Runtime-editable admin config: ``ckanext.data_gov_gr.powerbi_embed_url``
    2. Fallback config file option: ``powerbi.embed_url``
    """
    # 1. Admin-configurable value from /ckan-admin/config
    admin_value = toolkit.config.get('ckanext.data_gov_gr.powerbi_embed_url')
    if admin_value:
        return admin_value.strip()

    # 2. Fallback to static config option in ckan.ini
    ini_value = toolkit.config.get('powerbi.embed_url')
    if ini_value:
        return ini_value.strip()

    return ""


def _resolve_dataset_item_url(raw_value: str) -> str | None:
    """
    Μετατρέπει την τιμή του πεδίου \"query\" σε πλήρες URL.

    Υποστηρίζει:
      - Πλήρες URL (http/https) -> επιστρέφεται όπως είναι
      - Σχετικό path που ξεκινά με \"/\" (π.χ. \"/dataset/?is_hvd=Yes\")
      - Path χωρίς αρχικό \"/\" (π.χ. \"dataset/?is_hvd=Yes\") που
        μετατρέπεται σε \"/dataset/?is_hvd=Yes\"
      - Μόνο το query μέρος (π.χ. \"fq=is_hvd:true\" ή \"?fq=is_hvd:true\"),
        οπότε το προσαρτά στο ``/dataset``.
    """
    raw = (raw_value or '').strip()
    if not raw:
        return None

    lower = raw.lower()
    if lower.startswith('http://') or lower.startswith('https://') or raw.startswith('/'):
        return raw

    # Υποστήριξη για τιμές τύπου \"dataset/?is_hvd=Yes\" χωρίς αρχικό '/'
    if raw.startswith('dataset'):
        return '/' + raw

    base_url = core_helpers.url_for('dataset.search')
    # Αφαιρούμε αρχικό '?' αν υπάρχει, για να ενώσουμε σωστά
    if raw.startswith('?'):
        raw = raw[1:]

    sep = '&' if '?' in base_url else '?'
    return f'{base_url}{sep}{raw}'

def get_dataset_menu_items():
    """
    Επιστρέφει τις παραμετρικές επιλογές του dropdown για τα σύνολα δεδομένων,
    όπως έχουν οριστεί από το /ckan-admin/config.

    Προτεραιότητα πηγών:

      1. Νέα JSON ρύθμιση ``ckanext.data_gov_gr.menu.dataset.items`` (δυναμικός αριθμός επιλογών),
         π.χ. ::

           [
             {\"label\": \"HVDs\", \"query\": \"fq=is_hvd:true\"},
             {\"label\": \"Ιστορικά\", \"query\": \"fq=dataset_type:historical\"}
           ]

         Όπου:
           - ``label``: το κείμενο που θα εμφανιστεί στο dropdown
           - ``query``: το κομμάτι του CKAN search query (π.χ. ``fq=...``)

    Επιστρέφει λίστα από dictionaries με πεδία:
      - ``label``: το κείμενο που θα εμφανιστεί
      - ``url``: πλήρες URL (είτε όπως δόθηκε, είτε προσαρμοσμένο στο ``/dataset``)
    """

    # Δυναμική ρύθμιση με JSON
    # Χρησιμοποιούμε το raw από το config ώστε να ξεχωρίζουμε
    # την περίπτωση «δεν έχει οριστεί καθόλου» (None) από την
    # περίπτωση «ορίστηκε αλλά είναι κενό/[]».
    raw = toolkit.config.get('ckanext.data_gov_gr.menu.dataset.items')
    if raw is not None:
        raw_str = str(raw).strip()
        if raw_str:
            try:
                parsed = json.loads(raw_str)
                items = []
                if isinstance(parsed, list):
                    for entry in parsed:
                        if not isinstance(entry, dict):
                            continue
                        label = (entry.get('label') or '').strip()
                        query = (entry.get('query') or '').strip()
                        if not label or not query:
                            continue

                        url = _resolve_dataset_item_url(query)
                        if not url:
                            continue

                        items.append({'label': label, 'url': url})

                # Ακόμη κι αν η λίστα είναι κενή, σεβόμαστε τη ρύθμιση JSON
                return items
            except Exception as e:
                log.exception('Error parsing ckanext.data_gov_gr.menu.dataset.items JSON: %s', e)
                # Σε περίπτωση σφάλματος επιστρέφουμε κενή λίστα
                return []
        else:
            # Έχει οριστεί το key αλλά είναι κενό -> σημαίνει
            # «καμία επιλογή» για το dropdown
            return []

    # Αν δεν έχει οριστεί καθόλου η JSON ρύθμιση, δεν εμφανίζονται επιλογές
    return []


def _get_default_contact_gitbook_embed_items():
    guides_root = toolkit.config.get('guides_base_url') or 'https://data-gov-gr.gitbook.io/guides'
    guides_root = str(guides_root).rstrip('/')
    faq_root = f'{guides_root}/syxnes-erotiseis'

    return [
        {'title': 'Συχνές ερωτήσεις (Όλες)', 'url': faq_root},
        {'title': 'Γενικά', 'url': f'{faq_root}/genika'},
        {'title': 'Οργανισμοί Δημόσιου Τομέα', 'url': f'{faq_root}/foreis-dimosioy-tomea'},
        {'title': 'Πολίτες & Επιχειρήσεις', 'url': f'{faq_root}/polites-and-epixeiriseis'},
        {'title': 'Τεχνικά θέματα & API', 'url': f'{faq_root}/texnika-themata-and-api'},
        {'title': 'Dataspace, αλτρουιστές και διαμεσολαβητές', 'url': f'{faq_root}/dataspace-altroyistes-kai-diamesolavites'},
    ]


def get_contact_gitbook_embed_items():
    """
    Επιστρέφει τη λίστα επιλογών (τίτλος + URL) για το dropdown του
    embedded GitBook περιεχομένου στη σελίδα /contact.

    Πηγή: ``ckanext.data_gov_gr.contact.gitbook_embed_items`` από /ckan-admin/config,
    ως JSON λίστα από αντικείμενα, π.χ. ::

      [
        {"title": "Γενικά", "url": "https://.../syxnes-erotiseis/genika"},
        {"title": "Οργανισμοί Δημόσιου Τομέα", "url": "https://.../syxnes-erotiseis/foreis-dimosioy-tomea"}
      ]

    Υποστηρίζει και το κλειδί ``label`` αντί για ``title`` για συμβατότητα.

    Επιστρέφει:
      - default λίστα αν το key δεν έχει οριστεί καθόλου
      - κενή λίστα αν έχει οριστεί αλλά είναι κενό/[]
      - λίστα αν έχει οριστεί με έγκυρα items
    """
    raw = toolkit.config.get('ckanext.data_gov_gr.contact.gitbook_embed_items')
    if raw is None:
        return _get_default_contact_gitbook_embed_items()

    if isinstance(raw, list):
        if not raw:
            return []
        raw = raw[-1]

    raw_str = str(raw).strip()
    if not raw_str:
        return []

    try:
        parsed = json.loads(raw_str)
        if not isinstance(parsed, list) or not parsed:
            return []

        items = []
        for entry in parsed:
            if not isinstance(entry, dict):
                continue

            title = (entry.get('title') or entry.get('label') or '').strip()
            url = (entry.get('url') or '').strip()

            if not title or not url:
                continue

            items.append({'title': title, 'url': url})

        return items
    except Exception as e:
        log.exception('Error parsing ckanext.data_gov_gr.contact.gitbook_embed_items JSON: %s', e)
        return []


def has_gitbook_pdf_export():
    """
    Check whether the GitBook PDF export configuration is complete.
    """
    space_id = get_config_value('ckanext.data_gov_gr.gitbook.space_id')
    token = get_config_value('ckanext.data_gov_gr.gitbook.api_token')
    return bool(space_id and token)


def _localize_data_service_label(text):
    """
    Post-process humanized strings for the data-service dataset type so the
    rendered labels match the active locale.
    """
    if not isinstance(text, str):
        return text

    current_lang = lang()
    if current_lang == 'el':
        replacements = {
            'Data-services': 'Υπηρεσίες Δεδομένων',
            'Data-service': 'Υπηρεσία Δεδομένων',
            'Data Services': 'Υπηρεσίες Δεδομένων',
            'Data Service': 'Υπηρεσία Δεδομένων',
        }
    else:
        replacements = {
            'Data-services': 'Data Services',
            'Data-service': 'Data Service',
        }

    for source, target in replacements.items():
        text = text.replace(source, target)

    if current_lang == 'el':
        phrase_replacements = {
            'My Υπηρεσίες Δεδομένων': 'Οι Υπηρεσίες Δεδομένων μου',
            'My Υπηρεσία Δεδομένων': 'Η Υπηρεσία Δεδομένων μου',
            'Create Υπηρεσία Δεδομένων': 'Δημιουργία Υπηρεσίας Δεδομένων',
            'Add Υπηρεσία Δεδομένων': 'Προσθήκη Υπηρεσίας Δεδομένων',
            'Save Υπηρεσία Δεδομένων': 'Αποθήκευση Υπηρεσίας Δεδομένων',
            'Update Υπηρεσία Δεδομένων': 'Ενημέρωση Υπηρεσίας Δεδομένων',
            'View Υπηρεσία Δεδομένων': 'Προβολή Υπηρεσίας Δεδομένων',
        }
        for source, target in phrase_replacements.items():
            text = text.replace(source, target)

        verb_replacements = {
            'Create ': 'Δημιουργία ',
            'Add ': 'Προσθήκη ',
            'Save ': 'Αποθήκευση ',
            'Update ': 'Ενημέρωση ',
            'View ': 'Προβολή ',
        }
        for source, target in verb_replacements.items():
            text = text.replace(source, target)
    return text


def _localize_decision_label(text):
    """
    Post-process humanized strings for the decision dataset type so the
    rendered labels match the active locale.
    """
    if not isinstance(text, str):
        return text

    current_lang = lang()
    if current_lang == 'el':
        replacements = {
            'Decisions': 'Αποφάσεις',
            'Decision': 'Απόφαση',
        }
    else:
        replacements = {}

    for source, target in replacements.items():
        text = text.replace(source, target)

    if current_lang == 'el':
        phrase_replacements = {
            'My Αποφάσεις': 'Οι Αποφάσεις μου',
            'My Απόφαση': 'Η Απόφαση μου',
            'Create Απόφαση': 'Δημιουργία Απόφασης',
            'Add Απόφαση': 'Προσθήκη Απόφασης',
            'Save Απόφαση': 'Αποθήκευση Απόφασης',
            'Update Απόφαση': 'Ενημέρωση Απόφασης',
            'View Απόφαση': 'Προβολή Απόφασης',
        }
        for source, target in phrase_replacements.items():
            text = text.replace(source, target)

        verb_replacements = {
            'Create ': 'Δημιουργία ',
            'Add ': 'Προσθήκη ',
            'Save ': 'Αποθήκευση ',
            'Update ': 'Ενημέρωση ',
            'View ': 'Προβολή ',
        }
        for source, target in verb_replacements.items():
            text = text.replace(source, target)

    return text


def humanize_entity_type(entity_type, object_type, purpose):
    """
    Delegate to CKAN's default helper and localize custom dataset type labels.
    """
    base_value = core_helpers.humanize_entity_type(entity_type, object_type, purpose)
    if object_type == 'data-service':
        return _localize_data_service_label(base_value)
    if object_type == 'decision':
        return _localize_decision_label(base_value)
    return base_value


def should_hide_mqa_tab():
    """
    Ελέγχει αν πρέπει να κρυφτεί το MQA tab βάσει της παραμετροποίησης
    ckanext.data_gov_gr.dataset.hide_mqa_tab στο configuration file.

    Returns:
        bool: True αν πρέπει να κρυφτεί το tab, False διαφορετικά
              Το default είναι True αν δεν έχει δηλωθεί καθόλου
    """
    return get_config_as_bool('ckanext.data_gov_gr.dataset.hide_mqa_tab', default=True)

def should_disable_protected_data():
    """
    Ελέγχει αν πρέπει να απενεργοποιηθούν τα protected data βάσει της παραμετροποίησης
    ckanext.data_gov_gr.dataset.disable_protected_data στο configuration file.

    Returns:
        bool: True αν πρέπει να απενεργοποιηθούν τα protected data, False διαφορετικά
              Το default είναι True αν δεν έχει δηλωθεί καθόλου
    """
    return get_config_as_bool('ckanext.data_gov_gr.dataset.disable_protected_data', default=True)

def should_hide_azure_translation():
    """
    Ελέγχει αν πρέπει να κρυφτεί η azure translation λειτουργία βάσει της παραμετροποίησης
    ckanext.data_gov_gr.dataset.hide_azure_translation στο configuration file.

    Returns:
        bool: True αν πρέπει να κρυφτεί η azure translation, False διαφορετικά
              Το default είναι True αν δεν έχει δηλωθεί καθόλου
    """
    return get_config_as_bool('ckanext.data_gov_gr.dataset.hide_azure_translation', default=True)


def should_show_decision_menu():
    """
    Ελέγχει αν πρέπει να εμφανιστεί το Decision menu βάσει της παραμετροποίησης
    ckanext.data_gov_gr.menu.show_decision στο configuration file.

    Returns:
        bool: True αν πρέπει να εμφανιστεί το menu, False διαφορετικά
              Το default είναι True αν δεν έχει δηλωθεί καθόλου
    """
    return get_config_as_bool('ckanext.data_gov_gr.menu.show_decision', default=True)


def should_show_decision_button():
    """
    Ελέγχει αν πρέπει να εμφανιστεί το κουμπί προσθήκης Απόφασης στις σελίδες οργανισμών
    χρησιμοποιώντας την ίδια παράμετρο με το menu visibility.

    Returns:
        bool: True αν πρέπει να εμφανιστεί το κουμπί, False διαφορετικά
              Το default είναι True αν δεν έχει δηλωθεί καθόλου
    """
    return get_config_as_bool('ckanext.data_gov_gr.menu.show_decision', default=True)

def get_data_service_guides_url():
    """
    Return the configured URL for the data service guides reference.
    """
    return get_config_value('ckanext.data_gov_gr.data_service_guides_url')


def allow_org_admins_public_decisions():
    """
    Ελέγχει αν οι διαχειριστές οργανισμών και οι εκδότες, μπορούν να δημιουργούν δημόσια Decisions.
    Αν η παράμετρος είναι κενή, σχόλιο, ή απουσιάζει, επιστρέφει True.
    """
    value = toolkit.config.get('ckanext.data_gov_gr.decision.allow_org_admins_public')

    # Αν η παράμετρος απουσιάζει, είναι None, κενή string, ή περιέχει μόνο σχόλιο
    if value is None:
        return True

    value_str = str(value).strip()

    # Αν είναι κενή ή ξεκινά με # (σχόλιο)
    if value_str == '' or value_str.startswith('#'):
        return True

    # Αν έχει τιμή, μετατρέπεται σε boolean
    return toolkit.asbool(value)

def extract_iframe_from_html(html):
    """
    Επιστρέφει ένα dict με:
    - body: το HTML χωρίς το πρώτο <iframe>...</iframe>
    - iframe: το πρώτο iframe μπλοκ (ή κενό string αν δεν βρεθεί)
    """
    if not isinstance(html, str) or '<iframe' not in html.lower():
        return {
            'body': html,
            'iframe': '',
        }

    pattern = re.compile(r'<iframe\b[^>]*>.*?</iframe>', re.IGNORECASE | re.DOTALL)
    match = pattern.search(html)
    if not match:
        return {
            'body': html,
            'iframe': '',
        }

    iframe_html = match.group(0)
    body_html = pattern.sub('', html, count=1)

    return {
        'body': body_html,
        'iframe': iframe_html,
    }

# ---------------------------------------------------------------------------------------

def dump_json(obj):
    """
    JSON dump helper safe for embedding in HTML attributes.
    """
    try:
        return json.dumps(obj, ensure_ascii=False)
    except TypeError:
        return json.dumps(str(obj), ensure_ascii=False)


def _safe_url_for(endpoint: str, **kwargs) -> str | None:
    try:
        return toolkit.url_for(endpoint, **kwargs)
    except Exception:
        return None


def get_stats_url(default: str = '/stats') -> str:
    """
    Επιστρέφει URL για τη σελίδα στατιστικών.

    Αν δεν υπάρχει route `stats.index` (π.χ. δεν είναι ενεργό το stats), κάνει
    fallback σε στατικό path ώστε να μην “σπάει” η αρχική.
    """
    return _safe_url_for('stats.index') or default


def get_home_stats_tiles():
    """
    Return configured stats tiles for the home page (up to 4).

    Reads:
      - ckanext.data_gov_gr.home.stats.item1-4
    """
    catalog = _get_home_stats_catalog()
    catalog_by_id = {item['id']: item for item in catalog}

    selected: list[str] = []
    for idx in range(1, 5):
        key = f'ckanext.data_gov_gr.home.stats.item{idx}'
        raw_value = toolkit.config.get(key, '')
        if isinstance(raw_value, list):
            raw_value = raw_value[-1] if raw_value else ''

        stat_id = (raw_value or '').strip()
        if not stat_id or stat_id not in catalog_by_id:
            continue
        if stat_id in selected:
            continue
        selected.append(stat_id)

    selected_tiles = [catalog_by_id[stat_id] for stat_id in selected]
    if _current_user_is_sysadmin():
        return selected_tiles

    return [
        tile
        for tile in selected_tiles
        if not tile.get('requires_sysadmin')
    ]


def get_home_total_datasets() -> int:
    """
    Return total number of public datasets.
    """
    try:
        res = toolkit.get_action('package_search')(
            {},
            {'q': '*:*', 'fq': 'dataset_type:dataset', 'rows': 0},
        )
        return int(res.get('count', 0) or 0)
    except Exception as e:
        log.error('Error counting total datasets: %s', e)
        return 0


def count_home_dataset_resources() -> int:
    """
    Επιστρέφει το συνολικό πλήθος ενεργών πόρων για ενεργά δημόσια datasets.

    Εξαιρούνται:
      - πόροι από μη ενεργά ή private packages
      - packages που δεν είναι τύπου dataset
      - synthetic πόροι downloadall με marker downloadall_metadata_modified
    """
    try:
        count = (
            model.Session.query(func.count(model.Resource.id))
            .join(model.Package, model.Resource.package_id == model.Package.id)
            .filter(model.Resource.state == 'active')
            .filter(model.Package.state == 'active')
            .filter(model.Package.private == False)
            .filter(model.Package.type == 'dataset')
            .filter(
                or_(
                    model.Resource.extras.is_(None),
                    ~model.Resource.extras.like('%downloadall_metadata_modified%')
                )
            )
            .scalar()
        )
        return int(count or 0)
    except Exception as e:
        log.error('Error counting homepage dataset resources: %s', e)
        return 0


def get_home_dataset_resources_snapshot():
    """
    Διαβάζει το αποθηκευμένο snapshot του πλήθους πόρων της αρχικής από το system_info.
    """
    raw_value = get_system_info(HOME_DATASET_RESOURCES_SNAPSHOT_KEY)
    if not raw_value:
        return None

    try:
        payload = json.loads(raw_value)
    except (TypeError, ValueError):
        log.warning(
            'Invalid homepage dataset resources snapshot payload for key %s',
            HOME_DATASET_RESOURCES_SNAPSHOT_KEY,
        )
        return None

    if not isinstance(payload, dict):
        return None

    count = payload.get('count')
    computed_at = payload.get('computed_at')

    try:
        count = int(count)
    except (TypeError, ValueError):
        return None

    if computed_at is not None and not isinstance(computed_at, str):
        return None

    return {
        'count': count,
        'computed_at': computed_at,
    }


def get_home_datasets_vs_services() -> dict:
    """
    Return counts for datasets vs data services.
    """
    try:
        stats = DataGovStats()
        return stats.datasets_vs_services()
    except Exception as e:
        log.error('Error loading datasets vs services: %s', e)
        return {'datasets': 0, 'data_services': 0}


def _get_configured_home_showcase_ids():
    raw_ids = get_config_value('ckanext.data_gov_gr.home.showcases.ids', '')
    if not raw_ids:
        return []

    # Handle values that can be lists (eg multiple submissions).
    if isinstance(raw_ids, list):
        raw_ids = raw_ids[-1] if raw_ids else ''

    ids_source = str(raw_ids).replace('\\n', '\n')
    candidates = [
        candidate.strip()
        for candidate in re.split(r'[\n,]+', ids_source)
        if candidate.strip()
    ]

    configured_ids = []
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        configured_ids.append(candidate)
    return configured_ids


def _approved_public_showcase_query():
    approval_extra = aliased(model.PackageExtra)
    return (
        model.Session.query(model.Package)
        .join(
            approval_extra,
            and_(
                approval_extra.package_id == model.Package.id,
                approval_extra.key == 'approval_status',
                approval_extra.state == 'active',
                func.lower(func.trim(approval_extra.value)) == 'approved',
            ),
        )
        .filter(model.Package.type == 'showcase')
        .filter(model.Package.state == 'active')
        .filter(or_(
            model.Package.private.is_(False),
            model.Package.private.is_(None),
        ))
        .distinct()
    )


def _showcase_image_display_url(image_url):
    if not image_url:
        return None
    if isinstance(image_url, str) and not image_url.startswith('http'):
        try:
            return core_helpers.url_for_static(
                f'uploads/showcase/{image_url}', qualified=True
            )
        except Exception:
            return None
    return image_url


def _package_extra_value(pkg, key):
    extras = getattr(pkg, '_extras', {}) or {}
    extra = extras.get(key)
    if extra is None or getattr(extra, 'state', None) != 'active':
        return ''
    return extra.value or ''


def _home_showcase_card(pkg, organization_title=''):
    title = pkg.title or pkg.name
    notes = pkg.notes or ''

    submitter_organization = (
        _package_extra_value(pkg, 'submitter_organization') or ''
    ).strip()
    submitter_author = (pkg.author or '').strip()
    submitter_parts = [
        part for part in (submitter_organization, submitter_author) if part
    ]
    submitter_label = ' | '.join(submitter_parts) if submitter_parts else ''

    org_title = (organization_title or '').strip()
    responsible = (pkg.maintainer or submitter_author or '').strip()
    owner_parts = [part for part in (responsible, org_title) if part]
    owner_label = ' - '.join(owner_parts) if owner_parts else ''

    tag_label = ''
    for package_tag in getattr(pkg, 'package_tags', []) or []:
        if getattr(package_tag, 'state', None) != 'active':
            continue
        tag = getattr(package_tag, 'tag', None)
        if tag is not None:
            tag_label = (tag.name or '').strip()
            break

    return {
        'name': pkg.name,
        'title': title,
        'notes': notes,
        'image_url': _showcase_image_display_url(
            _package_extra_value(pkg, 'image_url')
        ),
        'organization_title': org_title,
        'submitter_organization': submitter_organization,
        'submitter_author': submitter_author,
        'submitter_label': submitter_label,
        'owner_label': owner_label,
        'views_total': None,
        'views_display': None,
        'tag': tag_label,
    }


def get_home_showcases(max_items=4):
    """
    Return up to ``max_items`` selected showcases for the home page.

    Values come from:
      - ckanext.data_gov_gr.home.showcases.ids (one showcase name/id per line)
    """
    try:
        limit = max(0, int(max_items))
    except Exception:
        limit = 4
    if not limit:
        return []

    candidates = _get_configured_home_showcase_ids()
    if not candidates:
        return []

    organization = aliased(model.Group)
    try:
        rows = (
            _approved_public_showcase_query()
            .options(
                joinedload(model.Package._extras),
                joinedload(model.Package.package_tags).joinedload(
                    model.PackageTag.tag
                ),
            )
            .outerjoin(
                organization,
                and_(
                    model.Package.owner_org == organization.id,
                    organization.state == 'active',
                ),
            )
            .add_columns(organization.title, organization.name)
            .filter(or_(
                model.Package.id.in_(candidates),
                model.Package.name.in_(candidates),
            ))
            .all()
        )
    except Exception as e:
        log.error('Error loading home showcases: %s', e)
        return []

    packages_by_identifier = {}
    organization_titles = {}
    for pkg, org_title, org_name in rows:
        org_label = org_title or org_name or ''
        packages_by_identifier[pkg.id] = pkg
        packages_by_identifier[pkg.name] = pkg
        organization_titles[pkg.id] = org_label

    showcases = []
    seen_package_ids = set()
    for showcase_name in candidates:
        pkg = packages_by_identifier.get(showcase_name)
        if pkg is None:
            continue
        if pkg.id in seen_package_ids:
            continue
        seen_package_ids.add(pkg.id)
        showcases.append(_home_showcase_card(pkg, organization_titles.get(pkg.id, '')))
        if len(showcases) >= limit:
            break

    return showcases


def get_home_featured_dataset_views(max_items=6):
    """
    Return up to ``max_items`` selected dataset resource views for the home page.

    Values come from:
      - ckanext.data_gov_gr.home.featured_dataset_views.ids (one view ID per line)
    """
    try:
        limit = max(0, int(max_items))
    except Exception:
        limit = 6
    if not limit:
        return []

    raw_ids = get_config_value('ckanext.data_gov_gr.home.featured_dataset_views.ids', '')
    if not raw_ids:
        return []

    if isinstance(raw_ids, list):
        raw_ids = raw_ids[-1] if raw_ids else ''

    ids_source = str(raw_ids).replace('\\n', '\n')
    candidates = [line.strip().strip(',') for line in ids_source.splitlines() if line.strip().strip(',')]
    if not candidates:
        candidates = [part.strip() for part in ids_source.split(',') if part.strip()]
    if not candidates:
        return []

    view_ids: list[str] = []
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        view_ids.append(candidate)
        if len(view_ids) >= limit:
            break

    context = {
        'user': getattr(g, 'user', None),
        'auth_user_obj': getattr(g, 'userobj', None),
    }

    featured = []
    for view_id in view_ids:
        try:
            resource_view = toolkit.get_action('resource_view_show')(context, {'id': view_id})
        except toolkit.ObjectNotFound:
            log.warning('Home featured dataset view "%s" not found', view_id)
            continue
        except toolkit.NotAuthorized:
            continue
        except Exception as e:
            log.error('Error loading home featured dataset view "%s": %s', view_id, e)
            continue

        resource_id = resource_view.get('resource_id')
        if not resource_id:
            continue

        try:
            resource = toolkit.get_action('resource_show')(context, {'id': resource_id})
        except toolkit.ObjectNotFound:
            continue
        except toolkit.NotAuthorized:
            continue
        except Exception as e:
            log.error('Error loading resource for home view "%s": %s', view_id, e)
            continue

        package_id = resource.get('package_id')
        if not package_id:
            continue

        try:
            package = toolkit.get_action('package_show')(context, {'id': package_id})
        except toolkit.ObjectNotFound:
            continue
        except toolkit.NotAuthorized:
            continue
        except Exception as e:
            log.error('Error loading package for home view "%s": %s', view_id, e)
            continue

        package_type = package.get('type') or 'dataset'
        package_name = package.get('name') or package.get('id')
        dataset_title = package.get('title') or package_name or ''

        link = ''
        embed_src = ''
        try:
            link = toolkit.url_for(
                f'{package_type}_resource.read',
                id=package_name,
                resource_id=resource.get('id'),
            ) + f"?view_id={resource_view.get('id')}"
            embed_src = toolkit.url_for(
                f'{package_type}_resource.view',
                id=package_name,
                resource_id=resource.get('id'),
                view_id=resource_view.get('id'),
            )
        except Exception:
            pass

        try:
            iframed = core_helpers.resource_view_is_iframed(resource_view)
        except Exception:
            iframed = True

        featured.append({
            'id': resource_view.get('id') or view_id,
            'title': (resource_view.get('title') or '').strip() or dataset_title,
            'description': (resource_view.get('description') or '').strip(),
            'dataset_title': dataset_title,
            'link': link,
            'embed_src': embed_src,
            'iframed': iframed,
            'view': resource_view,
            'resource': resource,
            'package': package,
        })

    return featured


def get_available_showcases(limit=200):
    """
    Return list of available showcases for selection in /ckan-admin/config.
    """
    try:
        q = _approved_public_showcase_query().order_by(model.Package.title.asc())
        if limit:
            q = q.limit(int(limit))
        results = q.all()
    except Exception as e:
        log.error('Error listing showcases for admin config: %s', e)
        return []

    available = []
    for pkg in results:
        available.append({
            'name': pkg.name,
            'title': pkg.title or pkg.name,
        })

    return available


def _strip_html(text: str) -> str:
    cleaned = re.sub(r'<[^>]+>', ' ', text or '')
    cleaned = html_unescape(cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def get_home_news_items(max_items=3):
    """
    Return latest blog posts from ckanext-pages (/blog).
    """
    try:
        limit = max(0, int(max_items))
    except Exception:
        limit = 3
    if not limit:
        return []

    context = {
        'user': getattr(g, 'user', None),
        'auth_user_obj': getattr(g, 'userobj', None),
    }

    try:
        blog_list = toolkit.get_action('ckanext_pages_list')(
            context,
            {
                'order_publish_date': True,
                'page_type': 'blog',
                'private': False,
            },
        )
    except Exception as e:
        log.error('Error loading blog posts for home page: %s', e)
        return []

    items = []
    for post in blog_list or []:
        if len(items) >= limit:
            break

        name = (post or {}).get('name')
        if not name:
            continue

        title = (post.get('title') or name).strip()

        summary = (post.get('summary') or post.get('excerpt') or '').strip()
        if not summary:
            summary = _strip_html(post.get('content') or '')

        publish_date = post.get('publish_date')
        dt = None
        if publish_date:
            try:
                dt = datetime.fromisoformat(str(publish_date).replace('Z', '+00:00'))
            except Exception:
                dt = None

        date_day = date_month = date_year = date_short = None
        if dt:
            date_day = str(dt.day)
            date_month = _month_abbrev(dt.month, lang())
            date_year = str(dt.year)
            date_short = f'{dt.day}/{dt.month}'

        link = _safe_url_for('pages.blog_show', page=name) or f'/{lang()}/blog/{name}'

        items.append({
            'title': title,
            'link': link,
            'summary': summary,
            'date_day': date_day,
            'date_month': date_month,
            'date_year': date_year,
            'date_short': date_short,
        })

    return items


def _format_counter(value: int) -> str:
    try:
        return f"{int(value):,}".replace(',', ' ')
    except Exception:
        return str(value)


def _home_reuse_to_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            return int(value)
    return None


def _home_reuse_spark_payload(series_name: str, points: list[list[object]]):
    if not points:
        return None
    return {
        'xAxisType': 'time',
        'series': [
            {'name': series_name, 'data': points},
        ],
    }


def _home_reuse_normalize_date_key(value):
    """
    Κανονικοποιεί keys ημερομηνίας ώστε το ECharts time axis να τα διαβάζει.

    Το Matomo μπορεί να επιστρέψει:
      - YYYY-MM-DD (period=day)
      - YYYY-MM (period=month)
    """
    s = str(value or '').strip()
    if len(s) == 7 and s[4] == '-' and s[:4].isdigit() and s[5:7].isdigit():
        return f'{s}-01'
    return s


def _home_reuse_extract_timeseries(payload, key=None):
    """
    Εξάγει time series από Matomo payload (dict(date -> value/row)).
    Επιστρέφει list of [date_iso, value_int] ταξινομημένο.
    """
    if not isinstance(payload, dict) or not payload:
        return []

    points: list[list[object]] = []
    for date_key, row in sorted(payload.items(), key=lambda kv: str(kv[0])):
        value_int = None
        if isinstance(row, dict):
            if key and key in row:
                value_int = _home_reuse_to_int(row.get(key))
            elif 'value' in row:
                value_int = _home_reuse_to_int(row.get('value'))
        else:
            value_int = _home_reuse_to_int(row)

        if value_int is None:
            continue

        points.append([_home_reuse_normalize_date_key(date_key), value_int])
    return points


def _home_reuse_extract_download_timeseries(payload):
    """
    Εξάγει time series λήψεων από Actions.getDownloads payload.
    Αναμένει dict(date -> list(rows)), όπου κάθε row έχει nb_hits.
    """
    if not isinstance(payload, dict) or not payload:
        return []

    points: list[list[object]] = []
    for date_key, rows in sorted(payload.items(), key=lambda kv: str(kv[0])):
        day_total = 0
        found = False
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                value_int = _home_reuse_to_int(row.get('nb_hits'))
                if value_int is not None:
                    day_total += value_int
                    found = True
        if found:
            points.append([_home_reuse_normalize_date_key(date_key), day_total])
    return points


def _home_reuse_extract_metric(payload, key=None, *, sum_time_series=True):
    """
    Best-effort εξαγωγή αριθμητικού metric από Matomo payloads.
    """
    if payload is None:
        return None

    if isinstance(payload, dict) and 'value' in payload:
        value_int = _home_reuse_to_int(payload.get('value'))
        if value_int is not None:
            return value_int

    if isinstance(payload, dict) and key and key in payload:
        return _home_reuse_to_int(payload.get(key))

    if isinstance(payload, dict):
        if not sum_time_series:
            if len(payload) == 1:
                _date, row = next(iter(payload.items()))
                if isinstance(row, dict):
                    if key and key in row:
                        return _home_reuse_to_int(row.get(key))
                    if 'value' in row:
                        return _home_reuse_to_int(row.get('value'))
                return _home_reuse_to_int(row)
            return None

        total = 0
        found = False
        for _date, row in payload.items():
            value_int = None
            if isinstance(row, dict):
                if key and key in row:
                    value_int = _home_reuse_to_int(row.get(key))
                elif 'value' in row:
                    value_int = _home_reuse_to_int(row.get('value'))
            else:
                value_int = _home_reuse_to_int(row)
            if value_int is not None:
                total += value_int
                found = True
        return total if found else None

    if isinstance(payload, list):
        total = 0
        found = False
        for row in payload:
            value_int = _home_reuse_to_int(row)
            if value_int is not None:
                total += value_int
                found = True
        return total if found else None

    return _home_reuse_to_int(payload)


def _home_reuse_sum_download_hits(rows) -> int:
    if not rows:
        return 0
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        value_int = _home_reuse_to_int(row.get('nb_hits'))
        if value_int is not None:
            total += value_int
    return total


def _home_reuse_compute_apps_total() -> int:
    """
    Μετράει τις εγκεκριμένες εφαρμογές (showcases).

    Σημείωση για deployments με approval workflow:
    - Μετράμε μόνο τις εγκεκριμένες (``approval_status=approved``).
    """
    try:
        showcase_pkg = aliased(model.Package)
        showcase_extra = aliased(model.PackageExtra)

        count_value = (
            model.Session.query(func.count(func.distinct(showcase_pkg.id)))
            .join(
                showcase_extra,
                and_(
                    showcase_extra.package_id == showcase_pkg.id,
                    showcase_extra.key == 'approval_status',
                    func.lower(func.trim(showcase_extra.value)) == 'approved',
                ),
            )
            .filter(showcase_pkg.type == 'showcase')
            .filter(showcase_pkg.state == 'active')
            .scalar()
        )
        return int(count_value or 0)
    except Exception:
        log.exception('Αποτυχία μέτρησης εφαρμογών (showcases) από τη βάση.')
        return 0


def _home_reuse_compute_apps_spark() -> dict | None:
    """
    Δημιουργεί sparkline (τελευταίοι 12 μήνες) για δημιουργίες εφαρμογών.
    """
    try:
        showcase_pkg = aliased(model.Package)
        showcase_extra = aliased(model.PackageExtra)

        end_month = _month_start(datetime.utcnow().date())
        start_month = _add_months(end_month, -11)

        daily_rows = (
            model.Session.query(
                func.date(showcase_pkg.metadata_created).label('day'),
                func.count(func.distinct(showcase_pkg.id)).label('count'),
            )
            .join(
                showcase_extra,
                and_(
                    showcase_extra.package_id == showcase_pkg.id,
                    showcase_extra.key == 'approval_status',
                    func.lower(func.trim(showcase_extra.value)) == 'approved',
                ),
            )
            .filter(showcase_pkg.type == 'showcase')
            .filter(showcase_pkg.state == 'active')
            .filter(showcase_pkg.metadata_created >= datetime.combine(start_month, datetime.min.time()))
            .group_by('day')
            .all()
        )

        per_month: dict[tuple[int, int], int] = {}
        for day_value, count_value in daily_rows:
            if isinstance(day_value, datetime):
                day_key = day_value.date()
            else:
                day_key = day_value
            if not isinstance(day_key, date_cls):
                continue
            mk = (day_key.year, day_key.month)
            per_month[mk] = int(per_month.get(mk, 0)) + int(count_value or 0)

        points: list[list[object]] = []
        for i in range(12):
            d = _add_months(start_month, i)
            mk = (d.year, d.month)
            points.append([d.isoformat(), int(per_month.get(mk, 0))])

        return {
            'xAxisType': 'time',
            'series': [{'name': 'Apps', 'data': points}],
        }
    except Exception:
        log.exception('Αποτυχία υπολογισμού sparkline εφαρμογών (showcases) από τη βάση.')
        return None

def get_home_reuse_stats() -> dict:
    """
    Στατιστικά “επαναχρησιμοποίησης” (δεξιά στήλη αρχικής).

    Αν υπάρχει ρύθμιση Matomo, τα visits/downloads έρχονται από Matomo. Αν όχι,
    επιστρέφουμε ``None`` στα αντίστοιχα πεδία.
    """
    now_ts = time.time()
    lang_code = lang()
    redis_enabled = get_config_as_bool('ckanext.data_gov_gr.home.reuse_stats.redis.enabled', True)
    redis_key_override = (toolkit.config.get('ckanext.data_gov_gr.home.reuse_stats.redis.key') or '').strip()
    async_refresh_enabled = get_config_as_bool('ckanext.data_gov_gr.home.reuse_stats.async_refresh_enabled', True)
    refresh_after_raw = toolkit.config.get('ckanext.data_gov_gr.home.reuse_stats.redis.refresh_after_seconds')
    try:
        redis_refresh_after_seconds = max(0, int(refresh_after_raw or 60 * 60 * 6))
    except Exception:
        redis_refresh_after_seconds = 60 * 60 * 6
    max_stale_raw = toolkit.config.get('ckanext.data_gov_gr.home.reuse_stats.redis.max_stale_seconds')
    try:
        redis_max_stale_seconds = max(0, int(max_stale_raw or 60 * 60 * 24 * 14))
    except Exception:
        redis_max_stale_seconds = 60 * 60 * 24 * 14

    matomo_domain = (toolkit.config.get('ckanext.matomo.domain') or '').strip().rstrip('/')
    matomo_api_url = (toolkit.config.get('ckanext.matomo.api_domain') or '').strip()
    if not matomo_api_url and matomo_domain:
        # Συνήθως το Matomo API σερβίρεται μέσω `/index.php`.
        # Το tracking script χρησιμοποιεί base domain, αλλά για API κλήσεις
        # στο CKAN θέλουμε `/index.php` ώστε να παίρνουμε JSON.
        matomo_api_url = f'{matomo_domain}/index.php'
    matomo_api_url = matomo_api_url.rstrip('/')
    matomo_site_id = (toolkit.config.get('ckanext.matomo.site_id') or '').strip()
    matomo_token = (toolkit.config.get('ckanext.matomo.token_auth') or '').strip()
    matomo_enabled = bool(matomo_api_url and matomo_site_id and matomo_token)

    matomo_period = (toolkit.config.get('ckanext.data_gov_gr.home.reuse_stats.matomo.period') or 'range').strip()
    # Ρυθμίσεις ημερομηνιών (compat): κοινό date ή ξεχωριστά για visits/downloads.
    matomo_date_common = (toolkit.config.get('ckanext.data_gov_gr.home.reuse_stats.matomo.date') or '').strip()
    matomo_date_visitors = (
        toolkit.config.get('ckanext.data_gov_gr.home.reuse_stats.matomo.visits_date')
        or matomo_date_common
        or 'last365'
    ).strip()
    matomo_date_downloads = (
        toolkit.config.get('ckanext.data_gov_gr.home.reuse_stats.matomo.downloads_date')
        or matomo_date_common
        or 'last365'
    ).strip()
    default_matomo_start_date = '2025-02-01'
    matomo_start_date = (toolkit.config.get('ckanext.data_gov_gr.home.reuse_stats.matomo.start_date') or '').strip()
    if not matomo_start_date:
        matomo_start_date = default_matomo_start_date

    if matomo_start_date:
        matomo_period = 'range'
        range_date = f'{matomo_start_date},today'
        matomo_date_visitors = range_date
        matomo_date_downloads = range_date

    spark_range_display = None
    spark_range = None
    # Προεπιλογή: γραμμή τάσης τελευταίων 12 μηνών.
    spark_period = (toolkit.config.get('ckanext.data_gov_gr.home.reuse_stats.spark.period') or 'month').strip()
    spark_date = (toolkit.config.get('ckanext.data_gov_gr.home.reuse_stats.spark.date') or 'last12').strip()

    cache_key = (
        f'home_reuse_stats|lang={lang_code}'
        f'|matomo_api_url={matomo_api_url}'
        f'|matomo_site_id={matomo_site_id}'
        f'|matomo_period={matomo_period}'
        f'|visits_date={matomo_date_visitors}'
        f'|downloads_date={matomo_date_downloads}'
        f'|spark_period={spark_period}'
        f'|spark_date={spark_date}'
        f'|start_date={matomo_start_date}'
    )
    redis_key = None
    if redis_enabled and (toolkit.config.get('ckan.redis.url') or '').strip():
        site_id = (toolkit.config.get('ckan.site_id') or 'default').strip()
        redis_key = redis_key_override or f'ckan:{site_id}:ckanext:data_gov_gr:home_reuse_stats:{lang_code}'

    try:
        if spark_period == 'month' and spark_date.startswith('last') and spark_date[4:].isdigit():
            months = int(spark_date[4:])
            if months > 0:
                end_month = date_cls(datetime.utcnow().year, datetime.utcnow().month, 1)

                start_month = _add_months(end_month, -(months - 1))
                spark_range = {
                    'start': f'{start_month:%m/%y}',
                    'end': f'{end_month:%m/%y}',
                }
                spark_range_display = f'{start_month:%m/%Y} – {end_month:%m/%Y}'
        elif spark_period == 'day' and spark_date.startswith('last') and spark_date[4:].isdigit():
            days = int(spark_date[4:])
            if days > 0:
                end_day = datetime.utcnow().date()
                start_day = end_day - timedelta(days=days - 1)
                spark_range = {
                    'start': f'{start_day:%d/%m/%y}',
                    'end': f'{end_day:%d/%m/%y}',
                }
                spark_range_display = f'{start_day:%d/%m/%Y} – {end_day:%d/%m/%Y}'
    except Exception:
        spark_range_display = None
        spark_range = None

    def _compute_result(*, include_matomo: bool = True) -> dict:
        apps_total = _home_reuse_compute_apps_total()
        apps_spark = _home_reuse_compute_apps_spark()

        visitors_total = None
        downloads_total = None
        visitors_label = None
        downloads_label = None
        visitors_spark = None
        downloads_spark = None

        if include_matomo and matomo_enabled:
            try:
                from ckanext.matomo.matomo_api import MatomoAPI  # type: ignore
            except Exception:
                MatomoAPI = None  # type: ignore
                log.debug('Δεν ήταν δυνατή η φόρτωση του MatomoAPI client.', exc_info=True)

            if MatomoAPI:
                api = MatomoAPI(matomo_api_url, matomo_site_id, matomo_token)

                try:
                    def _get_total_visits(period: str, date: str):
                        try:
                            summary_payload = api.get({
                                'method': 'VisitsSummary.get',
                                'period': period,
                                'date': date,
                            })
                            value = _home_reuse_extract_metric(summary_payload, key='nb_visits', sum_time_series=False)
                            if value is not None:
                                return value
                        except Exception:
                            log.debug('Αποτυχία Matomo VisitsSummary.get (total).', exc_info=True)

                        return None

                    visitors_total = _get_total_visits(matomo_period, matomo_date_visitors)
                    if visitors_total is not None:
                        visitors_label = 'Total Visits'
                except Exception:
                    log.warning(
                        "Matomo visitors metric failed (url=%s site_id=%s period=%s date=%s).",
                        matomo_api_url,
                        matomo_site_id,
                        matomo_period,
                        matomo_date_visitors,
                    )
                    visitors_total = None

                try:
                    spark_visitors_payload = api.get({
                        'method': 'VisitsSummary.get',
                        'period': spark_period,
                        'date': spark_date,
                    })
                    visitors_points = _home_reuse_extract_timeseries(spark_visitors_payload, key='nb_visits')
                    visitors_spark = _home_reuse_spark_payload('Visits', visitors_points)
                except Exception:
                    visitors_spark = None
                    log.debug('Αποτυχία Matomo VisitsSummary.get (spark).', exc_info=True)

                try:
                    downloads = api.get({
                        'method': 'Actions.getDownloads',
                        'period': matomo_period,
                        'date': matomo_date_downloads,
                        'flat': 1,
                    })

                    if isinstance(downloads, list):
                        downloads_total = _home_reuse_sum_download_hits(downloads)
                    elif isinstance(downloads, dict):
                        downloads_total = sum(
                            _home_reuse_sum_download_hits(v) for v in downloads.values() if isinstance(v, list)
                        )

                    if downloads_total is not None:
                        downloads_label = 'Total Downloads'
                except Exception:
                    log.warning(
                        "Matomo downloads metric failed (url=%s site_id=%s period=%s date=%s).",
                        matomo_api_url,
                        matomo_site_id,
                        matomo_period,
                        matomo_date_downloads,
                    )
                    downloads_total = None

                try:
                    spark_downloads_payload = api.get({
                        'method': 'Actions.getDownloads',
                        'period': spark_period,
                        'date': spark_date,
                        'flat': 1,
                    })
                    downloads_points = _home_reuse_extract_download_timeseries(spark_downloads_payload)
                    downloads_spark = _home_reuse_spark_payload('Downloads', downloads_points)
                except Exception:
                    downloads_spark = None
                    log.debug('Αποτυχία Matomo Actions.getDownloads (spark).', exc_info=True)

        return {
            'fetched_at': int(time.time()),
            'visitors_total': visitors_total,
            'downloads_total': downloads_total,
            'apps_total': apps_total,
            'apps_display': _format_counter(apps_total),
            'visitors_label': visitors_label,
            'downloads_label': downloads_label,
            'visitors_spark': visitors_spark,
            'downloads_spark': downloads_spark,
            'apps_spark': apps_spark,
            'spark_range_display': spark_range_display,
            'spark_range': spark_range,
        }

    def _store_redis(redis_conn, key: str, result: dict) -> None:
        payload = {
            'cache_key': cache_key,
            'ts': time.time(),
            'data': result,
        }
        raw_value = json.dumps(payload, ensure_ascii=False)
        if redis_max_stale_seconds and redis_max_stale_seconds > 0:
            redis_conn.setex(key, int(redis_max_stale_seconds), raw_value)
        else:
            redis_conn.set(key, raw_value)

    def _submit_background_refresh(reason: str) -> None:
        """
        Ανανεώνει στο παρασκήνιο τη Redis cache (χωρίς να μπλοκάρουμε την απόκριση).

        Χρησιμοποιεί:
        - Φραγή ανά διεργασία (cache_key) για να μη γεμίζουμε τον executor
        - Redis lock για να μη κάνουν πολλές διεργασίες refresh ταυτόχρονα
        """
        if not (redis_key and matomo_enabled and async_refresh_enabled):
            return

        with _HOME_REUSE_STATS_IN_FLIGHT_LOCK:
            if cache_key in _HOME_REUSE_STATS_IN_FLIGHT:
                return
            _HOME_REUSE_STATS_IN_FLIGHT.add(cache_key)

        def _run():
            lock_acquired = False
            lock_key = f'{redis_key}:refresh_lock'
            lock_value = f'{os.getpid()}:{threading.get_ident()}:{time.time()}'
            try:
                from ckan.lib.redis import connect_to_redis  # type: ignore
                redis_conn_bg = connect_to_redis()
                lock_acquired = bool(redis_conn_bg.set(lock_key, lock_value, nx=True, ex=300))
                if not lock_acquired:
                    return
                fresh = _compute_result(include_matomo=True)
                _store_redis(redis_conn_bg, redis_key, fresh)
            except Exception:
                log.debug('Αποτυχία background refresh reuse stats (%s).', reason, exc_info=True)
            finally:
                try:
                    model.Session.remove()
                except Exception:
                    pass
                if lock_acquired:
                    try:
                        existing = redis_conn_bg.get(lock_key)
                        if isinstance(existing, (bytes, bytearray)):
                            existing = existing.decode('utf-8', errors='replace')
                        if existing == lock_value:
                            redis_conn_bg.delete(lock_key)
                    except Exception:
                        pass
                with _HOME_REUSE_STATS_IN_FLIGHT_LOCK:
                    _HOME_REUSE_STATS_IN_FLIGHT.discard(cache_key)

        try:
            _HOME_REUSE_STATS_EXECUTOR.submit(_run)
        except Exception:
            # Αν αποτύχει το submit, καθαρίζουμε το in-flight guard ώστε να μη μείνει "κολλημένο".
            log.debug('Αποτυχία υποβολής εργασίας ανανέωσης reuse stats στο παρασκήνιο.', exc_info=True)
            with _HOME_REUSE_STATS_IN_FLIGHT_LOCK:
                _HOME_REUSE_STATS_IN_FLIGHT.discard(cache_key)

    # Αν υπάρχει cache στο Redis και δεν είναι υπερβολικά παλιά, τη χρησιμοποιούμε.
    if redis_key:
        try:
            from ckan.lib.redis import connect_to_redis  # type: ignore
            redis_conn = connect_to_redis()
            raw = redis_conn.get(redis_key)
            if raw:
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode('utf-8', errors='replace')
                payload = json.loads(raw)
                if (
                    isinstance(payload, dict)
                    and payload.get('cache_key') == cache_key
                    and isinstance(payload.get('ts'), (int, float))
                    and isinstance(payload.get('data'), dict)
                ):
                    ts = float(payload.get('ts'))
                    age = now_ts - ts
                    if redis_max_stale_seconds <= 0 or age <= float(redis_max_stale_seconds):
                        if redis_refresh_after_seconds and age >= float(redis_refresh_after_seconds):
                            _submit_background_refresh('stale')
                        return payload.get('data')
        except Exception:
            log.debug('Αποτυχία ανάγνωσης cache reuse stats από Redis (key=%r).', redis_key, exc_info=True)

    # Cache miss: υπολογίζουμε σύγχρονα (δηλ. γίνεται κλήση στο Matomo όταν είναι ρυθμισμένο).
    result = _compute_result(include_matomo=True)
    if redis_key:
        try:
            from ckan.lib.redis import connect_to_redis  # type: ignore
            redis_conn = connect_to_redis()
            _store_redis(redis_conn, redis_key, result)
        except Exception:
            log.debug('Αποτυχία εγγραφής reuse stats στο Redis (key=%r).', redis_key, exc_info=True)
    return result


def get_home_portal_numbers():
    """
    Return EU-style counters for the home page.

    Controlled by:
      - ckanext.data_gov_gr.home.portal_numbers.enabled
    """
    if not get_config_as_bool('ckanext.data_gov_gr.home.portal_numbers.enabled', True):
        return []

    def _count_packages(fq: str) -> int:
        try:
            res = toolkit.get_action('package_search')({}, {'q': '*:*', 'fq': fq, 'rows': 0})
            return int(res.get('count', 0) or 0)
        except Exception:
            return 0

    datasets_count = get_home_total_datasets()
    apis_count = _count_packages('dataset_type:data-service')
    dataset_resources_snapshot = get_home_dataset_resources_snapshot()

    try:
        orgs_count = int(
            model.Session.query(func.count(model.Group.id))
            .filter(model.Group.type == 'organization')
            .filter(model.Group.state == 'active')
            .scalar()
            or 0
        )
    except Exception:
        orgs_count = 0

    datasets_tile = {
        'value': _format_counter(datasets_count),
        'label': 'Σύνολα Δεδομένων' if lang() == 'el' else 'Datasets',
        'link': _safe_url_for('dataset.search') or f'/{lang()}/dataset',
    }
    if dataset_resources_snapshot:
        datasets_tile.update({
            'resource_value': _format_counter(dataset_resources_snapshot['count']),
            'resource_label': (
                'Πόροι Δεδομένων'
                if lang() == 'el'
                else 'Data Resources'
            ),
        })

    return [
        datasets_tile,
        {
            'value': _format_counter(orgs_count),
            'label': 'Οργανισμοί' if lang() == 'el' else 'Organizations',
            'link': _safe_url_for('organization.index') or f'/{lang()}/organization',
        },
        {
            'value': _format_counter(apis_count),
            'label': _('Data Services'),
            'link': _safe_url_for('data-service.search') or f'/{lang()}/data-service',
        },
    ]


def _organization_index_apps_counts(org_ids):
    counts = {org_id: 0 for org_id in org_ids}
    if not org_ids or ShowcasePackageAssociation is None:
        return counts

    try:
        dataset_pkg = aliased(model.Package)
        showcase_pkg = aliased(model.Package)
        showcase_extra = aliased(model.PackageExtra)

        query = (
            model.Session.query(
                dataset_pkg.owner_org.label('org_id'),
                func.count(func.distinct(showcase_pkg.id)).label('apps_count'),
            )
            .join(
                ShowcasePackageAssociation,
                ShowcasePackageAssociation.package_id == dataset_pkg.id,
            )
            .join(
                showcase_pkg,
                showcase_pkg.id == ShowcasePackageAssociation.showcase_id,
            )
            .join(
                showcase_extra,
                and_(
                    showcase_extra.package_id == showcase_pkg.id,
                    showcase_extra.key == 'approval_status',
                    func.lower(func.trim(showcase_extra.value)) == 'approved',
                ),
            )
            .filter(dataset_pkg.owner_org.in_(org_ids))
            # Μετράμε και datasets και data-services, γιατί πλέον τα showcases
            # μπορούν να συνδέονται και με τους δύο τύπους package.
            .filter(dataset_pkg.type.in_(('dataset', 'data-service')))
            .filter(dataset_pkg.state == 'active')
            .filter(or_(dataset_pkg.private.is_(False), dataset_pkg.private.is_(None)))
            .filter(showcase_pkg.type == 'showcase')
            .filter(showcase_pkg.state == 'active')
            .filter(or_(showcase_pkg.private.is_(False), showcase_pkg.private.is_(None)))
            .group_by(dataset_pkg.owner_org)
        )

        for org_id, apps_count in query.all():
            if org_id in counts:
                counts[org_id] = int(apps_count or 0)
    except Exception as e:
        log.error('Error loading apps counts for organization index: %s', e)

    return counts


def organization_index_stats(org_ids):
    normalized_org_ids = organization_stats.normalize_org_ids(org_ids)

    stats = {
        org_id: {'datasets': 0, 'apis': 0, 'apps': 0}
        for org_id in normalized_org_ids
    }
    if not normalized_org_ids:
        return stats

    datasets_counts = organization_stats.get_public_dataset_counts_for_orgs(
        normalized_org_ids
    )
    apis_counts = organization_stats.get_public_data_service_counts_for_orgs(
        normalized_org_ids
    )
    apps_counts = _organization_index_apps_counts(normalized_org_ids)

    for org_id in normalized_org_ids:
        stats[org_id]['datasets'] = datasets_counts.get(org_id, 0)
        stats[org_id]['apis'] = apis_counts.get(org_id, 0)
        stats[org_id]['apps'] = apps_counts.get(org_id, 0)

    return stats


def organization_visit_sort_available():
    return organization_stats.organization_profile_visit_sort_available()


def organization_visit_sort_enabled():
    return (
        organization_stats.organization_profile_visit_sort_enabled()
        and organization_stats.organization_profile_visit_sort_available()
    )


def organization_visit_sort_default_enabled():
    return (
        organization_stats.organization_profile_visit_sort_default_enabled()
        and organization_stats.organization_profile_visit_sort_available()
    )


def get_stat_data(stat_id, raw_data=None, variant='full'):
    """
    Return normalized chart payload for a given stats ID.

    Used both on /stats pages (raw_data provided) and on home previews.
    """
    catalog = {item['id']: item for item in _get_home_stats_catalog()}
    meta = catalog.get(stat_id)
    if not meta:
        return None
    if meta.get('requires_sysadmin') and not _current_user_is_sysadmin():
        return None

    variant_norm = str(variant or 'full').lower()

    if raw_data is None:
        stats = DataGovStats()
        try:
            if stat_id == 'datasets_by_theme':
                raw_data = stats.datasets_by_theme()
            elif stat_id == 'datasets_by_publisher_type':
                raw_data = stats.datasets_by_publisher_type()
            elif stat_id == 'datasets_by_organization':
                raw_data = stats.datasets_by_organization()
            elif stat_id == 'datasets_vs_services':
                raw_data = stats.datasets_vs_services()
            elif stat_id == 'datasets_by_hvd_category':
                raw_data = stats.datasets_by_hvd_category()
            elif stat_id == 'organizations_by_publisher_type':
                raw_data = stats.organizations_by_publisher_type()
            elif stat_id == 'total_datasets':
                raw_data = stats.get_num_packages_by_week()
            elif stat_id == 'dataset_revisions':
                raw_data = {
                    'revisions': stats.get_by_week('package_revisions'),
                    'new_packages': stats.get_by_week('new_packages'),
                }
            elif stat_id == 'most_edited':
                raw_data = stats.most_edited_packages()
            elif stat_id == 'largest_groups':
                raw_data = stats.largest_groups()
            elif stat_id == 'top_tags':
                raw_data = stats.top_tags()
            elif stat_id == 'top_creators':
                raw_data = stats.top_package_creators()
            elif stat_id == 'powerbi':
                return None
        except Exception as e:
            log.error('Error loading stat data %s: %s', stat_id, e)
            return None

    link = _safe_url_for(meta.get('route')) if meta.get('route') else None

    def _pie_from_tuples(rows):
        data = []
        for code, label, count in rows or []:
            name = (label or code or '').strip()
            data.append({'name': name, 'value': int(count or 0)})
        return data

    def _bar_payload(categories, values, series_name):
        return {
            'categories': categories,
            'series': [
                {'name': series_name, 'data': values}
            ],
        }

    if stat_id in (
        'datasets_by_theme',
        'datasets_by_publisher_type',
        'datasets_vs_services',
        'datasets_by_hvd_category',
        'organizations_by_publisher_type',
    ):
        if stat_id == 'datasets_vs_services':
            data = [
                {'name': _('Datasets'), 'value': int(getattr(raw_data, 'datasets', None) or raw_data.get('datasets', 0) or 0)},
                {'name': _('Data Services'), 'value': int(getattr(raw_data, 'data_services', None) or raw_data.get('data_services', 0) or 0)},
            ]
        else:
            data = _pie_from_tuples(raw_data)

        # Keep previews compact by limiting slices a bit
        if variant_norm == 'preview' and len(data) > 10:
            data = data[:10]

        return {
            'id': stat_id,
            'type': 'pie',
            'title': meta.get('title'),
            'data': data,
            'link': link,
        }

    if stat_id in ('datasets_by_organization', 'most_edited', 'largest_groups', 'top_tags', 'top_creators'):
        categories = []
        values = []

        if stat_id == 'datasets_by_organization':
            for _org_id, org_title, num in raw_data or []:
                categories.append(org_title)
                values.append(int(num or 0))
        elif stat_id == 'most_edited':
            for pkg, num in raw_data or []:
                title = getattr(pkg, 'title', None) or getattr(pkg, 'name', None) or ''
                categories.append(title)
                values.append(int(num or 0))
        elif stat_id == 'largest_groups':
            for grp, num in raw_data or []:
                title = ''
                if grp is not None:
                    title = getattr(grp, 'title', None) or getattr(grp, 'name', None) or ''
                categories.append(title or _('Unknown'))
                values.append(int(num or 0))
        elif stat_id == 'top_tags':
            for tag, num in raw_data or []:
                title = ''
                if tag is not None:
                    title = getattr(tag, 'display_name', None) or getattr(tag, 'name', None) or ''
                categories.append(title or _('Unknown'))
                values.append(int(num or 0))
        elif stat_id == 'top_creators':
            for user, num in raw_data or []:
                title = ''
                if user is not None:
                    title = getattr(user, 'display_name', None) or getattr(user, 'name', None) or ''
                categories.append(title or _('Unknown'))
                values.append(int(num or 0))

        if variant_norm == 'preview' and len(categories) > 8:
            categories = categories[:8]
            values = values[:8]

        return {
            'id': stat_id,
            'type': 'bar',
            'title': meta.get('title'),
            'data': _bar_payload(categories, values, meta.get('title') or ''),
            'link': link,
        }

    if stat_id == 'total_datasets':
        points = []
        for week_date, _num_pkgs, cumulative in raw_data or []:
            points.append([week_date, int(cumulative or 0)])

        if variant_norm == 'preview' and len(points) > 24:
            points = points[-24:]

        return {
            'id': stat_id,
            'type': 'line',
            'title': meta.get('title'),
            'data': {
                'xAxisType': 'time',
                'series': [
                    {'name': _('Total datasets'), 'data': points},
                ],
            },
            'link': link,
        }

    if stat_id == 'dataset_revisions':
        revisions = None
        new_packages = None
        if isinstance(raw_data, dict):
            revisions = raw_data.get('revisions')
            new_packages = raw_data.get('new_packages')
        if revisions is None:
            revisions = []
        if new_packages is None:
            new_packages = []

        series_revisions = []
        for week_date, _pkg_ids, num, _cumulative in revisions or []:
            series_revisions.append([week_date, int(num or 0)])

        series_new = []
        for week_date, _pkg_ids, num, _cumulative in new_packages or []:
            series_new.append([week_date, int(num or 0)])

        if variant_norm == 'preview':
            if len(series_revisions) > 24:
                series_revisions = series_revisions[-24:]
            if len(series_new) > 24:
                series_new = series_new[-24:]

        return {
            'id': stat_id,
            'type': 'line',
            'title': meta.get('title'),
            'data': {
                'xAxisType': 'time',
                'series': [
                    {'name': _('All dataset revisions'), 'data': series_revisions},
                    {'name': _('New datasets'), 'data': series_new},
                ],
            },
            'link': link,
        }

    return None


def is_email_changed(data_dict, current_user):
    """
    Helper function to check if the email in data_dict differs from current user's email.

    Args:
        data_dict: Dictionary containing form data with email field
        current_user: Current logged in user object

    Returns:
        bool: True if email has changed, False otherwise
    """
    if not data_dict or not current_user:
        return False

    new_email = data_dict.get('email', '').strip()
    current_email = getattr(current_user, 'email', '').strip()

    return new_email != current_email

def should_show_update_button_in_user_profile(data_dict):
    """
    Καθορίζει αν πρέπει να εμφανιστούν τα κουμπιά διαχείρισης στο edit profile.

    Λογική:
    - Αν το email δεν έχει αλλάξει, εμφανίζονται τα κουμπιά
    - Αν το email έχει αλλάξει, κρύβονται τα κουμπιά

    Args:
        data_dict: Λεξικό με τα δεδομένα της φόρμας

    Returns:
        bool: True αν πρέπει να εμφανιστούν τα κουμπιά διαχείρισης
    """

    # Έλεγχος αν το internal login είναι απενεργοποιημένο
    try:
        # Κλήση του helper από το keycloak plugin
        if toolkit.h.enable_internal_login():
            return True  # Εμφάνισε πάντα τα κουμπιά αν υπάρχει internal login
    except (AttributeError, KeyError):
        # Το keycloak plugin δεν είναι εγκατεστημένο ή ο helper δεν είναι διαθέσιμος
        pass

    # Λήψη του τρέχοντος συνδεδεμένου χρήστη
    current_user = cast(Union["Model.User", "Model.AnonymousUser"], _cu)

    # If email hasn't changed, show buttons
    # Η λογική έχει αντληθεί από το main ckan, δες ckan/common.py
    if not is_email_changed(data_dict, current_user):
        return True

    # Hide buttons if email changed
    return False

def is_url_field(field_name, value):
    """
    Ελέγχει αν ένα πεδίο πρέπει να εμφανίζεται ως URL.
    """
    url_fields = ['applicable_legislation', 'endpoint_description', 'endpoint_url', 'documentation']

    if field_name in url_fields and isinstance(value, str) and value.startswith('http'):
        return True
    return False

# ---------------------------------------------------------------------------------------

def _parse_csv_config(value: str) -> set[str]:
    if not value:
        return set()
    return {
        part.strip().upper()
        for part in str(value).split(",")
        if part.strip()
    }

def harvest_frequencies():
    from ckanext.harvest.model import UPDATE_FREQUENCIES

    excluded = _parse_csv_config(
        toolkit.config.get("ckanext.data_gov_gr.harvest.frequency_exclude", "")
    )

    freqs = [f for f in UPDATE_FREQUENCIES if f.upper() not in excluded]
    return [{"text": toolkit._(f.title()), "value": f} for f in freqs]

# ---------------------------------------------------------------------------------------

def noindex_nofollow_enabled():
    """Check if noindex/nofollow meta tag is enabled via ckan.ini config."""
    return toolkit.asbool(
        toolkit.config.get('ckanext.data_gov_gr.meta.noindex_nofollow', False)
    )

# ---------------------------------------------------------------------------------------

def get_allowed_view_types(resource, package):
    allowed_view_types = core_helpers.get_allowed_view_types(resource, package)

    if resource.get("url_type") == "tabledesigner":
        return [
            option
            for option in allowed_view_types
            if option[0] != "tables_view"
        ]

    return allowed_view_types

# ---------------------------------------------------------------------------------------

def should_skip_tables_view_render(resource, resource_view):
    """Return true for tables_view previews that are known to break rendering."""
    if not resource_view or resource_view.get("view_type") != "tables_view":
        return False

    return resource.get("url_type") == "tabledesigner"

# ---------------------------------------------------------------------------------------

def rendered_resource_view(resource_view, resource, package, *args, **kwargs):
    if should_skip_tables_view_render(resource, resource_view):
        return toolkit.literal(
            '<div class="data-viewer-info">'
            f'<p>{toolkit._("This resource view is not available for this resource.")}</p>'
            '</div>'
        )

    try:
        return core_helpers.rendered_resource_view(
            resource_view, resource, package, *args, **kwargs
        )
    except Exception:
        if resource_view and resource_view.get("view_type") == "tables_view":
            log.exception("Unable to render tables_view %s", resource_view.get("id"))
            return toolkit.literal(
                '<div class="data-viewer-info">'
                f'<p>{toolkit._("This resource view is not available for this resource.")}</p>'
                '</div>'
            )
        raise

# ---------------------------------------------------------------------------------------

def get_helpers():
    return {
        'noindex_nofollow_enabled': noindex_nofollow_enabled,
        "is_url_field": is_url_field,
        "get_allowed_view_types": get_allowed_view_types,
        "should_skip_tables_view_render": should_skip_tables_view_render,
        "rendered_resource_view": rendered_resource_view,
        "vocabulary_facet_item_label": vocabulary_facet_item_label,
        "vocabulary_facet_title": vocabulary_facet_title,
        "get_vocabulary_id_for_field": get_vocabulary_id_for_field,
        "google_analytics_snippet": google_analytics_snippet,
        'data_gov_gr_map_search_basemap': map_search_basemap_key,
        'decisions_menu_enabled': decisions_menu_enabled,
        "build_mqa_nav_icon": build_mqa_nav_icon,
        "fluent_language_is_required": fluent_language_is_required,
        "get_organizations_stats": get_organizations_stats,
        'get_access_rights_type': get_access_rights_type,
        'get_dataset_legislation_default': get_dataset_legislation_default,
        'get_resource_license_default': get_resource_license_default,
        'get_dataset_spatial_coverage_default': get_dataset_spatial_coverage_default,
        'get_dataset_temporal_coverage_default': get_dataset_temporal_coverage_default,
        'data_gov_gr_get_organizations': data_gov_gr_get_organizations,
        'get_data_service_guides_url': get_data_service_guides_url,
        'get_config_as_bool': get_config_as_bool,
        'get_config_value': get_config_value,
        'should_include_relationships_in_show': should_include_relationships_in_show,
        'get_powerbi_embed_url': get_powerbi_embed_url,
        'get_home_stats_tiles': get_home_stats_tiles,
        'get_home_datasets_vs_services': get_home_datasets_vs_services,
        'get_home_total_datasets': get_home_total_datasets,
        'count_home_dataset_resources': count_home_dataset_resources,
        'get_home_dataset_resources_snapshot': get_home_dataset_resources_snapshot,
        'get_home_showcases': get_home_showcases,
        'get_home_featured_dataset_views': get_home_featured_dataset_views,
        'get_available_showcases': get_available_showcases,
        'get_home_news_items': get_home_news_items,
        'get_home_reuse_stats': get_home_reuse_stats,
        'get_home_portal_numbers': get_home_portal_numbers,
        'get_stats_url': get_stats_url,
        'organization_index_stats': organization_index_stats,
        'organization_visit_sort_available': organization_visit_sort_available,
        'organization_visit_sort_enabled': organization_visit_sort_enabled,
        'organization_visit_sort_default_enabled': organization_visit_sort_default_enabled,
        'has_gitbook_pdf_export': has_gitbook_pdf_export,
        'humanize_entity_type': humanize_entity_type,
        'should_hide_mqa_tab': should_hide_mqa_tab,
        'should_disable_protected_data': should_disable_protected_data,
        'should_hide_azure_translation': should_hide_azure_translation,
        'should_show_decision_menu': should_show_decision_menu,
        'should_show_decision_button': should_show_decision_button,
        'allow_org_admins_public_decisions': allow_org_admins_public_decisions,
        'should_show_update_button_in_user_profile': should_show_update_button_in_user_profile,
        'get_dataset_menu_items': get_dataset_menu_items,
        'get_contact_gitbook_embed_items': get_contact_gitbook_embed_items,
        'extract_iframe_from_html': extract_iframe_from_html,
        'get_stat_data': get_stat_data,
        "harvest_frequencies": harvest_frequencies,
        'dump_json': dump_json,
    }
