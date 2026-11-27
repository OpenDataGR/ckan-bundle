# -*- coding: utf-8 -*-
'''
Tests για το ckanext.qa.openness_mode (OD-856).

archival: η ιστορική ροή μετά τον archiver.
metadata_only: βαθμολογία από άδεια, κατάληξη URL και resource.format,
χωρίς δίκτυο, χωρίς archiver και με δικό της trigger σε create/update.
'''
from types import SimpleNamespace
from unittest import mock

import pytest

from ckan import model
from ckan.exceptions import CkanConfigurationException
from ckan.tests import factories, helpers

import ckanext.qa.tasks as qa_tasks
from ckanext.qa import lib as qa_lib
from ckanext.qa import model as qa_model
from ckanext.qa import utils as qa_utils
from ckanext.archiver import job_dedup
from ckanext.archiver import model as archiver_model

OPEN_RESOURCE_LICENSE = 'https://creativecommons.org/licenses/by/4.0/'

# Κανένας έλεγχος URL από το MQA κατά τα tests.
pytestmark = pytest.mark.ckan_config('ckanext.data_gov_gr.mqa.check_urls', 'false')


@pytest.fixture
def qa_tables(clean_db):
    archiver_model.init_tables(model.meta.engine)
    qa_model.init_tables(model.meta.engine)


@pytest.fixture(autouse=True)
def enqueue_calls():
    '''Καταγράφει τα jobs αντί να τα στέλνει στο Redis, και απενεργοποιεί
    τον υπολογισμό MQA στα hooks ώστε τα tests να μην κάνουν HTTP.

    Το QA χρησιμοποιεί το ckanext.qa.lib.enqueue_job και ο archiver το
    ckan.plugins.toolkit.enqueue_job· επιστρέφονται μόνο τα QA jobs.
    '''
    calls = []

    def _record(fn, args=None, queue=None, **kwargs):
        calls.append({'fn': fn, 'args': list(args or []), 'queue': queue})

    with mock.patch.object(qa_lib, 'enqueue_job', side_effect=_record), \
            mock.patch('ckan.plugins.toolkit.enqueue_job'), \
            mock.patch.object(qa_tasks, 'calculate_and_store_mqa_scores'):
        yield _QaCalls(calls)

    # Καθαρισμός των κλειδιών «ένα job ανά dataset» από την Redis των tests
    conn = job_dedup._redis()
    for pattern in ('ckanext:*:qa:*', 'ckanext:*:archiver:*'):
        for key in conn.scan_iter(match=pattern):
            conn.delete(key)


class _QaCalls(object):
    '''Προβολή μόνο των QA update_package jobs από τα καταγεγραμμένα.'''

    def __init__(self, calls):
        self._calls = calls

    def all(self):
        return [c for c in self._calls if c['fn'] is qa_tasks.update_package]

    def package_ids(self):
        return [c['args'][0] for c in self.all()]

    def clear(self):
        del self._calls[:]


def _resource(url='http://example.com/data/file.csv', format='CSV',
              license_id='cc-by', resource_license=None, **dataset_kwargs):
    res = {'url': url, 'format': format}
    if resource_license:
        res['license'] = resource_license
    dataset = factories.Dataset(license_id=license_id, resources=[res],
                                **dataset_kwargs)
    return model.Resource.get(dataset['resources'][0]['id'])


@pytest.mark.usefixtures('with_plugins', 'qa_tables')
@pytest.mark.ckan_config('ckan.plugins', 'qa archiver report')
class TestResourceScoreMetadata(object):

    def test_known_url_suffix(self):
        result = qa_tasks.resource_score_metadata(_resource())
        assert result['openness_score'] == 3, result
        assert result['format'] == 'CSV'
        assert result['archival_timestamp'] is None
        assert 'URL extension "csv"' in result['openness_score_reason']

    def test_suffix_ignores_query_string_and_fragment(self):
        url = ('https://blob.example.com/container/report.xlsx'
               '?sv=2020-08-04&sig=abc%2Fdef.csv#sheet.json')
        result = qa_tasks.resource_score_metadata(_resource(url=url, format='XLSX'))
        assert result['format'] == 'XLSX', result
        assert result['openness_score'] == 2

    def test_unknown_suffix_falls_back_to_format_field(self):
        result = qa_tasks.resource_score_metadata(
            _resource(url='http://example.com/api/records', format='JSON'))
        assert result['format'] == 'JSON', result
        assert result['openness_score'] == 3
        assert 'Format field "JSON" receives score: 3.' in result['openness_score_reason']

    def test_format_field_is_normalised(self):
        result = qa_tasks.resource_score_metadata(
            _resource(url='http://example.com/download', format='.csv'))
        assert result['format'] == 'CSV', result
        assert result['openness_score'] == 3

    def test_suffix_wins_when_it_disagrees_with_format_field(self):
        result = qa_tasks.resource_score_metadata(
            _resource(url='http://example.com/file.csv', format='PDF'))
        assert result['format'] == 'CSV', result
        assert result['openness_score'] == 3
        assert 'Format field "PDF" does not match the URL extension "csv"' \
            in result['openness_score_reason']

    def test_no_url_and_no_format(self):
        result = qa_tasks.resource_score_metadata(_resource(url='', format=''))
        assert result['format'] is None
        assert result['openness_score'] == 1, result
        assert 'Could not understand the file format' in result['openness_score_reason']

    def test_resource_license_open_on_closed_dataset(self):
        result = qa_tasks.resource_score_metadata(
            _resource(license_id='notspecified',
                      resource_license=OPEN_RESOURCE_LICENSE))
        assert result['openness_score'] == 3, result
        assert 'Resource has open license' in result['openness_score_reason']

    def test_falls_back_to_open_dataset_license(self):
        result = qa_tasks.resource_score_metadata(_resource(license_id='cc-by'))
        assert result['openness_score'] == 3, result

    def test_license_not_open(self):
        result = qa_tasks.resource_score_metadata(
            _resource(license_id='notspecified', resource_license='proprietary'))
        assert result['openness_score'] == 0, result
        assert result['format'] == 'CSV'
        assert 'License not open' in result['openness_score_reason']

    def test_reason_says_it_is_an_estimate(self):
        result = qa_tasks.resource_score_metadata(_resource())
        assert 'the file contents were not inspected' in result['openness_score_reason']

    def test_no_network_no_file_and_no_archiver(self):
        resource = _resource()
        forbidden = AssertionError('must not be called in metadata_only')
        with mock.patch('requests.get', side_effect=forbidden), \
                mock.patch('requests.head', side_effect=forbidden), \
                mock.patch.object(qa_tasks, 'sniff_file_format', side_effect=forbidden), \
                mock.patch.object(archiver_model.Archival, 'get_for_resource',
                                  side_effect=forbidden), \
                mock.patch.object(archiver_model.Status, 'by_text',
                                  side_effect=forbidden):
            result = qa_tasks.resource_score_metadata(resource)
        assert result['openness_score'] == 3, result


@pytest.mark.usefixtures('with_plugins', 'qa_tables')
@pytest.mark.ckan_config('ckan.plugins', 'qa archiver report')
class TestModeSelection(object):

    def test_default_mode_is_archival(self):
        assert qa_lib.openness_mode() == 'archival'
        resource = _resource()
        with mock.patch.object(qa_tasks, 'resource_score_metadata') as metadata:
            qa_tasks.resource_score(resource)
        metadata.assert_not_called()

    @pytest.mark.ckan_config('ckanext.qa.openness_mode', 'metadata_only')
    def test_metadata_only_dispatch(self):
        resource = _resource()
        result = qa_tasks.resource_score(resource)
        assert result == qa_tasks.resource_score_metadata(resource)


class TestInvalidMode(object):
    '''Άγνωστη τιμή σταματά την εκκίνηση του plugin (δεν φορτώνεται εδώ, γιατί
    το with_plugins θα αποτύγχανε ήδη στο setup).'''

    @pytest.mark.ckan_config('ckanext.qa.openness_mode', 'bogus')
    def test_unknown_mode_is_rejected(self):
        with pytest.raises(CkanConfigurationException):
            qa_lib.openness_mode()

    @pytest.mark.ckan_config('ckanext.qa.openness_mode', 'bogus')
    def test_plugin_refuses_to_start(self):
        from ckan.plugins.toolkit import config
        from ckanext.qa.plugin import QAPlugin
        with pytest.raises(CkanConfigurationException):
            QAPlugin().update_config(config)

    @pytest.mark.ckan_config('ckanext.qa.openness_mode', ' Metadata_Only ')
    def test_value_is_normalised(self):
        assert qa_lib.openness_mode() == 'metadata_only'


class TestReindexDeclaration(object):
    '''Το QA δηλώνει στον archiver αν κάνει reindex μετά το package-archived.'''

    def test_archival_mode_reindexes(self):
        from ckanext.qa.plugin import QAPlugin
        assert QAPlugin().reindexes_after_package_archived() is True

    @pytest.mark.ckan_config('ckanext.qa.openness_mode', 'metadata_only')
    def test_metadata_only_does_not_reindex(self):
        from ckanext.qa.plugin import QAPlugin
        assert QAPlugin().reindexes_after_package_archived() is False


@pytest.mark.usefixtures('with_plugins')
@pytest.mark.ckan_config('ckan.plugins', 'qa archiver report')
class TestQueues(object):

    def test_logical_queue_names_by_default(self):
        assert qa_lib.resolve_queue('priority') == 'priority'
        assert qa_lib.resolve_queue('bulk') == 'bulk'
        assert qa_lib.resolve_queue('other') == 'other'

    @pytest.mark.ckan_config('ckanext.qa.queue.priority', 'qa_priority')
    @pytest.mark.ckan_config('ckanext.qa.queue.bulk', 'qa_bulk')
    def test_configured_queue_names(self):
        with mock.patch.object(qa_lib, 'enqueue_job') as enqueue:
            qa_lib.compat_enqueue('qa.update_package', qa_tasks.update_package,
                                  'priority', args=['pkg-id'])
            qa_lib.compat_enqueue('qa.update_package', qa_tasks.update_package,
                                  'bulk', args=['pkg-id'])
        queues = [c.kwargs['queue'] for c in enqueue.call_args_list]
        assert queues == ['qa_priority', 'qa_bulk']


@pytest.mark.usefixtures('with_plugins', 'qa_tables')
@pytest.mark.ckan_config('ckan.plugins', 'qa archiver report')
class TestTriggers(object):

    @pytest.mark.ckan_config('ckanext.qa.openness_mode', 'metadata_only')
    def test_metadata_only_queues_on_create_and_update(self, enqueue_calls):
        dataset = factories.Dataset(license_id='cc-by', resources=[
            {'url': 'http://example.com/file.csv', 'format': 'CSV'}])
        assert enqueue_calls.package_ids() == [dataset['id']]
        assert enqueue_calls.all()[0]['queue'] == 'priority'

        enqueue_calls.clear()
        helpers.call_action('package_patch', id=dataset['id'], notes='changed')
        assert enqueue_calls.package_ids() == [dataset['id']]

    @pytest.mark.ckan_config('ckanext.qa.openness_mode', 'metadata_only')
    def test_metadata_only_queues_on_resource_create(self, enqueue_calls):
        dataset = factories.Dataset(license_id='cc-by')
        enqueue_calls.clear()
        helpers.call_action('resource_create', package_id=dataset['id'],
                            url='http://example.com/file.json', format='JSON')
        assert enqueue_calls.package_ids() == [dataset['id']]

    @pytest.mark.ckan_config('ckanext.qa.openness_mode', 'metadata_only')
    def test_metadata_only_skips_data_services(self, enqueue_calls):
        factories.Dataset(type='data-service', resources=[
            {'url': 'http://example.com/api', 'format': 'API'}])
        assert enqueue_calls.package_ids() == []

    @pytest.mark.ckan_config('ckanext.qa.openness_mode', 'metadata_only')
    def test_metadata_only_does_not_queue_on_rollback(self, enqueue_calls):
        dataset = factories.Dataset(license_id='cc-by')
        enqueue_calls.clear()
        # Ανοιχτό transaction, ώστε το rollback να είναι πραγματικό
        model.Session.query(model.Package).first()
        qa_lib.queue_openness_after_commit(dataset['id'])
        model.Session.rollback()
        model.Session.commit()
        assert enqueue_calls.package_ids() == []

    @pytest.mark.ckan_config('ckanext.qa.openness_mode', 'metadata_only')
    def test_metadata_only_ignores_package_archived(self, enqueue_calls):
        dataset = factories.Dataset(license_id='cc-by', resources=[
            {'url': 'http://example.com/file.csv', 'format': 'CSV'}])
        enqueue_calls.clear()
        import ckanext.archiver.tasks
        ckanext.archiver.tasks.notify_package(dataset, 'priority')
        assert enqueue_calls.package_ids() == []

    @pytest.mark.ckan_config('ckanext.qa.openness_mode', 'metadata_only')
    def test_one_pending_job_per_dataset(self):
        '''Αλλαγές σε dataset του οποίου το QA job περιμένει ήδη στην ουρά δεν
        βάζουν δεύτερο job (π.χ. οι πολλές νυχτερινές αλλαγές των σταθμών ΕΜΥ).'''
        from rq.job import Job
        conn = job_dedup._redis()
        created = []

        def fake_enqueue(fn, args=None, queue=None, rq_kwargs=None, **kwargs):
            created.append(rq_kwargs['job_id'])
            conn.hset(Job.key_for(rq_kwargs['job_id']), mapping={'description': 'test', 'status': 'queued'})

        try:
            with mock.patch.object(qa_lib, 'enqueue_job', side_effect=fake_enqueue):
                dataset = factories.Dataset(license_id='cc-by', resources=[
                    {'url': 'http://example.com/file.csv', 'format': 'CSV'}])
                helpers.call_action('package_patch', id=dataset['id'], notes='1')
                helpers.call_action('resource_patch', id=dataset['resources'][0]['id'],
                                    description='2')
            assert len(created) == 1
        finally:
            for job_id in created:
                conn.delete(Job.key_for(job_id))

    def test_archival_does_not_queue_on_update(self, enqueue_calls):
        dataset = factories.Dataset(license_id='cc-by', resources=[
            {'url': 'http://example.com/file.csv', 'format': 'CSV'}])
        helpers.call_action('package_patch', id=dataset['id'], notes='changed')
        assert enqueue_calls.package_ids() == []

    def test_archival_queues_on_package_archived(self, enqueue_calls):
        dataset = factories.Dataset(license_id='cc-by', resources=[
            {'url': 'http://example.com/file.csv', 'format': 'CSV'}])
        import ckanext.archiver.tasks
        ckanext.archiver.tasks.notify_package(dataset, 'priority')
        assert enqueue_calls.package_ids() == [dataset['id']]
        assert enqueue_calls.all()[0]['queue'] == 'priority'


@pytest.mark.usefixtures('with_plugins', 'qa_tables', 'clean_index')
@pytest.mark.ckan_config('ckan.plugins', 'qa archiver report')
@pytest.mark.ckan_config('ckanext.qa.openness_mode', 'metadata_only')
class TestUpdatePackageMetadataOnly(object):

    def test_scores_saved_and_indexed(self, enqueue_calls):
        dataset = factories.Dataset(license_id='cc-by', resources=[
            {'url': 'http://example.com/file.pdf', 'format': 'PDF'},
            {'url': 'http://example.com/file.csv', 'format': 'CSV'},
        ])

        qa_tasks.update_package(dataset['id'])

        res_ids = [r['id'] for r in dataset['resources']]
        scores = [qa_model.QA.get_for_resource(res_id).openness_score
                  for res_id in res_ids]
        assert scores == [1, 3]

        shown = helpers.call_action('package_show', id=dataset['id'])
        assert shown['qa']['openness_score'] == 3

        found = helpers.call_action('package_search',
                                    fq='qa_openness_score:3')
        assert [p['id'] for p in found['results']] == [dataset['id']]

    def test_existing_mqa_only_row_gets_openness(self, enqueue_calls):
        dataset = factories.Dataset(license_id='cc-by', resources=[
            {'url': 'http://example.com/file.csv', 'format': 'CSV'}])
        res_id = dataset['resources'][0]['id']
        qa = qa_model.QA.create(res_id)
        qa.mqa_score = 80.0
        model.Session.add(qa)
        model.Session.commit()

        qa_tasks.update_package(dataset['id'])

        qa = qa_model.QA.get_for_resource(res_id)
        assert qa.openness_score == 3
        assert qa.mqa_score == 80.0

    def test_licence_vocabulary_loaded_once_per_job(self, enqueue_calls):
        '''Το λεξιλόγιο αδειών φορτώνεται μία φορά για όλους τους πόρους του
        dataset, όχι μία φορά ανά πόρο (2ο review, 13).'''
        dataset = factories.Dataset(license_id='cc-by', resources=[
            {'url': 'http://example.com/%d.csv' % i, 'format': 'CSV', 'license': 'cc-by'}
            for i in range(3)])
        with mock.patch.object(qa_tasks, '_get_licenses_from_vocabulary',
                               return_value=['cc-by']) as vocabulary:
            qa_tasks.update_package(dataset['id'])
            assert vocabulary.call_count == 1
            # Εκτός job, κάθε κλήση φορτώνει το λεξιλόγιο, όπως πριν
            qa_tasks._is_resource_license_open('cc-by')
            qa_tasks._is_resource_license_open('cc-by')
            assert vocabulary.call_count == 3
        scores = [qa_model.QA.get_for_resource(r['id']).openness_score
                  for r in dataset['resources']]
        assert scores == [3, 3, 3]


class TestAggregateWithNullRows(object):

    def test_null_openness_rows_are_ignored(self):
        rows = [
            SimpleNamespace(openness_score=None, openness_score_reason=None,
                            mqa_score=70.0, mqa_findability_score=1,
                            mqa_accessibility_score=1,
                            mqa_interoperability_score=1,
                            mqa_reusability_score=1,
                            mqa_contextuality_score=1, updated=None),
            SimpleNamespace(openness_score=2, openness_score_reason='xls',
                            mqa_score=None, updated=None),
        ]
        result = qa_model.aggregate_qa_for_a_dataset(rows)
        assert result['openness_score'] == 2
        assert result['mqa_score'] == 70.0


@pytest.mark.usefixtures('with_plugins', 'qa_tables')
@pytest.mark.ckan_config('ckan.plugins', 'qa archiver report')
class TestFullRecalculation(object):
    '''`ckan qa update --queue bulk` βάζει στην ουρά όλα τα ενεργά datasets.'''

    def test_all_datasets_go_to_logical_bulk_queue(self, enqueue_calls):
        resource = {'url': 'http://example.com/file.csv', 'format': 'CSV'}
        first = factories.Dataset(resources=[resource])
        second = factories.Dataset()
        enqueue_calls.clear()
        qa_utils.update([], 'bulk')
        assert set(enqueue_calls.package_ids()) == {first['id'], second['id']}
        assert {c['queue'] for c in enqueue_calls.all()} == {'bulk'}

    @pytest.mark.ckan_config('ckanext.qa.queue.bulk', 'qa_bulk')
    def test_bulk_maps_to_dedicated_qa_queue(self, enqueue_calls):
        dataset = factories.Dataset()
        enqueue_calls.clear()
        qa_utils.update([], 'bulk')
        assert enqueue_calls.package_ids() == [dataset['id']]
        assert enqueue_calls.all()[0]['queue'] == 'qa_bulk'
