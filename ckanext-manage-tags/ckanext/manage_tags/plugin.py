import os

from flask import Blueprint

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

from ckanext.manage_tags import actions, helpers, views


class ManageTagsPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IBlueprint)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IActions)
    plugins.implements(plugins.IAuthFunctions)
    plugins.implements(plugins.ITranslation)

    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')

    def get_blueprint(self):
        blueprint = Blueprint('manage_tags', __name__)
        blueprint.add_url_rule(
            '/ckan-admin/manage-tags',
            'index',
            views.index,
            strict_slashes=False,
        )
        blueprint.add_url_rule(
            '/ckan-admin/manage-tags/edit/<tag_id>',
            'edit',
            views.edit,
            methods=['GET', 'POST'],
            strict_slashes=False,
        )
        blueprint.add_url_rule(
            '/ckan-admin/manage-tags/rebuild-index',
            'rebuild_index',
            views.rebuild_index,
            methods=['GET', 'POST'],
            strict_slashes=False,
        )
        return blueprint

    def get_helpers(self):
        return {
            'manage_tags_get_free_tags': helpers.get_free_tags,
            'manage_tags_get_tag': helpers.get_manageable_tag_data,
            'manage_tags_type_label': helpers.type_label,
        }

    def get_actions(self):
        return {
            'manage_tags_tag_update': actions.manage_tags_tag_update,
        }

    def get_auth_functions(self):
        return {
            'manage_tags_tag_update': actions.manage_tags_tag_update_auth,
        }

    def i18n_directory(self):
        return os.path.join(os.path.dirname(__file__), 'i18n')

    def i18n_domain(self):
        return 'ckanext-manage_tags'

    def i18n_locales(self):
        directory = self.i18n_directory()
        if not os.path.isdir(directory):
            return []
        return [
            entry for entry in os.listdir(directory)
            if os.path.isdir(os.path.join(directory, entry))
        ]
