import os

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

from ckanext.hvd_validator import helpers
from ckanext.hvd_validator import views

plugin_dir = os.path.dirname(__file__)


class HvdValidatorPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IConfigDeclaration)
    plugins.implements(plugins.IBlueprint)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.ITranslation)

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, "templates")

    def update_config_schema(self, schema):
        ignore_missing = toolkit.get_validator("ignore_missing")
        boolean_validator = toolkit.get_validator("boolean_validator")
        schema[helpers.DATASET_ACTION_ENABLED_CONFIG] = [
            ignore_missing,
            boolean_validator,
        ]
        return schema

    # IConfigDeclaration

    def declare_config_options(self, declaration, key):
        declaration.annotate("ckanext-hvd-validator")
        declaration.declare_bool(
            key.ckanext.hvd_validator.dataset_action.enabled,
            True,
        ).set_description(
            toolkit._(
                "Show the HVD Validator button on HVD dataset pages."
            )
        )

    # IBlueprint

    def get_blueprint(self):
        return views.get_blueprint()

    # ITemplateHelpers

    def get_helpers(self):
        return helpers.get_helpers()

    # ITranslation

    def i18n_directory(self):
        return os.path.join(plugin_dir, "i18n")

    def i18n_domain(self):
        return "ckanext-hvd_validator"

    def i18n_locales(self):
        return ["el"]
