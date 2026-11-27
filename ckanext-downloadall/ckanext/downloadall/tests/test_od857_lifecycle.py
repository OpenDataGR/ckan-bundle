# -*- coding: utf-8 -*-
'''
Tests για την ασφαλή αντικατάσταση του ZIP στο cloud storage (OD-857): το
προηγούμενο blob σβήνεται μόνο αφού αποθηκευτεί το νέο, και μόνο αυτό· οι
αποτυχίες διαγραφής ξαναδοκιμάζονται. Το container του cloudstorage είναι
ψεύτικο· το ZIP αποθηκεύεται στην τοπική αποθήκευση του CKAN.
'''
import itertools
import os
from types import SimpleNamespace
from unittest import mock

import ckanapi
import pytest
import responses
from libcloud.storage.types import ObjectDoesNotExistError

from ckan.lib.uploader import get_resource_uploader
from ckan.plugins import toolkit
from ckan.tests import factories, helpers

from ckanext.downloadall import cli, freshness, storage, tasks

CSV = b'a,b\n1,2\n'
HVD = '["http://data.europa.eu/bna/c_ac64a52d"]'


class FakeContainer(object):
    '''Τα ZIP των tests αποθηκεύονται στην τοπική αποθήκευση του CKAN· ένα blob
    έχει το μέγεθος του τοπικού αρχείου του πόρου.'''

    def __init__(self):
        self.deleted = []
        self.fail = False
        self.missing = set()    # blobs που δεν υπάρχουν
        self.wrong_size = False

    def get_object(self, path):
        if self.fail:
            raise RuntimeError('storage unavailable')
        if path in self.missing:
            raise ObjectDoesNotExistError('missing', None, path)
        resource_id = path.split('/')[1]
        local = get_resource_uploader({'id': resource_id}).get_path(resource_id)
        size = os.path.getsize(local) if os.path.exists(local) else 0
        return SimpleNamespace(name=path, size=size + 1 if self.wrong_size else size)

    def delete_object(self, obj):
        self.deleted.append(obj.name)


@pytest.fixture
def cloud(monkeypatch):
    fake = SimpleNamespace(container=FakeContainer(), leave_files=False)
    monkeypatch.setattr(storage, 'cloudstorage_enabled', lambda: True)
    monkeypatch.setattr(storage, '_cloud_storage', lambda: fake)
    counter = itertools.count(1)
    # Διαφορετικό όνομα σε κάθε build (στην πράξη: χρονοσφραγίδα)
    monkeypatch.setattr(tasks, 'zip_filename', lambda name: '%s-%d.zip' % (name, next(counter)))
    return fake


def _zip(dataset_id):
    return freshness.zip_resource(helpers.call_action('package_show', id=dataset_id))


def _dataset(http):
    http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
    http.add(responses.GET, 'https://example.test/b.csv', body=CSV)
    return factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])


def _change(dataset):
    resource_id = helpers.call_action('package_show', id=dataset['id'])['resources'][0]['id']
    helpers.call_action('resource_patch', id=resource_id, url='https://example.test/b.csv')


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestReplacement(object):

    def test_previous_blob_deleted_after_success(self, http, cloud):
        dataset = _dataset(http)
        tasks.update_zip(dataset['id'])
        first = _zip(dataset['id'])
        assert cloud.container.deleted == []

        _change(dataset)
        tasks.update_zip(dataset['id'])
        second = _zip(dataset['id'])
        assert second['id'] == first['id']
        assert storage.upload_filename(second) != storage.upload_filename(first)
        assert cloud.container.deleted == [
            'resources/%s/%s' % (first['id'], storage.upload_filename(first))]

    def test_nothing_deleted_when_saving_fails(self, http, cloud):
        dataset = _dataset(http)
        tasks.update_zip(dataset['id'])
        first = _zip(dataset['id'])
        _change(dataset)

        real = ckanapi.LocalCKAN()
        failing = SimpleNamespace(action=SimpleNamespace(
            resource_patch=mock.Mock(side_effect=toolkit.ValidationError(
                {'notes_translated-el': ['Missing value']})),
            resource_create=real.action.resource_create))
        with mock.patch.object(tasks, '_site_ckan', return_value=failing):
            with pytest.raises(toolkit.ValidationError):
                tasks.update_zip(dataset['id'])
        assert cloud.container.deleted == []
        assert _zip(dataset['id'])['url'] == first['url']

    def test_same_filename_is_not_deleted(self, http, cloud, monkeypatch):
        monkeypatch.setattr(tasks, 'zip_filename', lambda name: 'roads.zip')
        dataset = _dataset(http)
        tasks.update_zip(dataset['id'])
        _change(dataset)
        tasks.update_zip(dataset['id'])
        assert cloud.container.deleted == []

    def test_failed_deletion_is_retried_later(self, http, cloud):
        dataset = _dataset(http)
        tasks.update_zip(dataset['id'])
        first = _zip(dataset['id'])
        _change(dataset)
        cloud.container.fail = True
        tasks.update_zip(dataset['id'])
        assert storage.upload_filename(first) in _zip(dataset['id'])['downloadall_cleanup_pending']

        cloud.container.fail = False
        tasks.update_zip(dataset['id'])  # χωρίς αλλαγές: μόνο ο καθαρισμός
        assert cloud.container.deleted == [
            'resources/%s/%s' % (first['id'], storage.upload_filename(first))]
        assert not _zip(dataset['id'])['downloadall_cleanup_pending']

    def test_previous_blob_kept_until_the_new_one_is_verified(self, http, cloud):
        '''Handoff §5: το παλιό blob σβήνεται μόνο αφού βρεθεί το νέο στο
        storage· ως τότε μένει για επόμενη προσπάθεια.'''
        dataset = _dataset(http)
        tasks.update_zip(dataset['id'])
        first = _zip(dataset['id'])
        _change(dataset)
        new_file = '%s-2.zip' % dataset['name']
        cloud.container.missing.add('resources/%s/%s' % (first['id'], new_file))
        tasks.update_zip(dataset['id'])
        second = _zip(dataset['id'])
        assert storage.upload_filename(second) == new_file
        assert cloud.container.deleted == []
        assert storage.upload_filename(first) in second['downloadall_cleanup_pending']

        tasks.update_zip(dataset['id'])  # χωρίς αλλαγές· το νέο λείπει ακόμη
        assert cloud.container.deleted == []

        cloud.container.missing.clear()
        tasks.update_zip(dataset['id'])
        assert cloud.container.deleted == [
            'resources/%s/%s' % (first['id'], storage.upload_filename(first))]
        assert not _zip(dataset['id'])['downloadall_cleanup_pending']

    def test_previous_blob_kept_when_the_new_one_has_another_size(self, http, cloud):
        dataset = _dataset(http)
        tasks.update_zip(dataset['id'])
        first = _zip(dataset['id'])
        _change(dataset)
        cloud.container.wrong_size = True
        tasks.update_zip(dataset['id'])
        assert cloud.container.deleted == []
        assert storage.upload_filename(first) in _zip(dataset['id'])['downloadall_cleanup_pending']

        tasks.update_zip(dataset['id'])  # χωρίς αλλαγές· το μέγεθος διαφέρει ακόμη
        assert cloud.container.deleted == []

        cloud.container.wrong_size = False
        tasks.update_zip(dataset['id'])
        assert cloud.container.deleted == [
            'resources/%s/%s' % (first['id'], storage.upload_filename(first))]

    def test_leave_files_keeps_the_blob(self, http, cloud):
        cloud.leave_files = True
        dataset = _dataset(http)
        tasks.update_zip(dataset['id'])
        _change(dataset)
        tasks.update_zip(dataset['id'])
        assert cloud.container.deleted == []
        assert not _zip(dataset['id'])['downloadall_cleanup_pending']


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestCleanupPlan(object):
    '''Η εντολή cleanup: τι θα σβηνόταν (dry-run).'''

    def _zip_resource(self, dataset_id, **extra):
        return helpers.call_action(
            'resource_create', package_id=dataset_id, url='https://example.test/old.zip',
            format='ZIP', downloadall_metadata_modified='2026-01-01T00:00:00', **extra)

    def test_zip_of_dataset_that_is_not_eligible(self):
        dataset = factories.Dataset()
        zip_res = self._zip_resource(dataset['id'])
        with mock.patch.dict('ckan.plugins.toolkit.config', {'ckanext.downloadall.hvd_only': 'true'}):
            zip_resources, blobs = cli._cleanup_plan()
        assert [(z['resource_id'], z['reason']) for z in zip_resources] == \
            [(zip_res['id'], 'not a high-value dataset')]

    def test_duplicate_zips_keep_the_one_the_job_maintains(self):
        '''Review #1: η σελίδα, το job και το cleanup διαλέγουν το ίδιο ZIP
        (το πρώτο με τη σειρά των πόρων)· σβήνεται το άλλο.'''
        from ckanext.downloadall import helpers as dl_helpers
        dataset = factories.Dataset(extras=[{'key': 'hvd_category', 'value': HVD}])
        first = self._zip_resource(dataset['id'])
        second = self._zip_resource(dataset['id'])
        zip_resources, _ = cli._cleanup_plan()
        assert [(z['resource_id'], z['reason']) for z in zip_resources] == \
            [(second['id'], 'duplicate zip')]
        shown = helpers.call_action('package_show', id=dataset['id'])
        assert freshness.zip_resource(shown)['id'] == first['id']
        assert dl_helpers.pop_zip_resource(shown)['id'] == first['id']
        assert shown['resources'] == []

    def test_apply_continues_after_a_failed_item(self, monkeypatch):
        '''#15: σφάλμα σε ένα στοιχείο καταγράφεται και η εκτέλεση συνεχίζει·
        μετρώνται μόνο οι επιτυχημένες διαγραφές.'''
        first = self._zip_resource(factories.Dataset()['id'])
        second = self._zip_resource(factories.Dataset()['id'])
        zip_resources = [{'resource_id': 'no-such-resource'},
                         {'resource_id': first['id']}, {'resource_id': second['id']}]
        blobs = [{'resource_id': first['id'], 'filename': 'old.zip'}]
        monkeypatch.setattr(storage, 'delete_upload_blob', lambda rid, name: False)
        deleted, failed = cli._apply_cleanup(zip_resources, blobs, limit=0)
        assert (deleted, failed) == (2, 2)
        assert zip_resources[0]['deleted'] is False and zip_resources[0]['error']
        assert zip_resources[1]['deleted'] and zip_resources[2]['deleted']
        assert blobs[0]['deleted'] is False

    def test_apply_limit_counts_successful_deletions(self):
        resources = [self._zip_resource(factories.Dataset()['id']) for _ in range(2)]
        zip_resources = [{'resource_id': 'no-such-resource'}] + \
            [{'resource_id': r['id']} for r in resources]
        assert cli._apply_cleanup(zip_resources, [], limit=1) == (1, 1)
        assert 'deleted' not in zip_resources[2]

    def test_only_superseded_blobs_of_current_zips(self, http, cloud, monkeypatch):
        dataset = _dataset(http)
        tasks.update_zip(dataset['id'])
        current = _zip(dataset['id'])
        current_file = storage.upload_filename(current)
        monkeypatch.setattr(storage, 'iterate_zip_blobs', lambda ids: iter([
            (current['id'], current_file), (current['id'], 'roads-old.zip')]))
        _, blobs = cli._cleanup_plan()
        assert blobs == [{'resource_id': current['id'], 'filename': 'roads-old.zip'}]

    def test_apply_keeps_superseded_blob_while_current_zip_is_missing(self, http, cloud):
        '''Handoff §5: παλιό blob σβήνεται μόνο αν το τρέχον ZIP υπάρχει.'''
        dataset = _dataset(http)
        tasks.update_zip(dataset['id'])
        current = _zip(dataset['id'])
        cloud.container.missing.add(
            'resources/%s/%s' % (current['id'], storage.upload_filename(current)))
        blobs = [{'resource_id': current['id'], 'filename': 'roads-old.zip'}]
        assert cli._apply_cleanup([], blobs, limit=0) == (0, 0)
        assert cloud.container.deleted == []
        assert blobs[0]['skipped'] == 'current zip not verified'

        cloud.container.missing.clear()
        assert cli._apply_cleanup([], blobs, limit=0) == (1, 0)
        assert cloud.container.deleted == ['resources/%s/roads-old.zip' % current['id']]
