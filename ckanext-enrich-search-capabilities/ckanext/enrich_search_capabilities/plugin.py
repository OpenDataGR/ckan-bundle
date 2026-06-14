import os

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
from ckan.lib.plugins import DefaultTranslation

from ckanext.enrich_search_capabilities import actions, auth, helpers, views

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")


def _blank_or_positive_integer(value, context):
    # The admin form submits an empty string to reset the option to its
    # default; the config helper treats it as unset.
    if value is None or value == "":
        return ""
    return toolkit.get_validator("is_positive_integer")(value, context)


class EnrichSearchCapabilitiesPlugin(
    plugins.SingletonPlugin,
    DefaultTranslation,
):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IConfigurable)
    plugins.implements(plugins.IConfigDeclaration)
    plugins.implements(plugins.IActions)
    plugins.implements(plugins.IAuthFunctions)
    plugins.implements(plugins.IBlueprint)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.ITranslation, inherit=True)

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, "templates")
        toolkit.add_public_directory(config_, "public")
        toolkit.add_resource("assets", "enrich_search_capabilities")

    def update_config_schema(self, schema):
        ignore_missing = toolkit.get_validator("ignore_missing")
        boolean_validator = toolkit.get_validator("boolean_validator")
        schema["ckanext.enrich_search_capabilities.enabled"] = [
            ignore_missing,
            boolean_validator,
        ]
        schema[
            "ckanext.enrich_search_capabilities.header_search_enabled"
        ] = [
            ignore_missing,
            boolean_validator,
        ]
        schema[
            "ckanext.enrich_search_capabilities.guides_search_enabled"
        ] = [
            ignore_missing,
            boolean_validator,
        ]
        schema[
            "ckanext.enrich_search_capabilities.dataset_live_search_enabled"
        ] = [
            ignore_missing,
            boolean_validator,
        ]
        schema[
            "ckanext.enrich_search_capabilities.dataset_live_search_limit"
        ] = [
            ignore_missing,
            _blank_or_positive_integer,
        ]
        return schema

    # IConfigurable

    def configure(self, config_):
        paths = config_.get("computed_template_paths", [])
        if _TEMPLATES_DIR in paths:
            paths.remove(_TEMPLATES_DIR)
            paths.insert(0, _TEMPLATES_DIR)
            config_["computed_template_paths"] = paths

    # IConfigDeclaration

    def declare_config_options(self, declaration, key):
        declaration.annotate("ckanext-enrich-search-capabilities")
        declaration.declare_bool(
            key.ckanext.enrich_search_capabilities.enabled,
            False,
        ).set_description(
            toolkit._(
                "Enable keyword search on the ckanext-pages /pages and /blog "
                "indexes."
            )
        )
        declaration.declare_bool(
            key.ckanext.enrich_search_capabilities.header_search_enabled,
            False,
        ).set_description(
            toolkit._(
                "Enable the search destination dropdown in the site header."
            )
        )
        declaration.declare_bool(
            key.ckanext.enrich_search_capabilities.guides_search_enabled,
            False,
        ).set_description(
            toolkit._(
                "Enable the external guides search option in the header "
                "dropdown."
            )
        )
        declaration.declare_bool(
            key.ckanext.enrich_search_capabilities.dataset_live_search_enabled,
            False,
        ).set_description(
            toolkit._(
                "Enable live search suggestions on the dataset search page."
            )
        )
        declaration.declare_int(
            key.ckanext.enrich_search_capabilities.dataset_live_search_limit,
            10,
        ).set_description(
            toolkit._(
                "Maximum number of suggestions returned by the dataset live "
                "search, between 1 and 10."
            )
        )

    # IActions

    def get_actions(self):
        return {
            "enrich_pages_search": actions.enrich_pages_search,
            "enrich_dataset_live_search": actions.enrich_dataset_live_search,
        }

    # IAuthFunctions

    def get_auth_functions(self):
        return {
            "enrich_pages_search": auth.enrich_pages_search,
            "enrich_dataset_live_search": auth.enrich_dataset_live_search,
        }

    # ITemplateHelpers

    def get_helpers(self):
        return helpers.get_helpers()

    # IBlueprint

    def get_blueprint(self):
        return views.blueprint
