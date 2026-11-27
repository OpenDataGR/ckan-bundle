# -*- coding: utf-8 -*-
'''
Tests για το τρίτο code review του OD-857 (19/11) και το handoff (§3): μετάβαση
των παλιών ZIP (#9), όριο του --retry-failed (#1, #2, #7), hash χωρίς τίτλο
άδειας (#4), cleanup_pending (#5), επανέλεγχος του dataset πριν την
αποθήκευση (#3, #6) και μικρότερα (#8, #10, #11, #12, #13).
'''
import zipfile
from time import monotonic
from unittest import mock

import pytest
import responses
import sqlalchemy as sa

from ckan import model
from ckan.plugins import toolkit
from ckan.tests import factories, helpers

from ckanext.downloadall import cli, dedup, freshness, lib, tasks
from ckanext.downloadall.tests.test_od857_build import _zip_of
from ckanext.downloadall.tests.test_od857_rules import _dataset

CSV = b'a,b\n1,2\n'
HVD = '["http://data.europa.eu/bna/c_ac64a52d"]'


def _sql(statement, **params):
    '''Αλλαγή από άλλη διεργασία (άλλη σύνδεση, ήδη commit).'''
    with model.meta.engine.begin() as conn:
        conn.execute(sa.text(statement), params)


def _zip_resources(dataset_id):
    shown = helpers.call_action('package_show', id=dataset_id)
    return [r for r in shown['resources'] if r.get('downloadall_metadata_modified')]


def _zip_file(tmp_path):
    path = tmp_path / 'build.zip'
    with zipfile.ZipFile(str(path), 'w') as zipf:
        zipf.writestr('a.csv', CSV)
    return str(path)


class TestLegacyZips(object):
    '''#9: τα ZIP από πριν το OD-857 δεν ξαναχτίζονται αυτόματα (handoff:
    «δεν διαγράφονται παλιά ZIP ή blobs αυτόματα κατά το deployment»).'''

    def test_retry_failed_treats_a_legacy_zip_as_current(self):
        dataset = _dataset()
        dataset['resources'].append({'id': 'zip', 'url': 'old.zip',
                                     'downloadall_metadata_modified': 'x'})
        assert not freshness.needs_retry(dataset)
        assert freshness.zip_state(dataset) == 'ready'

    def test_hash_ignores_the_licence_title_and_url(self):
        '''#4: όπως στο fingerprint.'''
        def package(**license_):
            return {'name': 'roads', 'license': license_, 'resources': []}
        assert tasks.hash_datapackage(package(type='cc-by', title='Attribution', url='http://a')) == \
            tasks.hash_datapackage(package(type='cc-by', title=u'Αναφορά', url='https://b'))
        assert tasks.hash_datapackage(package(type='cc-by')) != \
            tasks.hash_datapackage(package(type='cc-by-sa'))


class TestRetryLimits(object):

    def _with_zip(self, dataset, **fields):
        dataset['resources'].append(dict(
            {'id': 'zip', 'url': 'roads.zip', 'downloadall_metadata_modified': 'x',
             'downloadall_fingerprint': freshness.compute_fingerprint(dataset)}, **fields))
        return dataset

    def test_failed_rebuilds_of_the_current_version_count(self):
        '''#2: ZIP με προσωρινή αποτυχία· οι νέες προσπάθειες της ίδιας
        εκδοχής απέτυχαν όλες (π.χ. validation) και μετρούν στο όριο.'''
        def zip_with(attempts):
            dataset = _dataset()
            return self._with_zip(
                dataset, downloadall_failed='1', downloadall_failed_transient='1',
                downloadall_retries='1',
                downloadall_attempted_fingerprint=freshness.compute_fingerprint(dataset),
                downloadall_attempts=attempts)
        assert freshness.needs_retry(zip_with('1'))
        assert not freshness.needs_retry(zip_with('2'))


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestRetryWithoutZip(object):

    def test_failed_builds_without_a_zip_stop_at_the_limit(self, http):
        '''#1: dataset χωρίς ZIP που αποτυγχάνει πάντα (π.χ. 404): η πρώτη
        αποτυχία και 3 νέες προσπάθειες, όχι κάθε βράδυ για πάντα.'''
        http.add(responses.GET, 'https://example.test/gone.csv', status=404)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/gone.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        for _ in range(3):
            assert freshness.needs_retry(helpers.call_action('package_show', id=dataset['id']))
            tasks.update_zip(dataset['id'], None, False)
        assert not freshness.needs_retry(helpers.call_action('package_show', id=dataset['id']))
        assert dedup.no_zip_attempts(dataset['id'])[1] == 4

    def test_build_that_fails_with_an_error_counts_too(self, http):
        '''Π.χ. το dataset δεν περνά validation στην αποθήκευση του πρώτου ZIP.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        with mock.patch.object(tasks, 'save_zip',
                               side_effect=toolkit.ValidationError({'title': ['missing']})):
            with pytest.raises(toolkit.ValidationError):
                tasks.update_zip(dataset['id'])
        assert dedup.no_zip_attempts(dataset['id'])[1] == 1

    def test_a_change_or_a_success_resets_it(self, http):
        http.add(responses.GET, 'https://example.test/gone.csv', status=404)
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/gone.csv', 'format': 'CSV'}])
        for _ in range(4):
            tasks.update_zip(dataset['id'], None, False)
        helpers.call_action('resource_patch', id=dataset['resources'][0]['id'],
                            url='https://example.test/a.csv')
        assert freshness.needs_retry(helpers.call_action('package_show', id=dataset['id']))
        tasks.update_zip(dataset['id'])
        assert dedup.no_zip_attempts(dataset['id']) == (None, 0)

    def test_only_forced_builds_count_as_retries(self, http):
        '''#7: ένα rebuild επειδή άλλαξε μόνο το hash του datapackage (π.χ.
        σχήμα του datastore) δεν τρώει από το όριο του --retry-failed.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/down.csv', status=503)
        dataset = factories.Dataset(resources=[
            {'url': 'https://example.test/a.csv', 'format': 'CSV'},
            {'url': 'https://example.test/down.csv', 'format': 'CSV'}])

        def retries():
            return freshness.build_count(_zip_of(dataset['id'])[1], freshness.RETRIES_FIELD)

        tasks.update_zip(dataset['id'])
        with mock.patch.object(tasks, 'hash_datapackage', return_value='other'):
            tasks.update_zip(dataset['id'])
        assert retries() == 0
        tasks.update_zip(dataset['id'], None, False)
        assert retries() == 1


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestSaveRecheck(object):
    '''Handoff §3: πριν ενεργοποιηθεί το νέο ZIP επανελέγχεται το dataset.'''

    def _dataset(self, http):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/b.csv', body=CSV)
        return factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])

    def _change_during_build(self, statement, **params):
        original = tasks.write_zip

        def write_zip_and_change(*args, **kwargs):
            manifest = original(*args, **kwargs)
            _sql(statement, **params)
            return manifest
        return mock.patch.object(tasks, 'write_zip', side_effect=write_zip_and_change)

    def test_dataset_made_private_during_the_build_gets_no_zip(self, http, enqueue_calls):
        '''#6'''
        dataset = self._dataset(http)
        del enqueue_calls[:]
        # Όπως το package_update: αλλάζει και το metadata_modified
        with self._change_during_build(
                'UPDATE package SET private = true, metadata_modified = now() WHERE id = :id',
                id=dataset['id']):
            tasks.update_zip(dataset['id'])
        model.Session.expire_all()
        assert _zip_resources(dataset['id']) == []
        assert dataset['id'] in enqueue_calls.package_ids()

    def test_older_build_does_not_overwrite_a_newer_zip(self, http, tmp_path):
        '''#3: π.χ. δύο jobs με request_cache· το νεότερο αποθήκευσε πρώτο.'''
        dataset = self._dataset(http)
        tasks.update_zip(dataset['id'])
        old_view = helpers.call_action('package_show', id=dataset['id'])
        old_fingerprint = freshness.compute_fingerprint(old_view)
        helpers.call_action('resource_patch', id=dataset['resources'][0]['id'],
                            url='https://example.test/b.csv')
        tasks.update_zip(dataset['id'])
        newer = _zip_of(dataset['id'])[1]
        assert tasks.save_zip(old_view, None, _zip_file(tmp_path), old_fingerprint, 'hash',
                              {'included': 1, 'excluded': 0, 'failed': 0}) is None
        assert _zip_of(dataset['id'])[1]['downloadall_fingerprint'] == \
            newer['downloadall_fingerprint']

    def test_changed_during_the_build_is_saved_as_not_current(self, http, enqueue_calls):
        '''Το ZIP της εκδοχής που χτίστηκε αποθηκεύεται, δεν φαίνεται ενημερωμένο,
        και ακολουθεί νέα επεξεργασία.'''
        dataset = self._dataset(http)
        del enqueue_calls[:]
        with self._change_during_build(
                "UPDATE package SET title = 'Changed', metadata_modified = now() WHERE id = :id",
                id=dataset['id']):
            tasks.update_zip(dataset['id'])
        model.Session.expire_all()
        shown, zip_res = _zip_of(dataset['id'])
        assert zip_res and freshness.zip_state(shown) == 'stale'
        assert dataset['id'] in enqueue_calls.package_ids()

    def test_cleanup_pending_does_not_overwrite_a_newer_save(self, http):
        '''#5: το cleanup_pending γράφεται μόνο του, με νέα ανάγνωση.'''
        dataset = self._dataset(http)
        tasks.update_zip(dataset['id'])
        zip_id = _zip_of(dataset['id'])[1]['id']
        resource = model.Session.query(model.Resource).get(zip_id)
        resource.extras = dict(resource.extras, downloadall_cleanup_pending='["old.zip"]')
        model.Session.commit()
        assert resource.url  # φορτωμένο στο session, όπως σε ένα job
        _sql("UPDATE resource SET url = 'newer.zip' WHERE id = :id", id=zip_id)
        tasks._store_pending(zip_id, ['old.zip'], [])
        model.Session.expire_all()
        saved = model.Session.query(model.Resource).get(zip_id)
        assert saved.url == 'newer.zip'
        assert not saved.extras.get('downloadall_cleanup_pending')

    @pytest.mark.ckan_config('ckanext.downloadall.hvd_only', 'true')
    def test_every_zip_is_removed_when_the_dataset_is_not_eligible(self):
        '''#11: και τα διπλά ZIP.'''
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        for _ in range(2):
            helpers.call_action('resource_create', package_id=dataset['id'],
                                url='https://example.test/old.zip', format='ZIP',
                                downloadall_metadata_modified='2026-01-01T00:00:00')
        assert len(_zip_resources(dataset['id'])) == 2
        tasks.update_zip(dataset['id'])
        assert _zip_resources(dataset['id']) == []


@pytest.mark.usefixtures('with_plugins')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestSmallFixes(object):

    def test_uploader_error_fails_only_the_resource(self, tmp_path):
        '''#8'''
        resource = {'id': 'r1', 'url': 'x.csv', 'url_type': 'upload', 'format': 'CSV'}
        with zipfile.ZipFile(str(tmp_path / 'a.zip'), 'w') as zipf, \
                mock.patch.object(tasks, '_local_upload_path',
                                  side_effect=PermissionError('storage')):
            with pytest.raises(tasks.DownloadError):
                tasks.download_resource_into_zip(resource, 0, zipf, set(), str(tmp_path))

    def test_small_timeout_still_leaves_time(self):
        '''#10: το περιθώριο δεν ξεπερνά το μισό του timeout.'''
        start = monotonic()
        assert 45 < tasks.job_deadline(100) - start <= 50.5
        assert 1615 < tasks.job_deadline(1800) - start <= 1620.5
        assert tasks.job_deadline(None) is None

    def test_synchronous_runs_have_a_time_limit(self):
        '''#12'''
        with mock.patch.object(tasks, '_update_zip_once') as update_once:
            tasks.update_zip('dataset-id', timeout=600)
        assert update_once.call_args.args[3] is not None
        with mock.patch.object(cli.tasks, 'update_zip') as update_zip, \
                mock.patch.object(cli.model.Package, 'get',
                                  return_value=mock.Mock(state='active', type='dataset',
                                                         extras={}, private=False, name='x')):
            cli._update_one('dataset-id', {'queued': 0, 'skipped': 0, 'current': 0},
                            synchronous=True, dry_run=False, retry_failed=False)
        assert update_zip.call_args.kwargs['timeout'] == cli._sync_timeout()


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'clean_dedup_keys', 'with_request_context')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
@pytest.mark.ckan_config('ckanext.downloadall.dedup_strategy', 'redis')
class TestRedisFallback(object):

    def test_commit_enqueue_is_not_dropped_when_redis_fails(self, enqueue_calls):
        '''#13: όπως και χωρίς σφάλμα, το enqueue μετά από commit δεν
        χάνεται επειδή το dataset μπήκε νωρίτερα στο ίδιο αίτημα.'''
        dataset = factories.Dataset()
        del enqueue_calls[:]
        with mock.patch.object(dedup, 'mark_dirty_and_acquire',
                               side_effect=dedup.RedisDedupError('down')):
            assert lib.enqueue_zip(dataset['id']) == lib.QUEUED
            assert lib.enqueue_zip(dataset['id'], per_request=False) == lib.QUEUED
            assert lib.enqueue_zip(dataset['id']) == lib.ALREADY_QUEUED
        assert len(enqueue_calls) == 2
