# -*- coding: utf-8 -*-
'''
Tests που μεταφέρθηκαν από τα παλιά test_plugin.py, test_tasks.py και
test_action.py (Python 2, nose), για τη συμπεριφορά που δεν κάλυπταν τα tests
του OD-857: σχήμα του datastore και επιπλέον πεδία στο datapackage.json, hash
και canonization του datapackage, ZIP με τοπικό upload, job μετά από διαγραφή
πόρου και μετά από datastore_create.
'''
import copy
import io
from unittest import mock

import pytest
import responses
from werkzeug.datastructures import FileStorage

from ckan.tests import factories, helpers

from ckanext.downloadall import action, eligibility, tasks
from ckanext.downloadall.tests.test_od857_build import _by_status, _read, _zip_of

CSV = b'Date,Price\n1/6/2017,4.00\n2/6/2017,4.12\n'

REMOTE = {
    'name': 'gold-prices',
    'resources': [{'format': 'CSV', 'name': 'annual',
                   'path': 'https://example.test/annual.csv'}],
}
LOCAL = {
    'name': 'gold-prices',
    'resources': [{'format': 'CSV', 'name': 'annual', 'path': 'annual.csv',
                   'sources': [{'title': 'Gold Price Annual',
                                'path': 'https://example.test/annual.csv'}]}],
}


def _datastore_fields(ckan, res):
    res['datastore_fields'] = [{'type': 'int', 'id': '_id'},
                               {'type': 'text', 'id': 'Date'},
                               {'type': 'text', 'id': 'Price'}]


class TestDatapackageHelpers(object):

    def test_local_path_points_into_the_zip(self):
        datapackage = copy.deepcopy(REMOTE)
        tasks.save_local_path_in_datapackage_resource(
            datapackage['resources'][0], {'title': 'Gold Price Annual'}, 'annual.csv')
        assert datapackage == LOCAL

    def test_canonized_local_and_remote_are_equal(self):
        assert tasks.canonized_datapackage(LOCAL) == REMOTE
        assert tasks.canonized_datapackage(REMOTE) == REMOTE

    def test_hash_is_repeatable(self):
        # Ίδιο σε κάθε μηχάνημα και έκδοση Python
        assert tasks.hash_datapackage({'resources': []}) == \
            '60482792d5032e490cdde4f759e84fd6'

    def test_hash_ignores_key_order(self):
        assert tasks.hash_datapackage({'resources': [{'format': 'CSV', 'name': 'a'}]}) == \
            tasks.hash_datapackage({'resources': [{'name': 'a', 'format': 'CSV'}]})


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestDatapackage(object):

    def test_datastore_schema_is_included(self):
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/data.csv',
                                                'format': 'CSV'}])
        included, _ = eligibility.split_resources(dataset)
        with mock.patch('ckanapi.datapackage.populate_datastore_res_fields',
                        side_effect=_datastore_fields):
            datapackage, _ = tasks.generate_datapackage(dataset, included)
        assert datapackage['resources'][0]['schema'] == {'fields': [
            {'type': 'string', 'name': 'Date'}, {'type': 'string', 'name': 'Price'}]}

    @pytest.mark.ckan_config('ckanext.downloadall.dataset_fields_to_add_to_datapackage',
                             'num_resources type')
    def test_configured_dataset_fields_are_added(self):
        dataset = helpers.call_action('package_show', id=factories.Dataset()['id'])
        datapackage, _ = tasks.generate_datapackage(dataset, [])
        assert (datapackage['num_resources'], datapackage['type']) == (0, 'dataset')


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestBuildAndQueue(object):

    def test_local_upload_is_included(self):
        dataset = factories.Dataset()
        helpers.call_action('resource_create', package_id=dataset['id'], url='prices.csv',
                            format='CSV', upload=FileStorage(io.BytesIO(CSV), 'prices.csv'))
        tasks.update_zip(dataset['id'])
        names, manifest, _ = _read(_zip_of(dataset['id'])[1])
        assert 'prices.csv' in names
        assert [e['filename'] for e in _by_status(manifest)['included']] == ['prices.csv']

    def test_deleting_a_resource_rebuilds_the_zip(self, http, enqueue_calls):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/b.csv', body=CSV)
        dataset = factories.Dataset(resources=[
            {'url': 'https://example.test/a.csv', 'format': 'CSV'},
            {'url': 'https://example.test/b.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        del enqueue_calls[:]
        helpers.call_action('resource_delete', id=dataset['resources'][1]['id'])
        assert enqueue_calls.package_ids() == [dataset['id']]
        tasks.update_zip(dataset['id'])
        _, manifest, _ = _read(_zip_of(dataset['id'])[1])
        assert [e['id'] for e in manifest['resources']] == [dataset['resources'][0]['id']]

    def test_datastore_create_queues_a_job(self, enqueue_calls):
        '''Π.χ. το xloader φορτώνει τον πόρο ή αλλάζει το λεξικό δεδομένων.'''
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv',
                                                'format': 'CSV'}])
        del enqueue_calls[:]
        original = mock.Mock(return_value={'resource_id': 'x'})
        result = action.datastore_create(
            original, {}, {'resource_id': dataset['resources'][0]['id']})
        assert result == {'resource_id': 'x'}
        assert enqueue_calls.package_ids() == [dataset['id']]
