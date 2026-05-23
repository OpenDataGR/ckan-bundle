from __future__ import annotations

from ckanext.spatial.interfaces import ISpatialHarvester
from .logic.harvest_mapping import (
    apply_theme_from_topiccategory,
    apply_frequency_from_resource_maintenance,
    ensure_applicable_legislation,
    apply_temporal_coverage_from_iso19139,
    apply_resource_rights_and_license_from_iso19139,
    apply_resource_rights_from_iso_use_constraints,
    cleanup_package_tags,
    apply_dcat_type_geospatial,
    apply_dataset_name_from_file_identifier,
    apply_default_dataset_fields_from_config,
    apply_default_resource_fields_from_config,
    apply_landing_page_from_file_identifier,
    apply_download_url_for_direct_downloads,
    insert_configured_wms_wfs_capabilities_resources,
    apply_resource_access_url_from_url,
    apply_resource_description_from_name,
    apply_resource_mimetype_from_distribution_format,
    apply_resource_format_from_iso19139,
    preserve_resource_ids_by_url,
    prepend_configured_wms_layer_resource,
    prepend_wms_preview_resource_from_online_resource,
    prepend_wms_preview_resources_from_wms_online_resources,
    should_skip_data_service_package,
    should_skip_dataset_when_title_matches_layer_name,
    should_skip_dataset_with_uuid_like_layer_identifier,
)

import logging
from typing import Dict, Any

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
import os
import sys

from ckan.common import config, request
from ckan import model
import requests
from urllib.parse import urlparse
import re
from sqlalchemy import or_

from ckanext.data_gov_gr import views, cli, organization_stats
from ckanext.data_gov_gr.logic import validators, actions, auth
from ckanext.data_gov_gr.logic.hvd_legislation import (
    DEFAULT_HVD_APPLICABLE_LEGISLATION,
    HVD_APPLICABLE_LEGISLATION_CONFIG,
    HVD_CATEGORY_NOTICE_URL_CONFIG,
)
import json

from ckanext.keycloak.helpers import enable_internal_login
from ckanext.dcat.interfaces import IDCATRDFHarvester

import ckan.logic as logic

plugin_dir = os.path.dirname(sys.modules[__name__].__file__)
import ckanext.data_gov_gr.helpers as helpers

log = logging.getLogger(__name__)

DEFAULT_DATASET_POPULARITY_SORT = 'views_recent desc'
DEFAULT_DATASET_RELEVANCE_SORT = 'score desc, metadata_modified desc'
DEFAULT_DATASET_POPULARITY_SORT_CONFIG = (
    'ckanext.data_gov_gr.search.default_popularity_sort.enabled'
)
DEFAULT_DATASET_POPULARITY_SORT_PACKAGE_TYPES = ('dataset', 'data-service')


def _positive_integer_or_default(default):
    def validator(value, context):
        if value is None or (hasattr(value, 'strip') and not value.strip()):
            return default

        return toolkit.get_validator('is_positive_integer')(value, context)

    return validator


class DataGovGrPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IConfigDeclaration)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IPackageController, inherit=True)
    plugins.implements(plugins.IResourceController, inherit=True)
    plugins.implements(plugins.ITranslation)
    plugins.implements(plugins.IActions)
    plugins.implements(plugins.IAuthFunctions)
    plugins.implements(plugins.IValidators)
    plugins.implements(plugins.IFacets)
    plugins.implements(plugins.IBlueprint)
    plugins.implements(IDCATRDFHarvester)
    plugins.implements(plugins.IClick)

    def _get_clean_license_id(self, license_uri_or_id):
        """
        Παίρνει ένα URI ή ID άδειας και επιστρέφει το "καθαρό" του ID.
        π.χ. 'http://.../AFL_3_0' -> 'AFL_3_0'
        π.χ. 'cc-by-4.0' -> 'cc-by-4.0'
        """
        if not license_uri_or_id or not isinstance(license_uri_or_id, str):
            return None

        # Αν είναι URI, παίρνουμε το τελευταίο μέρος
        if '/' in license_uri_or_id:
            return license_uri_or_id.split('/')[-1]

        # Αλλιώς, είναι ήδη καθαρό ID
        return license_uri_or_id

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, "templates")
        toolkit.add_public_directory(config_, "public")
        toolkit.add_resource("assets", "data_gov_gr")

        self._change_valid_name()

    def update_config_schema(self, schema):
        """
        Make the Power BI embed URL configurable from /ckan-admin/config.

        This defines runtime-editable configuration options for:
        - ``ckanext.data_gov_gr.powerbi_embed_url`` (Power BI)
        - ``ckanext.data_gov_gr.user_survey.url`` (user survey popup/link URL)
        - ``ckanext.data_gov_gr.showcase.intro_text`` (apps/showcases intro text)
        - ``ckanext.data_gov_gr.showcase.disclaimer`` (apps/showcases disclaimer)
        - ``ckanext.data_gov_gr.dataset.legislation.open`` (default applicable legislation for open datasets)
        - ``ckanext.data_gov_gr.dataset.legislation.protected`` (default applicable legislation for protected datasets)
        - ``ckanext.data_gov_gr.hvd.applicable_legislation.default`` (προεπιλεγμένη εφαρμοστέα νομοθεσία για HVD σύνολα/υπηρεσίες/πόρους)
        - ``ckanext.data_gov_gr.hvd.category_notice.url`` (σύνδεσμος για το ενημερωτικό κείμενο HVD category)
        - ``ckanext.data_gov_gr.dataset.show_metadata_license_disclaimer`` (show/hide metadata license disclaimer in dataset form)
        - ``ckanext.data_gov_gr.resource.license.default`` (default license URI for new resources on open datasets)
        - ``ckanext.data_gov_gr.dataset.spatial_coverage.default.*`` (προεπιλεγμένη χωρική κάλυψη για νέα datasets - παλιό/advanced σχήμα)
        - ``ckanext.data_gov_gr.dataset.spatial_coverage.default`` (απλή επιλογή προεπιλεγμένης χωρικής κάλυψης)
        - ``ckanext.data_gov_gr.home.reuse_stats.view_all_url`` (home reuse stats button URL)
        - ``guides_base_url`` (external guides base URL)
        - ``ckanext.data_gov_gr.contact.gitbook_embed_items`` (contact page GitBook dropdown items as JSON)
        - ``ckanext.data_gov_gr.pages.faq`` (CKAN Pages slug for the FAQ footer link)
        - ``ckanext.data_gov_gr.pages.accessibility_statement`` (CKAN Pages slug for the Accessibility footer link)
        which are independent from their fallback values in the ini file.

        Επιπλέον, ορίζει παραμετρικές επιλογές μενού για τα σύνολα δεδομένων:
        - ``ckanext.data_gov_gr.menu.dataset.items`` (JSON λίστα από αντικείμενα
          με πεδία ``label`` και ``query``)
        """
        ignore_missing = toolkit.get_validator('ignore_missing')
        unicode_safe = toolkit.get_validator('unicode_safe')
        boolean_validator = toolkit.get_validator('boolean_validator')
        geojson_max_features_validator = _positive_integer_or_default(500)
        geojson_max_coordinates_validator = _positive_integer_or_default(400000)

        schema.update({
            'ckanext.data_gov_gr.powerbi_embed_url': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.user_survey.url': [ignore_missing, unicode_safe],
            'ckanext.geonames.username': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.showcase.intro_text': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.showcase.disclaimer': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.dataset.legislation.open': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.dataset.legislation.protected': [ignore_missing, unicode_safe],
            HVD_APPLICABLE_LEGISLATION_CONFIG: [ignore_missing, unicode_safe],
            HVD_CATEGORY_NOTICE_URL_CONFIG: [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.dataset.show_metadata_license_disclaimer': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.dataset.redirect_to_resource_after_create': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.resource.license.default': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.dataset.spatial_coverage.default': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.dataset.spatial_coverage.default.geonames_id': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.dataset.spatial_coverage.default.text': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.dataset.spatial_coverage.default.lng': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.dataset.spatial_coverage.default.lat': [ignore_missing, unicode_safe],
            'guides_base_url': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.getting_started.url': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.api_guide.url': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.data_publishing_guide.url': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.quality_guide.url': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.contact.gitbook_embed_items': [ignore_missing, unicode_safe],
            'ckanext.contact.support_faq.enabled': [ignore_missing, boolean_validator],
            'ckanext.contact.guides_embed.enabled': [ignore_missing, boolean_validator],
            # Νέα, JSON παραμετρικές επιλογές για dropdown συνόλων δεδομένων
            'ckanext.data_gov_gr.menu.dataset.items': [ignore_missing, unicode_safe],
            # Ρυθμίσεις αρχικής σελίδας (στατιστικά, showcases)
            'ckanext.data_gov_gr.home.stats.item1': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.home.stats.item2': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.home.stats.item3': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.home.stats.item4': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.home.featured_dataset_views.ids': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.home.portal_numbers.enabled': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.home.reuse_stats.enabled': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.home.reuse_stats.view_all_url': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.home.registries.enabled': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.home.showcases.ids': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.botakis.enabled': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.header.secretariat_logo.enabled': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.header.dashboard_activity_count.enabled': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.footer.government_logo.enabled': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.footer.greece_2_nextgeneration_logo.enabled': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.activity_stream.dataset.restrict_visibility': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.footer.mindigital_logo_variant': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.pages.faq': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.pages.accessibility_statement': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.pages.cookies_policy': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.pages.privacy_policy': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.search.api_doc_url': [ignore_missing, unicode_safe],
            'ckanext.geoview.geojson.max_features': [ignore_missing, geojson_max_features_validator],
            'ckanext.geoview.geojson.max_coordinates': [ignore_missing, geojson_max_coordinates_validator],
            DEFAULT_DATASET_POPULARITY_SORT_CONFIG: [ignore_missing, boolean_validator],
            'ckanext.matomo.consent_mode': [ignore_missing, unicode_safe],
            'ckanext.data_gov_gr.header.logo_preset': [ignore_missing, unicode_safe],
            organization_stats.ORGANIZATION_VISITS_SORT_ENABLED_CONFIG: [ignore_missing, boolean_validator],
            organization_stats.ORGANIZATION_VISITS_SORT_DEFAULT_CONFIG: [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.gitbook.pdf_auto_print': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.gitbook.pdf_per_page_auto_print': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.gitbook.pdf_all_guides_panel.enabled': [ignore_missing, boolean_validator],
            'ckanext.data_gov_gr.gitbook.pdf_per_page_panel.enabled': [ignore_missing, boolean_validator],
        })

        return schema

    # IConfigDeclaration

    def declare_config_options(self, declaration, key):
        """
        Declare config options to avoid 'Option ... is not declared' warnings.

        These options are typically edited via /ckan-admin/config, not only via
        ckan.ini.
        """
        declaration.annotate("data.gov.gr (ckanext-data-gov-gr)")

        root = key.ckanext.data_gov_gr
        home = root.home
        config_ui = root.config_ui
        contact = root.contact
        data_service = root.data_service
        resource = root.resource
        dataset = root.dataset
        user = root.user
        geonames = key.ckanext.geonames

        declaration.declare(root.powerbi_embed_url, "").set_description(
            "Power BI embed URL (used on /stats/powerbi and home previews)."
        )
        declaration.declare(root.user_survey.url, "").set_description(
            "User survey URL (supports {locale} placeholder)."
        )
        declaration.declare(root.pages.terms_of_use, "").set_description(
            "CKAN Pages slug for the Terms of Use footer link."
        )
        declaration.declare(root.pages.accessibility_statement, "").set_description(
            "CKAN Pages slug for the Accessibility footer link."
        )
        declaration.declare(root.pages.faq, "").set_description(
            "CKAN Pages slug for the FAQ footer link."
        )
        declaration.declare(root.pages.cookies_policy, "").set_description(
            "CKAN Pages slug for the Cookies Policy footer link."
        )
        declaration.declare(root.pages.privacy_policy, "").set_description(
            "CKAN Pages slug for the Privacy Policy footer link."
        )
        declaration.declare(key.ckanext.matomo.consent_mode, "disabled").set_description(
            "Matomo consent mode: 'disabled', 'tracking_consent', 'cookie_consent', or 'opt_out'."
        )
        declaration.declare(root.search.api_doc_url, "").set_description(
            "Custom API documentation URL shown on the dataset search page (opens in new tab)."
        )
        declaration.declare(root.search.default_popularity_sort.enabled, "yes").set_description(
            "Use popularity (views_recent desc) as the default sort on the dataset search page."
        )
        declaration.declare(root.organization_index.visits_sort.enabled, "no").set_description(
            "Show organization index sort options based on profile visits."
        )
        declaration.declare(root.organization_index.visits_sort.default, "no").set_description(
            "Use profile visits descending as the default organization index sort."
        )
        declaration.declare(geonames.username, "").set_description(
            "GeoNames username used by geonames_search / geonames_get actions."
        )
        declaration.declare(root.showcase.intro_text, "").set_description(
            "Showcases intro text (HTML allowed)."
        )
        declaration.declare(root.showcase.disclaimer, "").set_description(
            "Showcases disclaimer text (HTML allowed)."
        )
        declaration.declare(
            root.activity_stream.dataset.restrict_visibility, "yes"
        ).set_description(
            "Restrict the dataset activity stream to sysadmins and organization admins."
        )
        declaration.declare(root.dataset.legislation.open, "").set_description(
            "Default applicable legislation URL for open datasets."
        )
        declaration.declare(root.dataset.legislation.protected, "").set_description(
            "Default applicable legislation URL for protected datasets."
        )
        declaration.declare(
            root.hvd.applicable_legislation.default,
            DEFAULT_HVD_APPLICABLE_LEGISLATION,
        ).set_description(
            "Προεπιλεγμένο URL εφαρμοστέας νομοθεσίας που εφαρμόζεται αυτόματα όταν επιλεγούν HVD κατηγορίες."
        )
        declaration.declare(root.hvd.category_notice.url, "").set_description(
            "URL για τον σύνδεσμο στο ενημερωτικό κείμενο των HVD κατηγοριών. Αν μείνει κενό, χρησιμοποιείται η HVD εφαρμοστέα νομοθεσία."
        )
        declaration.declare(dataset.show_metadata_license_disclaimer, "no").set_description(
            "Show/hide the metadata license disclaimer text in dataset create/edit forms."
        )
        declaration.declare(dataset.redirect_to_resource_after_create, "no").set_description(
            "Redirect users to the new resource form after creating a dataset from the UI. Applies only to the 'dataset' package type."
        )
        declaration.declare(resource.license.default, "").set_description(
            "Προεπιλεγμένο URI άδειας για νέους πόρους σε ανοικτά datasets (access_rights που καταλήγει σε /PUBLIC)."
        )
        declaration.declare(dataset.spatial_coverage.default, "").set_description(
            "Προεπιλεγμένη χωρική κάλυψη για νέα datasets. Τιμές: 'greece' ή κενό (απενεργοποίηση)."
        )
        declaration.declare(dataset.spatial_coverage.default.geonames_id, "").set_description(
            "Προεπιλεγμένο GeoNames ID για spatial_coverage (π.χ. 390903 για Ελλάδα). Κενό = απενεργοποίηση."
        )
        declaration.declare(dataset.spatial_coverage.default.text, "").set_description(
            "Προεπιλεγμένη ετικέτα (label) για spatial_coverage (π.χ. Greece)."
        )
        declaration.declare(dataset.spatial_coverage.default.lng, "").set_description(
            "Προεπιλεγμένο longitude (lng) για centroid/geom στο spatial_coverage (π.χ. 22)."
        )
        declaration.declare(dataset.spatial_coverage.default.lat, "").set_description(
            "Προεπιλεγμένο latitude (lat) για centroid/geom στο spatial_coverage (π.χ. 39)."
        )
        declaration.declare(root.menu.dataset.items, "").set_description(
            "JSON list for the dataset dropdown menu items."
        )
        declaration.declare(key.guides_base_url, "").set_description(
            "External guides base URL (e.g. GitBook /guides)."
        )
        declaration.declare(root.getting_started.url, "https://data-gov-gr.gitbook.io/guides/grigoroi-odigoi").set_description(
            "Home page: getting started guide URL."
        )
        declaration.declare(root.api_guide.url, "https://data-gov-gr.gitbook.io/guides/texnika-egxeiridia/data.gov.gr/metadedomena/tekmiriosi-api").set_description(
            "Home page: API documentation guide URL."
        )
        declaration.declare(root.data_publishing_guide.url, "https://data-gov-gr.gitbook.io/guides/diaxeirisi-dedomenon/synola-dedomenon/dimioyrgia-synoloy-dedomenon").set_description(
            "Home page: data publishing guide URL."
        )
        declaration.declare(root.quality_guide.url, "https://data-gov-gr.gitbook.io/guides/xrisi-dedomenon/synola-dedomenon/aksiologisi-poiotitas-metadedomenon/kritiria-aksiologisis-mqa").set_description(
            "Home page: data quality guide URL."
        )
        declaration.declare(key.ckanext.contact.support_faq.enabled, False).set_description(
            "Show the FAQ (GitBook embed) section on the contact/support page."
        )
        declaration.declare(root.gitbook.pdf_auto_print, False).set_description(
            "Auto-trigger the browser print dialog when opening the GitBook PDF page."
        )
        declaration.declare(root.gitbook.pages_cache_ttl, 86400).set_description(
            "Redis cache TTL (seconds) for the GitBook pages list used in per-section PDF download. Default: 86400 (1 day)."
        )
        declaration.declare(root.gitbook.pdf_per_page_auto_print, True).set_description(
            "Auto-trigger the browser print dialog when downloading a single-section GitBook PDF."
        )
        declaration.declare(root.gitbook.pdf_per_page_print_delay_ms, 0).set_description(
            "Delay in milliseconds before the print dialog opens for single-section PDF. 0 = immediate."
        )
        declaration.declare(root.gitbook.pdf_all_guides_panel.enabled, True).set_description(
            "Show/hide the 'Download all guides (PDF)' panel on the /more page."
        )
        declaration.declare(root.gitbook.pdf_per_page_panel.enabled, True).set_description(
            "Show/hide the 'Download guide by section' panel on the /more page."
        )
        declaration.declare(key.ckanext.contact.guides_embed.enabled, True).set_description(
            "Show the guides iframe embed section on the contact/support page."
        )
        declaration.declare(contact.gitbook_embed_items, json.dumps([
            {
                "title": "Συχνές ερωτήσεις (Όλες)",
                "url": "https://data-gov-gr.gitbook.io/guides/syxnes-erotiseis",
            },
            {
                "title": "Γενικά",
                "url": "https://data-gov-gr.gitbook.io/guides/syxnes-erotiseis/genika",
            },
            {
                "title": "Οργανισμοί Δημόσιου Τομέα",
                "url": "https://data-gov-gr.gitbook.io/guides/syxnes-erotiseis/foreis-dimosioy-tomea",
            },
            {
                "title": "Πολίτες & Επιχειρήσεις",
                "url": "https://data-gov-gr.gitbook.io/guides/syxnes-erotiseis/polites-and-epixeiriseis",
            },
            {
                "title": "Τεχνικά θέματα & API",
                "url": "https://data-gov-gr.gitbook.io/guides/syxnes-erotiseis/texnika-themata-and-api",
            },
            {
                "title": "Dataspace, αλτρουιστές και διαμεσολαβητές",
                "url": "https://data-gov-gr.gitbook.io/guides/syxnes-erotiseis/dataspace-altroyistes-kai-diamesolavites",
            },
        ], ensure_ascii=False)).set_description(
            "Contact page GitBook dropdown items as JSON list."
        )

        declaration.annotate("Home page configuration")
        declaration.declare(home.portal_numbers.enabled, "yes").set_description(
            "Show the 'Portal in numbers' counters on the home page."
        )
        declaration.declare(home.reuse_stats.enabled, "yes").set_description(
            "Show the 'Reuse statistics' section (Matomo visitors/downloads + apps count) on the home page."
        )
        declaration.declare(home.reuse_stats.view_all_url, "").set_description(
            "Custom URL for the home reuse stats 'View Statistics' button."
        )
        declaration.declare(home.registries.enabled, "yes").set_description(
            "Show links to registries on the home page."
        )
        declaration.declare(home.stats.item1, "").set_description(
            "Home stats tile 1 (stats id)."
        )
        declaration.declare(home.stats.item2, "").set_description(
            "Home stats tile 2 (stats id)."
        )
        declaration.declare(home.stats.item3, "").set_description(
            "Home stats tile 3 (stats id)."
        )
        declaration.declare(home.stats.item4, "").set_description(
            "Home stats tile 4 (stats id)."
        )
        declaration.declare(home.featured_dataset_views.ids, "").set_description(
            "Selected dataset resource view IDs (one per line, up to 6) for the home page."
        )
        declaration.declare(home.showcases.ids, "").set_description(
            "Selected showcases IDs (one per line, up to 4) for the home page."
        )

        declaration.declare(root.botakis.enabled, "no").set_description(
            "Enable/disable the Botakis webchat widget."
        )
        declaration.declare(root.header.secretariat_logo.enabled, "no").set_description(
            "Show the AI Data Governance Secretariat logo in the header, next to the site logo."
        )
        declaration.declare(root.header.logo_preset, "white-gradient-blue-trimmed-transparent.png").set_description(
            "Preset logo filename from /images/data-gov-gr/ shown in the header when ckan.site_logo is not set."
        )
        declaration.declare(root.header.dashboard_activity_count.enabled, "no").set_description(
            "Calculate the dashboard activity notification count in the header. Disabled by default to avoid per-page activity queries for logged-in users."
        )
        declaration.declare(root.config_ui.dashboard_activity_count.enabled, "no").set_description(
            "Show the dashboard activity notification count checkbox in /ckan-admin/config. Ini-only; hidden by default."
        )
        declaration.declare(root.footer.government_logo.enabled, "yes").set_description(
            "Show the government logo (gov.gr) in the footer, to the left of the ministry logo."
        )
        declaration.declare(root.footer.greece_2_nextgeneration_logo.enabled, "yes").set_description(
            "Show the Greece 2.0 NextGenerationEU logo in the footer, after the government and ministry logos."
        )
        declaration.declare(root.footer.mindigital_logo_variant, "light").set_description(
            "Footer Mindigital logo variant: 'light' (ανοιχτή απόχρωση μπλε) or 'dark' (σκοτεινή απόχρωση μπλε)."
        )

        declaration.annotate("Dataset / data-service view")
        declaration.declare(data_service.hide_resources_section, "yes").set_description(
            "Hide 'Data and Resources' section on data-service (API) pages."
        )
        declaration.declare(user.hide_showcase_tab, "no").set_description(
            "Hide the 'Showcases' tab from the user dashboard."
        )

        declaration.annotate("Config UI visibility (ini-only feature flags)")
        declaration.declare(config_ui.stats_powerbi.enabled, "no").set_description(
            "Show 'Στατιστικά και Power BI' section in /ckan-admin/config."
        )
        declaration.declare(config_ui.home_stats.enabled, "no").set_description(
            "Show 'Στατιστικά αρχικής σελίδας' section in /ckan-admin/config."
        )
        declaration.declare(config_ui.home_featured_datasets.enabled, "no").set_description(
            "Show 'Επιλεγμένα datasets στην αρχική σελίδα' section in /ckan-admin/config."
        )
        declaration.declare(config_ui.home_showcases.enabled, "no").set_description(
            "Show 'Επαναχρήσεις στην αρχική σελίδα' section in /ckan-admin/config."
        )
        declaration.declare(config_ui.dataset_menu.enabled, "no").set_description(
            "Show 'Μενού Συνόλων Δεδομένων (Dropdown)' section in /ckan-admin/config."
        )
        declaration.declare(config_ui.guides.enabled, "no").set_description(
            "Show 'Οδηγοί (GitBook)' section in /ckan-admin/config."
        )

    # IBlueprint

    def get_blueprint(self):
        return views.get_blueprint()

    # IClick

    def get_commands(self):
        return cli.get_commands()

    # IDCATRDFHarvester

    def before_download(self, url, harvest_job):
        """
        Pass-through hook before downloading the remote RDF/JSON-LD document.
        We don't modify the URL at this stage.
        """
        return url, []

    def update_session(self, session):
        from ckanext.data_gov_gr.harvesters.custom_dcat_harvester import harvest_local
        import logging
        log = logging.getLogger(__name__)
        user_agent = getattr(harvest_local, 'user_agent', None)
        if user_agent:
            session.headers.update({'User-Agent': str(user_agent)})
        log.debug("[HARVESTER] Session headers: %s", dict(session.headers))
        return session

    def after_download(self, content, harvest_job):
        """
        Tweak JSON-LD feeds so that `accessUrl` keys are normalised to
        `accessURL`, which is what the DCAT parser expects to map to
        dcat:accessURL.
        """
        if not content:
            return content, []

        try:
            if '"accessUrl"' in content:
                content = content.replace('"accessUrl"', '"accessURL"')
        except Exception:
            # In case of non-text content, just leave it untouched
            pass

        return content, []

    def after_parsing(self, rdf_parser, harvest_job):
        """
        No-op hook after the RDF/JSON-LD content has been parsed into a graph.
        """
        return rdf_parser, []

    def after_update(self, harvest_object, dataset_dict, temp_dict):
        """
        No-op hook after package_update.
        """
        return None

    def after_create(self, harvest_object, dataset_dict, temp_dict):
        """
        No-op hook after package_create.
        """
        return None

    def update_package_schema_for_create(self, package_schema):
        """
        Leave the package schema unchanged on create.
        """
        return package_schema

    def update_package_schema_for_update(self, package_schema):
        """
        Leave the package schema unchanged on update.
        """
        return package_schema

    # ΙValidators
    def get_validators(self) -> Dict[str, Any]:
        return validators.get_validators()

    # ITemplateHelpers

    def get_helpers(self):
        return helpers.get_helpers()

    # IPackageController
    def before_index(self, pkg_dict):
        """
        Προσθέτουμε το 'publishertype' από τον συνδεδεμένο οργανισμό.
        Σημείωση: Δεν παραλείπουμε τα data-service ώστε να υπάρχει διαθέσιμο
        το πεδίο για φιλτράρισμα στο ευρετήριο υπηρεσιών.
        """
        # Skip processing only for decisions
        if pkg_dict.get('type') in ['decision']:
            return pkg_dict

        org_id = pkg_dict.get('owner_org')
        if org_id:
            try:
                org = model.Group.get(org_id)
                if org and org.is_organization:
                    publisher_type_value = org.extras.get('publishertype')
                    if publisher_type_value:
                        pkg_dict['publishertype'] = publisher_type_value
            except Exception:
                pass  # Αγνοούμε τυχόν σφάλματα για να μην σπάσει το indexing

        return pkg_dict

    # IResourceController

    def _should_skip_size_default(self, resource_dict: Dict[str, Any]) -> bool:
        """
        Επιστρέφει True όταν *δεν* πρέπει να μπει default μέγεθος.

        Στόχος: να μην «πατήσουμε» το πραγματικό μέγεθος κατά την ανάρτηση αρχείου
        (upload), όπου το CKAN συμπληρώνει αυτόματα το size.
        """
        if resource_dict.get('upload'):
            return True
        url_type = resource_dict.get('url_type')
        if isinstance(url_type, str) and url_type.strip().lower() == 'upload':
            return True
        return False

    def _ensure_resource_size(self, resource_dict: Dict[str, Any]) -> None:
        """
        Αν ο πόρος δεν έχει size, τότε θέτει size=1.

        Χρησιμοποιείται μόνο για πόρους χωρίς ανάρτηση αρχείου, όπου διαφορετικά
        το size μένει κενό/None.
        """
        if self._should_skip_size_default(resource_dict):
            return

        size = resource_dict.get('size', None)
        if size in (None, '', [], {}):
            resource_dict['size'] = 1
            return

        try:
            # Σε μερικές ροές το size μπορεί να έρθει ως string.
            size_int = int(size)
        except Exception:
            resource_dict['size'] = 1
            return

        if size_int <= 0:
            resource_dict['size'] = 1

    def before_resource_create(self, context: Dict[str, Any], resource_dict: Dict[str, Any]) -> None:
        self._ensure_resource_size(resource_dict)

    def before_resource_update(
        self,
        context: Dict[str, Any],
        current: Dict[str, Any],
        resource_dict: Dict[str, Any],
    ) -> None:
        # Στο resource_update, αν λείπει το `size`, κινδυνεύει να «χαθεί» η
        # υπάρχουσα τιμή, επειδή το action αντικαθιστά ολόκληρο το resource dict.
        # Άρα:
        # - αν υπάρχει ήδη size, το διατηρούμε
        # - αν δεν υπάρχει, αφήνουμε τον μηχανισμό default να βάλει 1
        if 'size' not in resource_dict:
            current_size = current.get('size', None)
            if current_size not in (None, '', [], {}):
                resource_dict['size'] = current_size

        self._ensure_resource_size(resource_dict)

    def before_dataset_search(self, data_dict):
        if self._should_apply_default_relevance_sort(data_dict):
            data_dict['sort'] = self._default_relevance_sort()
        elif self._should_apply_default_popularity_sort(data_dict):
            data_dict['sort'] = DEFAULT_DATASET_POPULARITY_SORT

        # Αναζητούμε το χωρικό φίλτρο 'ext_bbox' στο αρχικό dictionary που έρχεται από το request.
        # Το φίλτρο αυτό αναμένεται να είναι μια συμβολοσειρά τεσσάρων δεκαδικών τιμών: minLon, minLat, maxLon, maxLat (π.χ. "24.1,35.2,25.9,36.1")
        ext_bbox_value = data_dict.get('ext_bbox')

        # Αν υπάρχει αυτό το φίλτρο, συνεχίζουμε
        if ext_bbox_value:

            # Μεταφέρουμε το 'ext_bbox' στα 'extras' ώστε να είναι συμβατό με το πώς CKAN χειρίζεται επιπλέον παραμέτρους.
            # Χρησιμοποιούμε setdefault για να δημιουργήσουμε το 'extras' αν δεν υπάρχει ήδη.
            data_dict.setdefault('extras', {})['ext_bbox'] = ext_bbox_value

            # Αφαιρούμε το αρχικό πεδίο από το root για να αποφύγουμε συγκρούσεις ή warnings
            data_dict.pop('ext_bbox', None)

            try:
                # Διαχωρίζουμε τις τιμές της συμβολοσειράς και τις μετατρέπουμε σε float
                minLng, minLat, maxLng, maxLat = map(float, ext_bbox_value.split(','))

                # Δημιουργούμε το φίλτρο αναζήτησης (FQ) για το Solr, με βάση τα όρια bounding box.
                # Η σύνταξη τύπου: minx:[* TO maxLng] AND maxx:[minLng TO *] εξασφαλίζει ότι η γεωμετρία του dataset, τέμνει το ορθογώνιο του χάρτη (δηλ. υπάρχει κάποια επικάλυψη).
                bbox_fq = (
                    f"(minx:[* TO {maxLng}] AND maxx:[{minLng} TO *] "
                    f"AND miny:[* TO {maxLat}] AND maxy:[{minLat} TO *])"
                )

                # Αν υπάρχει ήδη φίλτρο fq (π.χ. φίλτρο από οργανισμό ή κατηγορία), το συνδυάζουμε με AND
                if data_dict.get('fq'):
                    data_dict['fq'] = f"({data_dict['fq']}) AND {bbox_fq}"
                else:
                    # Διαφορετικά, το bbox φίλτρο είναι το μόνο
                    data_dict['fq'] = bbox_fq

            except Exception as e:
                # Αν υπάρξει σφάλμα (π.χ. κακό format στη συμβολοσειρά), το καταγράφουμε στο log
                log.warning(f"Invalid ext_bbox format in plugin: {ext_bbox_value} - {e}")

        # Επιστρέφουμε το τροποποιημένο data_dict ώστε να συνεχιστεί η αναζήτηση με τα νέα φίλτρα
        return data_dict

    def _should_apply_default_relevance_sort(self, data_dict):
        if not helpers.get_config_as_bool(
            DEFAULT_DATASET_POPULARITY_SORT_CONFIG,
            default=True,
        ):
            return False

        if not self._is_supported_search_endpoint():
            return False

        query = data_dict.get('q')
        if not (isinstance(query, str) and query.strip()):
            return False

        return data_dict.get('sort') in (None, '')

    def _default_relevance_sort(self):
        return (
            config.get('ckan.search.default_package_sort')
            or DEFAULT_DATASET_RELEVANCE_SORT
        )

    def _should_apply_default_popularity_sort(self, data_dict):
        if data_dict.get('sort') not in (None, ''):
            return False

        if not helpers.get_config_as_bool(
            DEFAULT_DATASET_POPULARITY_SORT_CONFIG,
            default=True,
        ):
            return False

        if not self._is_supported_search_endpoint():
            return False

        try:
            request_args = request.args
        except RuntimeError:
            return False

        if self._has_search_or_filter_params(request_args):
            return False

        return True

    def _is_supported_search_endpoint(self):
        try:
            endpoint = request.endpoint
            view_args = request.view_args or {}
        except RuntimeError:
            return False

        package_type = view_args.get('package_type', 'dataset')
        return (
            package_type in DEFAULT_DATASET_POPULARITY_SORT_PACKAGE_TYPES
            and endpoint == f'{package_type}.search'
        )

    def _has_search_or_filter_params(self, request_args):
        for param, value in request_args.items(multi=True):
            if param in ('page', 'sort') or param.startswith('_'):
                continue
            if isinstance(value, str):
                if not value.strip():
                    continue
            elif value is None:
                continue
            return True
        return False

    def before_dataset_index(self, pkg_dict):
        """
        Εμπλουτισμός πεδίων για το ευρετήριο ανά τύπο πακέτου.
        - dataset: is_hvd, is_nsip, publishertype, resource extras
        - data-service: is_hvd, publishertype
        - decision: καμία επέμβαση
        """
        # Deduplicate res_license to prevent Solr 32KB limit overflow
        # Keep only unique values instead of repeating for each resource
        if 'res_license' in pkg_dict:
            res_license = pkg_dict['res_license']
            if isinstance(res_license, list):
                # Keep only unique values
                unique_licenses = list(set(res_license))
                pkg_dict['res_license'] = unique_licenses
            elif isinstance(res_license, str) and len(res_license) > 30000:
                # If it's already a huge string, take just the first license
                pkg_dict['res_license'] = res_license[:500]

        pkg_type = pkg_dict.get('type')

        # Καμία επέμβαση για αποφάσεις
        if pkg_type == 'decision':
            return pkg_dict

        # Publishertype από τον οργανισμό (dataset + data-service)
        try:
            org_id = pkg_dict.get('owner_org')
            if org_id:
                org = model.Group.get(org_id)
                if org and org.is_organization:
                    publisher_type_value = org.extras.get('publishertype')
                    if publisher_type_value:
                        if not publisher_type_value.startswith('http://'):
                            publisher_type_value = f'http://purl.org/adms/publishertype/{publisher_type_value}'
                        pkg_dict['publishertype'] = publisher_type_value
        except Exception as e:
            log.debug(f"Could not get org extras for {org_id}: {e}")

        # is_hvd (dataset + data-service)
        pkg_dict['is_hvd'] = 'No'
        if pkg_dict.get('hvd_category'):
            hvd_category_array_size = 0
            try:
                hvd_category_array = json.loads(pkg_dict['hvd_category'])
                hvd_category_array_size = len(hvd_category_array)
            except Exception as e:
                log.error(f"Unexpected error while processing hvd_category: {e}")
            if hvd_category_array_size > 0:
                pkg_dict['is_hvd'] = 'Yes'

        # is_nsip + resource extras μόνο για datasets
        if pkg_type == 'dataset':
            access_rights_value = pkg_dict.get('access_rights', '')
            if isinstance(access_rights_value, str):
                if access_rights_value.endswith('/NON_PUBLIC') or access_rights_value.endswith('/RESTRICTED'):
                    pkg_dict['is_nsip'] = 'Yes'
                elif access_rights_value.endswith('/PUBLIC'):
                    pkg_dict['is_nsip'] = 'No'

            extra_resource_fields = model.Resource.get_extra_columns()
            for field in extra_resource_fields:
                res_extras_key = f'res_extras_{field}'
                if res_extras_key not in pkg_dict:
                    continue

                values = pkg_dict[res_extras_key]
                if not values:
                    continue

                # Special handling for license: index all unique values in a bounded string for Solr
                if field == 'license':
                    # Flatten nested lists/tuples just in case
                    items = []
                    if isinstance(values, (list, tuple)):
                        for v in values:
                            if isinstance(v, (list, tuple)):
                                items.extend(v)
                            else:
                                items.append(v)
                    else:
                        items = [values]

                    cleaned = []
                    seen = set()
                    for item in items:
                        if item is None:
                            continue
                        s = str(item).strip()
                        if not s:
                            continue
                        key = s.lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        cleaned.append(s)

                    if cleaned:
                        # Δημιουργούμε string τύπου Python list, ώστε τα υπάρχοντα
                        # patterns αναζήτησης (π.χ. *ID'*) να συνεχίσουν να δουλεύουν.
                        res_license_value = "['" + "', '".join(cleaned) + "']"
                        max_len = 30000  # με ασφάλεια κάτω από το όριο 32KB του Solr
                        if len(res_license_value) > max_len:
                            log.warning(
                                "Truncating res_license for %s from %d to %d chars (too many unique licences)",
                                pkg_dict.get('name'),
                                len(res_license_value),
                                max_len,
                            )
                            res_license_value = res_license_value[:max_len]

                        pkg_dict['res_license'] = res_license_value
                    else:
                        pkg_dict.pop('res_license', None)
                else:
                    pkg_dict[f'res_{field}'] = str(values)

        return pkg_dict

    def _extract_publisher_name(self, publisher_value):
        """
        Επιστρέφει το πρώτο διαθέσιμο publisher name από search result payload.
        """
        if isinstance(publisher_value, list):
            for item in publisher_value:
                if isinstance(item, dict):
                    name = (item.get('name') or '').strip()
                    if name:
                        return name
        elif isinstance(publisher_value, dict):
            name = (publisher_value.get('name') or '').strip()
            if name:
                return name
        elif isinstance(publisher_value, str):
            publisher_name = publisher_value.strip()
            if publisher_name:
                return publisher_name
        return ''

    def _extract_organization_name(self, organization_value):
        """
        Επιστρέφει το organization name από search result payload.
        """
        if isinstance(organization_value, dict):
            organization_name = (organization_value.get('name') or '').strip()
            if organization_name:
                return organization_name
        elif isinstance(organization_value, str):
            organization_name = organization_value.strip()
            if organization_name:
                return organization_name
        return ''

    def after_dataset_search(self, search_results, search_params):
        """
        Εμπλουτίζει τα search results με human-friendly organization metadata
        για χρήση στα dataset/data-service cards του index.
        """
        results = search_results.get('results') or []
        if not results:
            return search_results

        owner_org_ids = set()
        organization_names = set()
        publisher_names = set()
        organization_names_by_result_index = {}
        publisher_names_by_result_index = {}

        for index, result in enumerate(results):
            if not isinstance(result, dict):
                continue

            result.pop('organization_card', None)

            owner_org = result.get('owner_org')
            if owner_org:
                owner_org_ids.add(owner_org)

            organization_name = self._extract_organization_name(result.get('organization'))
            organization_names_by_result_index[index] = organization_name
            if organization_name:
                organization_names.add(organization_name)

            publisher_name = self._extract_publisher_name(result.get('publisher'))
            publisher_names_by_result_index[index] = publisher_name
            if publisher_name:
                publisher_names.add(publisher_name)

        if not owner_org_ids and not organization_names and not publisher_names:
            return search_results

        query = model.Session.query(model.Group).filter(
            model.Group.state == 'active',
            model.Group.is_organization.is_(True),
        )

        filters = []
        if owner_org_ids:
            filters.append(model.Group.id.in_(owner_org_ids))
        if organization_names:
            filters.append(model.Group.name.in_(organization_names))
        if publisher_names:
            filters.append(model.Group.title.in_(publisher_names))

        if not filters:
            return search_results

        organizations = query.filter(or_(*filters)).all()
        organizations_by_id = {organization.id: organization for organization in organizations}
        organizations_by_name = {organization.name: organization for organization in organizations}

        organizations_by_title = {}
        ambiguous_titles = set()
        for organization in organizations:
            title = (organization.title or '').strip()
            if not title:
                continue
            if title in organizations_by_title:
                ambiguous_titles.add(title)
                continue
            organizations_by_title[title] = organization

        for ambiguous_title in ambiguous_titles:
            organizations_by_title.pop(ambiguous_title, None)

        for index, result in enumerate(results):
            if not isinstance(result, dict):
                continue

            owner_org = result.get('owner_org')
            organization_name = organization_names_by_result_index.get(index, '')
            publisher_name = publisher_names_by_result_index.get(index, '')

            organization = None
            if owner_org:
                organization = organizations_by_id.get(owner_org)
            if organization is None and organization_name:
                organization = organizations_by_name.get(organization_name)
            if organization is None and publisher_name:
                organization = organizations_by_title.get(publisher_name)

            if organization is not None:
                organization_title = (
                    (organization.title or '').strip()
                    or (organization.name or '').strip()
                    or publisher_name
                )
                if organization_title:
                    result['organization_card'] = {
                        'title': organization_title,
                        'name': organization.name,
                        'type': organization.type or 'organization',
                        'is_linkable': True,
                    }
                continue

            if publisher_name:
                result['organization_card'] = {
                    'title': publisher_name,
                    'name': None,
                    'is_linkable': False,
                }

        return search_results

    def _extract_label_from_uri(self, uri):
        """Εξάγει το τελευταίο μέρος του URI για καλύτερη αναζήτηση"""
        if uri and isinstance(uri, str) and '/' in uri:
            # Παίρνουμε το τελευταίο μέρος του URI (πχ. 'PublicInstitution' από το 'http://purl.org/adms/publishertype/PublicInstitution')
            label = uri.split('/')[-1]

            # Μετατρέπουμε το camelCase σε λέξεις με κενά για καλύτερη αναγνωσιμότητα
            # π.χ. 'PublicInstitution' -> 'Public Institution'
            label = re.sub(r'([a-z])([A-Z])', r'\1 \2', label)
            return label
        return uri

    # IFacets

    def dataset_facets(self, facets_dict, package_type):
        """
        Προσθέτει τα facets που θέλουμε να εμφανίζονται στην αναζήτηση datasets.
        """
        # Αφαιρούμε το facet "groups"
        if 'groups' in facets_dict:
            del facets_dict['groups']

        # Προσθέτουμε τα facets που θέλουμε
        if package_type == 'dataset':
            facets_dict['is_hvd'] = toolkit._('High-Value Dataset')
            if not helpers.should_disable_protected_data():
                facets_dict['is_nsip'] = toolkit._('Protected Dataset')
            else:
                facets_dict.pop('is_nsip', None)
            facets_dict['publishertype'] = toolkit._('Organization Type')

        elif package_type == 'data-service':
            facets_dict.pop('frequency', None)
            facets_dict.pop('res_format', None)
            facets_dict.pop('is_nsip', None)

        elif package_type == 'decision':
            facets_dict.pop('is_hvd',None)
            facets_dict.pop('publishertype',None)
            facets_dict.pop('access_rights',None)
            facets_dict.pop('frequency', None)
            facets_dict.pop('res_format', None)
            facets_dict.pop('is_nsip', None)

        return facets_dict

    def organization_facets(self, facets, group_type, extra_param):
        """
        Προσθέτει τα facets που θέλουμε να εμφανίζονται στην αναζήτηση organization pages.
        Εφαρμόζει τις ίδιες προσαρμογές με τα dataset facets για συνέπεια.
        """
        # Αφαιρούμε το facet "groups"
        if 'groups' in facets:
            del facets['groups']

        # Προσθέτουμε τα ίδια facets όπως στα datasets
        if not helpers.should_hide_mqa_tab():
            facets['qa_mqa_rating'] = toolkit._('Metadata quality')

        # Only add openness score facet for datasets, not for decisions or data-services
        # Since organization pages show all package types, we need to check if we're filtering by decisions or data-services
        request_path = request.environ.get('PATH_INFO', '')
        if 'decision' not in request_path and 'data-service' not in request_path:
            facets['qa_openness_score'] = toolkit._('Openness score')

        if not helpers.should_disable_protected_data():
            facets['is_nsip'] = toolkit._('Protected Dataset')
        else:
            facets.pop('is_nsip', None)

        return facets

    #ITranslation
    def i18n_directory(self):
        return os.path.join(plugin_dir, 'i18n')

    def i18n_domain(self):
        return 'ckanext-data_gov_gr'

    def i18n_locales(self):
        return ['el', 'en', 'fr']

    # Implement IAuthFunctions
    def get_auth_functions(self):
        return {
            'check_user_org_permission': auth.check_user_org_permission,
            'user_organization_capacity': auth.user_organization_capacity_auth,
            'user_reset': auth.user_reset_override,
            'organization_list_with_user_extras': auth.organization_list_with_user_extras_auth,
            'package_activity_list': auth.package_activity_list,
            'organization_activity_list': auth.organization_activity_list,
        }

    # IActions
    def get_actions(self):
        exposed_actions = {
            'check_user_org_permission': actions.check_user_org_permission,
            'organization_list_with_user_extras': actions.organization_list_with_user_extras,
            'user_organization_capacity': actions.user_organization_capacity,
            'user_delete': actions.user_delete,
            "organization_list": actions.organization_list,
            'geonames_search': self.geonames_search_action,  # Κλήση για ανάκτηση αποτελεσμάτων σε geoname
            'geonames_get': self.geonames_get_action,
            # Προσυμπλήρωση access_url / download_url κατά το save πόρου (chained actions)
            'package_create': actions.package_create,
            'package_update': actions.package_update,
            'resource_create': actions.resource_create,
            'resource_update': actions.resource_update,
        }

        if not enable_internal_login():

            # Ανάγνωση παραμέτρου από ckan.ini για την επιλογή μεθόδου user_invite
            user_invite_method = config.get('ckanext.data_gov_gr.user_invite_method', 'notify')

            if user_invite_method == 'notify':
                exposed_actions['user_invite'] = actions.user_invite_notify
            elif user_invite_method == 'waiting_keycloak':
                exposed_actions['user_invite'] = actions.user_invite_waiting_keycloak_user
            else:
                # Προεπιλογή σε περίπτωση λάθους στη παράμετρο
                exposed_actions['user_invite'] = actions.user_invite_notify

            exposed_actions['organization_member_create'] = actions.organization_member_create_custom

        return exposed_actions

    ''' Έλεγχος αν είναι υπάρχει παραμετροποίηση '''
    @staticmethod
    def raise_error_if_username_not_set():
        username = config.get('ckanext.geonames.username')
        if not username or not str(username).strip():
            raise toolkit.ValidationError('GeoNames username is not configured.')
        return str(username).strip()

    @staticmethod
    def _build_bbox_polygon_geojson(raw_bbox: Any) -> str:
        if not isinstance(raw_bbox, dict):
            return ''
        try:
            west = float(raw_bbox.get('west'))
            south = float(raw_bbox.get('south'))
            east = float(raw_bbox.get('east'))
            north = float(raw_bbox.get('north'))
        except (TypeError, ValueError):
            return ''

        polygon = {
            "type": "Polygon",
            "coordinates": [[
                [west, south],
                [west, north],
                [east, north],
                [east, south],
                [west, south],
            ]],
        }
        try:
            return json.dumps(polygon, ensure_ascii=False)
        except Exception:
            return ''

    ''' Κλήση για ανάκτηση περιοχής '''
    @staticmethod
    def geonames_search_action(context, data_dict):
        """
        CKAN Action to search GeoNames.
        Expects 'query' in data_dict.
        """
        query = data_dict.get('query')
        if isinstance(query, str):
            query = query.strip()
        if not query:
            raise toolkit.ValidationError('Missing required parameter: query')

        try:
            # Ανάκτηση username και δημιουργία URL
            username = DataGovGrPlugin.raise_error_if_username_not_set()

            language = DataGovGrPlugin.get_language_from_url_or_default()

            url = "http://api.geonames.org/searchJSON"
            # Ορίζουμε σαν timeout για να απαντήσει ο GeoNames Server
            REQUEST_TIMEOUT = (5, 10)  # seconds

            response = requests.get(
                url,
                params={
                    "q": query,
                    "maxRows": 10,
                    "username": username,
                    "lang": language,
                },
                timeout=REQUEST_TIMEOUT,
            )

            # Exception για τις κλήσεις που είναι της μορφής (4xx or 5xx)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout as e:
            # Exception για τις κλήσεις που αργεί ο server να απαντήσει
            raise toolkit.ValidationError(f'GeoNames API request timed out: {str(e)}')
        except requests.exceptions.RequestException as e:
            # Exception για client side σφάλματα
            raise toolkit.ValidationError(f'Error communicating with GeoNames API: {str(e)}')
        except toolkit.ValidationError:
            # ΓΙα validation σφάλματα
            raise
        except Exception as e:
            # Για οποιοδήποτε άλλο σφάλμα
            raise toolkit.ValidationError(f'Unexpected error during GeoNames search: {str(e)}')

    ''' Κλήση για ανάκτηση αναλυτικών στοιχείων τοποθεσίας GeoNames '''
    @staticmethod
    def geonames_get_action(context, data_dict):
        geoname_id_raw = data_dict.get('geonameId')
        geoname_id = str(geoname_id_raw).strip() if geoname_id_raw is not None else ''
        if not geoname_id:
            raise toolkit.ValidationError('Missing required parameter: geonameId')

        try:
            username = DataGovGrPlugin.raise_error_if_username_not_set()
            language = DataGovGrPlugin.get_language_from_url_or_default()
            request_timeout = (5, 10)  # seconds

            response = requests.get(
                "http://api.geonames.org/getJSON",
                params={
                    "geonameId": geoname_id,
                    "username": username,
                    "lang": language,
                    "style": "full",
                },
                timeout=request_timeout,
            )
            response.raise_for_status()
            payload = response.json() or {}

            raw_bbox = payload.get('bbox')
            bbox_geojson = DataGovGrPlugin._build_bbox_polygon_geojson(raw_bbox)

            return {
                "geonameId": geoname_id,
                "bbox_raw": raw_bbox if isinstance(raw_bbox, dict) else None,
                "bbox": bbox_geojson,
            }
        except requests.exceptions.Timeout as e:
            raise toolkit.ValidationError(f'GeoNames API request timed out: {str(e)}')
        except requests.exceptions.RequestException as e:
            raise toolkit.ValidationError(f'Error communicating with GeoNames API: {str(e)}')
        except toolkit.ValidationError:
            raise
        except Exception as e:
            raise toolkit.ValidationError(f'Unexpected error during GeoNames get details: {str(e)}')

    ''' Ανάκτηση της γλώσσας από το URL αν υπάρχει '''
    @staticmethod
    def get_language_from_url_or_default():
        referer = request.environ.get('HTTP_REFERER')

        # Default to None initially
        language = None
        import json
        if referer:
            # Extract the path and split
            path = urlparse(referer).path
            parts = path.strip("/").split("/")

            # Get language from URL if available
            if parts:
                lang_candidate = parts[0]

                # Get offered languages and default from CKAN config
                available_languages = ['el', 'en','fr', 'es', 'it', 'ja']
                default_language = toolkit.config.get('locale_default', 'en')

                # Check if it's an offered language
                if lang_candidate in available_languages:
                    language = lang_candidate
                else:
                    language = default_language
            else:
                language = toolkit.config.get('default_locale', 'en')
        else:
            language = toolkit.config.get('default_locale', 'en')
        return language

    @staticmethod
    def _change_valid_name():
        # Έλεγχος αν επιτρέπεται οποιοσδήποτε χαρακτήρας π.χ. @ από το ckan.ini
        allow_any_character = toolkit.asbool(
            toolkit.config.get('ckanext.data_gov_gr.user.allow_any_character_in_username', False))

        # Τροποποίηση του VALID_NAME pattern στην κλάση User για να επιτρέπει όλους τους χαρακτήρες
        if allow_any_character:
            model.User.VALID_NAME = re.compile(r"^[^\s]{3,255}$")

    def _is_sysadmin(self, context):
        """
        Ελέγχει αν ο τρέχων χρήστης είναι sysadmin.
        Επιστρέφει True αν είναι sysadmin, αλλιώς False.
        Χρησιμοποιείται για να αποφασιστεί αν μπορεί να αλλάξει την ορατότητα σε δημόσια.
        """
        user = context.get('user')
        if not user:
            return False
        user_obj = model.User.get(user)
        return bool(user_obj and user_obj.sysadmin)

    def before_create(self, *args, **kwargs):
        """
        Συνδυασμένο hook:

        - Ως IDCATRDFHarvester.before_create(harvest_object, dataset_dict, temp_dict)
          (καλείται από τον DCATRDFHarvester πριν το package_create)
        - Ως IPackageController.before_create(context, pkg_dict)
          (καλείται από τον CKAN πριν τη δημιουργία dataset/decision)
          Αν το dataset είναι τύπου 'decision' και ο χρήστης **δεν** είναι sysadmin:
          - Επιβάλλει να είναι ιδιωτικό (private=True)
          - Αποτρέπει την επιλογή Public στο UI ή μέσω API
        """
        # Κλήση από DCATRDFHarvester (harvest_object, dataset_dict, temp_dict)
        if len(args) == 3 and args and not isinstance(args[0], dict):
            # Δεν χρειάζεται να κάνουμε κάτι ειδικά για το harvest case
            return

        # Κλήση από IPackageController (context, pkg_dict)
        if len(args) == 2 and isinstance(args[0], dict) and isinstance(args[1], dict):
            context, pkg_dict = args
            try:
                if pkg_dict.get('type') == 'decision':
                    if not self._is_sysadmin(context):
                        # "Κλειδώνουμε" το decision σε ιδιωτικό
                        pkg_dict['private'] = True
            except Exception:
                # Αγνοούμε σφάλματα για να μην σπάσει η δημιουργία dataset
                pass
            return pkg_dict

        # Οποιαδήποτε άλλη κλήση την αγνοούμε σιωπηλά
        return

    def before_update(self, *args, **kwargs):
        """
        Συνδυασμένο hook:

        - Ως IDCATRDFHarvester.before_update(harvest_object, dataset_dict, temp_dict)
          (καλείται από τον DCATRDFHarvester πριν το package_update)
        - Ως IPackageController.before_update(context, pkg_dict)
          (καλείται από τον CKAN πριν την ενημέρωση dataset/decision)
                  Καλείται πριν την ενημέρωση ενός dataset/decision.
        Αν το dataset είναι τύπου 'decision' και ο χρήστης **δεν** είναι sysadmin:
          - Επιβάλλει να παραμείνει ιδιωτικό (private=True)
          - Αποτρέπει την αλλαγή σε Public μέσω UI ή API
        """
        # Κλήση από DCATRDFHarvester (harvest_object, dataset_dict, temp_dict)
        if len(args) == 3 and args and not isinstance(args[0], dict):
            # Δεν κάνουμε κάτι επιπλέον για το harvest case
            return

        # Κλήση από IPackageController (context, pkg_dict)
        if len(args) == 2 and isinstance(args[0], dict) and isinstance(args[1], dict):
            context, pkg_dict = args
            try:
                if pkg_dict.get('type') == 'decision':
                    if not self._is_sysadmin(context):
                        # Απαγόρευση αλλαγής σε public για μη-sysadmin
                        pkg_dict['private'] = True
            except Exception:
                # Αγνοούμε σφάλματα για να μην σπάσει η ενημέρωση
                pass
            return pkg_dict

        # Οποιαδήποτε άλλη κλήση την αγνοούμε σιωπηλά
        return

    def after_dataset_show(self, context, package_dict):
        # Feature flag (default True): allow disabling via ckan.ini if ever needed
        if not helpers.should_include_relationships_in_show():
            return package_dict

        # Ελέγχουμε αν η λίστα είναι κενή ή λείπει (συμβαίνει όταν το αποτέλεσμα έρχεται από Solr cache)
        if not package_dict.get('relationships_as_subject'):
            try:
                # Καλούμε το action του relationships plugin που φέρνει και τα external URIs
                relationships = logic.get_action('package_relationships_list')(
                    context, {'id': package_dict['id']}
                )

                if relationships:
                    package_dict['relationships_as_subject'] = relationships

            except Exception as e:
                log.warning("Error updating relationships in after_dataset_show: %s", str(e))

        return package_dict

class DataGovGrSpatialHarvesterPlugin(plugins.SingletonPlugin):
    """
    Separate plugin class for ckanext-spatial hooks.

    Reason: both CKAN (IValidators) and ckanext-spatial (ISpatialHarvester) use a
    method named `get_validators()`, but they expect different return types.
    Keeping them in separate classes avoids runtime type conflicts.
    """
    plugins.implements(ISpatialHarvester, inherit=True)

    def get_package_dict(self, context: dict[str, Any], data_dict: dict[str, Any]) -> dict[str, Any]:
        """
        Override hook για spatial harvesting (ckanext-spatial / ISpatialHarvester.get_package_dict).

        Καλείται στο import των CSW/ISO19139 αφού έχει φτιαχτεί το ``package_dict``.
        Εδώ χαρτογραφούμε το ISO19139 ``topicCategory`` σε DCAT-AP ``theme`` (EU URIs)
        και το αποθηκεύουμε στο ``package_dict["theme"]``.
        """
        package_dict = data_dict.get("package_dict")
        iso_values = data_dict.get("iso_values") or {}
        xml_tree = data_dict.get("xml_tree")
        harvest_object = data_dict.get("harvest_object")

        if isinstance(package_dict, dict):
            if should_skip_data_service_package(package_dict, harvest_object):
                return None
            if should_skip_dataset_with_uuid_like_layer_identifier(
                xml_tree,
                harvest_object,
            ):
                return None
            if should_skip_dataset_when_title_matches_layer_name(
                package_dict,
                xml_tree,
                harvest_object,
            ):
                return None

            apply_dataset_name_from_file_identifier(package_dict, xml_tree, harvest_object)
            apply_landing_page_from_file_identifier(package_dict, xml_tree, harvest_object)

            # Cleanup tags: remove "__", "--", etc (junk tags)
            cleanup_package_tags(package_dict)

            # Set dcat_type for geospatial datasets
            apply_dcat_type_geospatial(package_dict, overwrite=False)

            apply_theme_from_topiccategory(package_dict, iso_values, xml_tree)
            apply_default_dataset_fields_from_config(package_dict, harvest_object)

            apply_temporal_coverage_from_iso19139(package_dict, xml_tree)

            # ISO resourceMaintenance/maintenanceAndUpdateFrequency -> DCAT frequency (EU URI)
            apply_frequency_from_resource_maintenance(package_dict, iso_values, xml_tree)

            # Default applicable legislation (only if missing)
            ensure_applicable_legislation(package_dict, protected=False)

            prepend_configured_wms_layer_resource(package_dict, xml_tree, harvest_object)
            prepend_wms_preview_resource_from_online_resource(
                package_dict,
                xml_tree,
                harvest_object,
            )
            prepend_wms_preview_resources_from_wms_online_resources(
                package_dict,
                xml_tree,
                harvest_object,
            )
            insert_configured_wms_wfs_capabilities_resources(
                package_dict,
                xml_tree,
                harvest_object,
            )

            apply_resource_rights_and_license_from_iso19139(package_dict, xml_tree, overwrite=False)
            apply_resource_rights_from_iso_use_constraints(
                package_dict,
                xml_tree,
                harvest_object,
                overwrite=False,
            )
            apply_default_resource_fields_from_config(package_dict, harvest_object)

            apply_resource_access_url_from_url(package_dict, harvest_object)
            apply_resource_description_from_name(package_dict, harvest_object)
            apply_resource_mimetype_from_distribution_format(
                package_dict,
                xml_tree,
                harvest_object,
            )

            apply_download_url_for_direct_downloads(package_dict, xml_tree, overwrite=False)
            apply_resource_format_from_iso19139(
                package_dict,
                xml_tree,
                overwrite=True,
                harvest_object=harvest_object,
            )

            preserve_resource_ids_by_url(package_dict, harvest_object)

        return package_dict

    def get_validators(self):
        """
        Spatial harvesting validators hook (ckanext-spatial / ISpatialHarvester.get_validators).

        Must return a list of Validator CLASSES (each with `.name` and `.is_valid()`).
        If you don't add custom spatial validators, return an empty list.
        """
        return []
