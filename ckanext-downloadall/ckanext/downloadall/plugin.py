import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
from ckan.lib.plugins import DefaultTranslation

from ckan import model

from . import helpers
from . import action
from . import eligibility
from . import lib


log = __import__('logging').getLogger(__name__)


@toolkit.blanket.config_declarations
class DownloadallPlugin(plugins.SingletonPlugin, DefaultTranslation):
    plugins.implements(plugins.ITranslation)
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IDomainObjectModification)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IPackageController, inherit=True)
    plugins.implements(plugins.IActions)

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('fanstatic', 'downloadall')
        # Έλεγχος του ckanext.downloadall.dedup_strategy κατά την εκκίνηση και
        # καταχώριση των hooks για το enqueue μετά το commit
        lib.check_config()

    # IDomainObjectModification

    def notify(self, entity, operation):
        u'''
        Βάζει job για το ZIP του dataset μετά το commit, όταν αλλάζει το
        dataset ή κάποιος πόρος του (OD-857).

        Το ίδιο το job αποφασίζει αν το ZIP χρειάζεται νέο build (fingerprint
        και hash του datapackage.json), οπότε εδώ δεν γίνεται σύγκριση.
        Αγνοούνται:
          - η ενημέρωση του ίδιου του ZIP από το job (αλλιώς ατέρμονος κύκλος)
          - datasets χωρίς δικαίωμα σε ZIP που δεν έχουν ZIP (π.χ. μη HVD με
            hvd_only)

        :param entity: instance of model.Package or model.Resource
        :param operation: 'new', 'changed' or 'deleted'.
        '''
        if operation == 'deleted' or entity is None or lib.in_own_update():
            return

        if isinstance(entity, model.Package):
            dataset = entity
        elif isinstance(entity, model.Resource):
            if eligibility.is_zip_model_resource(entity):
                # Το ίδιο το ZIP· η αλλαγή του δεν χρειάζεται νέο build
                return
            packages = entity.related_packages()
            if not packages:
                return
            dataset = packages[0]
        else:
            return

        if not eligibility.package_needs_job(dataset):
            log.debug('No DownloadAll job for %s', dataset.name)
            return
        lib.enqueue_zip_after_commit(dataset.id)

    # ITemplateHelpers

    def get_helpers(self):
        return {
            'downloadall__pop_zip_resource': helpers.pop_zip_resource,
            'downloadall__is_data_service': helpers.is_data_service,
            'downloadall__zip_state': helpers.zip_state,
            'downloadall__zip_missing_count': helpers.zip_missing_count,
        }

    # IPackageController
    def before_dataset_index(self, data_dict):
        return self.before_index(data_dict)

    def before_index(self, pkg_dict):
        try:
            has_downloadall = False

            # Primary check: parse validated_data_dict to look for the
            # downloadall_metadata_modified marker on any resource.
            # This is more reliable than checking the name.
            import json
            validated = pkg_dict.get('validated_data_dict')
            if validated:
                try:
                    vd = json.loads(validated)
                    for res in vd.get('resources', []):
                        if res.get('downloadall_metadata_modified'):
                            has_downloadall = True
                            break
                except (json.JSONDecodeError, TypeError):
                    pass

            # Fallback: also check res_name for known zip resource names
            if not has_downloadall:
                res_names = pkg_dict.get('res_name', [])
                if res_names:
                    downloadall_names = {u'All resource data', u'Όλα τα δεδομένα πόρων'}
                    has_downloadall = any(
                        name and any(dn in name for dn in downloadall_names)
                        for name in res_names
                    )

            if has_downloadall:
                # we've got a 'Download all zip', so remove it's ZIP from the
                # SOLR facet of resource formats, as it's not really a data
                # resource
                pkg_dict['res_format'].remove('ZIP')
        except (KeyError, ValueError, TypeError):
            # this happens when you save a new package without a resource yet
            pass
        return pkg_dict

    # IActions

    def get_actions(self):
        actions = {
            'package_update': action.package_update,
            'resource_delete': action.resource_delete,
        }
        if plugins.get_plugin('datastore'):
            # datastore is enabled, so we need to chain the datastore_create
            # action, to update the zip when it is called
            actions['datastore_create'] = action.datastore_create
        return actions
