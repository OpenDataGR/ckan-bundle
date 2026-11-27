import logging
from pathlib import Path

import ckan.model as model
import ckan.plugins as p
from ckan.plugins import toolkit

from ckanext.archiver.interfaces import IPipe
from ckanext.qa.logic import action, auth
from ckanext.qa.model import QA, aggregate_qa_for_a_dataset
from ckanext.qa.helpers import qa_show_openness_stars, qa_openness_stars_resource_html, qa_openness_stars_dataset_html, qa_mqa_rating_label
from ckanext.qa import lib as qa_lib
from ckanext.qa.lib import create_qa_update_package_task
from ckanext.report.interfaces import IReport
import ckanext.data_gov_gr.helpers as data_gov_gr_helpers


log = logging.getLogger(__name__)

# Τύποι datasets για τους οποίους δεν υπολογίζεται ανοικτότητα.
OPENNESS_SKIPPED_TYPES = ('decision', 'data-service')


if toolkit.check_ckan_version(min_version='2.9.0'):
    from ckanext.qa.plugin.flask_plugin import MixinPlugin
else:
    from ckanext.qa.plugin.pylons_plugin import MixinPlugin


def _mqa_rating_from_score(mqa_score):
    if mqa_score is None:
        return None
    if 86.4 <= mqa_score <= 100:
        return 'excellent'
    if 54.3 <= mqa_score < 86.4:
        return 'good'
    if 29.6 <= mqa_score < 54.3:
        return 'sufficient'
    if 0 <= mqa_score < 29.6:
        return 'bad'
    return None


def _build_mqa_for_dataset_without_resources(pkg_dict):
    resources = pkg_dict.get('resources') or []
    if resources:
        return None

    try:
        from ckanext.data_gov_gr.logic.mqa_calculator import MQACalculator
    except ImportError:
        return None

    try:
        check_urls = toolkit.asbool(
            toolkit.config.get('ckanext.data_gov_gr.mqa.check_urls', True)
        )
        mqa_scores = MQACalculator(check_urls=check_urls).calculate_all_scores(pkg_dict)
    except Exception as e:
        log.warning(
            'Error calculating fallback MQA scores for dataset %s: %s',
            pkg_dict.get('id'),
            str(e)
        )
        return None

    return {
        'openness_score': None,
        'openness_score_reason': None,
        'mqa_score': round(mqa_scores.get('percentage', 0), 1),
        'mqa_findability_score': round(mqa_scores.get('findability', 0), 1),
        'mqa_accessibility_score': round(mqa_scores.get('accessibility', 0), 1),
        'mqa_interoperability_score': round(mqa_scores.get('interoperability', 0), 1),
        'mqa_reusability_score': round(mqa_scores.get('reusability', 0), 1),
        'mqa_contextuality_score': round(mqa_scores.get('contextuality', 0), 1),
        'updated': None
    }


class QAPlugin(MixinPlugin, p.SingletonPlugin, toolkit.DefaultDatasetForm):
    p.implements(p.IConfigurer, inherit=True)
    p.implements(IPipe, inherit=True)
    p.implements(IReport)
    p.implements(p.IActions)
    p.implements(p.IAuthFunctions)
    p.implements(p.ITemplateHelpers)
    p.implements(p.IPackageController, inherit=True)
    p.implements(p.IFacets)
    p.implements(p.IPluginObserver)
    p.implements(p.ITranslation)

    # IConfigurer

    def update_config(self, config):
        toolkit.add_template_directory(config, '../templates')

        # Έλεγχος του ckanext.qa.openness_mode κατά την εκκίνηση: άγνωστη
        # τιμή σταματά την εφαρμογή αντί να γυρίσει σιωπηλά στο default.
        log.info('QA openness mode: %s', qa_lib.openness_mode())
        from ckanext.archiver import job_dedup
        log.info('QA dedup strategy: %s', job_dedup.get_strategy('qa'))
        qa_lib.register_session_hooks()

        # check for qsv config
        qsv_bin = config.get('ckanext.qa.qsv_bin')
        if qsv_bin:
            qsv_path = Path(qsv_bin)
            if not qsv_path.is_file():
                log.error('ckanext.qa.qsv_bin file not found: %s', qsv_path)
        else:
            log.error('ckanext.qa.qsv_bin not set')

        # Warm the tldextract cache to avoid blocking on first use
        try:
            import tldextract
            log.debug('Warming tldextract cache...')
            # This will download the PSL file if not already cached
            tldextract.extract('example.com', include_psl_private_domains=True)
            log.debug('tldextract cache warmed successfully')
        except ImportError:
            log.debug('tldextract not available, skipping cache warming')

    # IPipe

    def reindexes_after_package_archived(self):
        '''Στο archival mode το QA κάνει reindex μετά το package-archived· σε
        metadata_only το αγνοεί, οπότε το reindex το κάνει ο archiver.'''
        return not qa_lib.is_metadata_only_mode()

    def receive_data(self, operation, queue, **params):
        '''Receive notification from ckan-archiver that a dataset has been
        archived.'''
        if not operation == 'package-archived':
            return
        if qa_lib.is_metadata_only_mode():
            # Σε metadata_only το QA μπαίνει στην ουρά από τα
            # after_dataset_create/update και δεν εξαρτάται από τον archiver.
            return
        dataset_id = params['package_id']

        dataset = model.Package.get(dataset_id)
        assert dataset

        create_qa_update_package_task(dataset, queue=queue)

    # IReport

    def register_reports(self):
        """Register details of an extension's reports"""
        from ckanext.qa import reports
        return [reports.openness_report_info, reports.metadata_quality_report_info]

    # IActions

    def get_actions(self):
        return {
            'qa_resource_show': action.qa_resource_show,
            'qa_package_openness_show': action.qa_package_openness_show,
            }

    # IAuthFunctions

    def get_auth_functions(self):
        return {
            'qa_resource_show': auth.qa_resource_show,
            'qa_package_openness_show': auth.qa_package_openness_show,
            }

    # ITemplateHelpers

    def get_helpers(self):
        return {
            'qa_show_openness_stars': qa_show_openness_stars,
            'qa_openness_stars_resource_html':
            qa_openness_stars_resource_html,
            'qa_openness_stars_dataset_html':
            qa_openness_stars_dataset_html,
            'qa_mqa_rating_label':
            qa_mqa_rating_label,
            }

    # IPackageController

    def after_show(self, context, pkg_dict):
        """ Old CKAN function name """
        return self.after_dataset_show(context, pkg_dict)

    def after_dataset_create(self, context, pkg_dict):
        """
        Calculate and store MQA scores after a dataset is created.
        """
        try:
            from ckanext.qa.tasks import calculate_and_store_mqa_scores
            log.info('Calculating MQA scores for newly created dataset: %s', pkg_dict['id'])
            calculate_and_store_mqa_scores(pkg_dict['id'])
        except Exception as e:
            log.error('Error calculating MQA scores for dataset %s: %s', pkg_dict['id'], str(e))
        self._queue_metadata_openness(pkg_dict)

    def after_dataset_update(self, context, pkg_dict):
        """
        Calculate and store MQA scores after a dataset is updated.
        """
        try:
            from ckanext.qa.tasks import calculate_and_store_mqa_scores
            log.info('Calculating MQA scores for updated dataset: %s', pkg_dict['id'])
            calculate_and_store_mqa_scores(pkg_dict['id'])
        except Exception as e:
            log.error('Error calculating MQA scores for dataset %s: %s', pkg_dict['id'], str(e))
        self._queue_metadata_openness(pkg_dict)

    def _queue_metadata_openness(self, pkg_dict):
        """
        Σε metadata_only, κάθε create/update dataset βάζει QA job στην ουρά
        priority, μετά το commit. Το package_update καλείται και από
        resource create/update/delete/reorder, οπότε καλύπτονται κι αυτά.
        """
        try:
            if not qa_lib.is_metadata_only_mode():
                return
            if pkg_dict.get('type') in OPENNESS_SKIPPED_TYPES:
                return
            qa_lib.queue_openness_after_commit(pkg_dict['id'])
        except Exception as e:
            log.error('Error queueing openness QA for dataset %s: %s',
                      pkg_dict.get('id'), str(e))

    def after_dataset_show(self, context, pkg_dict):
        # Insert the qa info into the package_dict so that it is
        # available on the API.
        # When you edit the dataset, these values will not show in the form,
        # it they will be saved in the resources (not the dataset). I can't see
        # and easy way to stop this, but I think it is harmless. It will get
        # overwritten here when output again.

        # Skip QA info for decisions and data-services
        if pkg_dict.get('type') in OPENNESS_SKIPPED_TYPES:
            return

        qa_objs = QA.get_for_package(pkg_dict['id'])
        if not qa_objs:
            fallback_qa = _build_mqa_for_dataset_without_resources(pkg_dict)
            if fallback_qa:
                pkg_dict['qa'] = fallback_qa
            return
        # dataset
        dataset_qa = aggregate_qa_for_a_dataset(qa_objs)
        pkg_dict['qa'] = dataset_qa
        # resources
        qa_by_res_id = dict((a.resource_id, a) for a in qa_objs)
        for res in pkg_dict['resources']:
            qa = qa_by_res_id.get(res['id'])
            if qa:
                qa_dict = qa.as_dict()
                del qa_dict['id']
                del qa_dict['package_id']
                del qa_dict['resource_id']
                res['qa'] = qa_dict

    """
    Μέθοδος που εκτελείται πριν την index.py:index_package
    """
    # IPackageController
    def before_dataset_index(self, pkg_dict):
        '''
        Extract QA scores from `qa` and add them to the package dictionary for indexing
        '''
        # Skip openness score for decisions and data-services
        if pkg_dict.get('type') in OPENNESS_SKIPPED_TYPES:
            pkg_dict.pop('qa', None)
            return pkg_dict

        qa = pkg_dict.get('qa')
        if qa is None:
            qa = _build_mqa_for_dataset_without_resources(pkg_dict)
        if qa is not None:
            # Add openness score
            openness_score = qa.get('openness_score')
            if openness_score is not None:
                pkg_dict['qa_openness_score'] = openness_score

            # Add MQA score and categorize it
            mqa_score = qa.get('mqa_score')
            if mqa_score is not None:
                pkg_dict['qa_mqa_score'] = mqa_score

                mqa_rating = _mqa_rating_from_score(mqa_score)
                if mqa_rating is not None:
                    pkg_dict['qa_mqa_rating'] = mqa_rating

        pkg_dict.pop('qa', None)
        return pkg_dict

    # IFacets
    def dataset_facets(self, facets_dict, package_type):
        """
        Προσθέτει τα facets μόνο για datasets,
        και τα εξαιρεί για data-service και showcases.
        """
        if package_type == 'dataset':
            # Προσθήκη facet για Openness Score
            facets_dict['qa_openness_score'] = toolkit._('Openness Score')
            # Προσθήκη facet για MQA Rating
            if data_gov_gr_helpers.can_view_mqa_facet():
                facets_dict['qa_mqa_rating'] = toolkit._('MQA Rating')
        return facets_dict

    def organization_facets(self, facets, organization_type, package_type):
        return facets

    # IPluginObserver

    def before_load(self, plugin):
        # Called before a plugin is loaded
        pass

    def after_load(self, service):
        # Called after a plugin is loaded
        pass

    def before_unload(self, plugin):
        # Called before a plugin is unloaded
        # If this plugin is being unloaded, shut down the RDF_THREAD_POOL
        if plugin == 'qa':
            log.info('Shutting down RDF_THREAD_POOL...')
            try:
                from ckanext.qa.tasks import RDF_THREAD_POOL
                RDF_THREAD_POOL.shutdown(wait=True)
                log.info('RDF_THREAD_POOL shut down successfully')
            except Exception as e:
                log.error('Error shutting down RDF_THREAD_POOL: %s', str(e))

    def after_unload(self, service):
        # Called after a plugin is unloaded
        pass

    # ITranslation
    def i18n_directory(self):
        import os
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), 'i18n')

    def i18n_domain(self):
        return 'ckanext-qa'

    def i18n_locales(self):
        return ['el', 'en']
