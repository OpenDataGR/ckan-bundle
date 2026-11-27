# -*- coding: utf-8 -*-
'''
Tests για τη δημιουργία του ZIP (OD-857): manifest, ονόματα αρχείων, μερική
επιτυχία, όρια, χρονικό όριο, fingerprint και HVD. Το HTTP είναι ψεύτικο
(responses) και το ZIP αποθηκεύεται στην τοπική αποθήκευση του CKAN.
'''
import json
import re
import zipfile
from time import monotonic
from unittest import mock

import pytest
import requests
import responses
from rq.timeouts import JobTimeoutException

from ckan.lib.uploader import get_resource_uploader
from ckan.plugins import toolkit
from ckan.tests import factories, helpers

from ckanext.downloadall import eligibility, freshness, tasks

HVD = '["http://data.europa.eu/bna/c_ac64a52d"]'
CSV = b'a,b\n1,2\n'


def _zip_of(dataset_id):
    dataset = helpers.call_action('package_show', id=dataset_id)
    return dataset, freshness.zip_resource(dataset)


def _read(zip_res):
    path = get_resource_uploader(dict(zip_res)).get_path(zip_res['id'])
    with zipfile.ZipFile(path) as zipf:
        manifest = json.loads(zipf.read('downloadall-manifest.json'))
        datapackage = json.loads(zipf.read('datapackage.json'))
        return sorted(zipf.namelist()), manifest, datapackage


def _by_status(manifest):
    result = {}
    for entry in manifest['resources']:
        result.setdefault(entry['status'], []).append(entry)
    return result


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestBuild(object):

    @pytest.mark.ckan_config('ckanext.downloadall.exclude_resource_formats', 'API')
    def test_zip_with_manifest_names_and_partial_success(self, http):
        http.add(responses.GET, 'https://example.test/roads.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/api/', body=CSV,
                 content_type='text/csv')
        http.add(responses.GET, 'https://example.test/gone.csv', status=404)
        dataset = factories.Dataset(resources=[
            {'url': 'https://example.test/roads.csv', 'format': 'CSV', 'name': 'Roads'},
            # Χωρίς κατάληξη και χωρίς format: πριν έριχνε όλο το job (KeyError: 'format')
            {'url': 'https://example.test/api/', 'name': ''},
            {'url': 'https://example.test/gone.csv', 'format': 'CSV', 'name': 'Gone'},
            {'url': 'https://example.test/service', 'format': 'API', 'name': 'Service'},
        ])

        tasks.update_zip(dataset['id'])

        shown, zip_res = _zip_of(dataset['id'])
        assert zip_res['downloadall_fingerprint'] == freshness.compute_fingerprint(shown)
        assert (int(zip_res['downloadall_included']), int(zip_res['downloadall_excluded']),
                int(zip_res['downloadall_failed'])) == (2, 1, 1)
        names, manifest, datapackage = _read(zip_res)
        assert names == ['datapackage.json', 'downloadall-manifest.json',
                         'resource-2.csv', 'roads.csv']
        statuses = _by_status(manifest)
        assert [e['filename'] for e in statuses['included']] == ['roads.csv', 'resource-2.csv']
        assert statuses['failed'][0]['reason'] == 'HTTP 404'
        assert statuses['excluded'][0]['reason'] == 'excluded format'
        # Στο datapackage.json οι πόροι που μπήκαν δείχνουν στο αρχείο μέσα στο ZIP
        paths = [r['path'] for r in datapackage['resources']]
        assert paths[:2] == ['roads.csv', 'resource-2.csv']
        assert paths[2] == 'https://example.test/gone.csv'
        assert freshness.zip_state(shown) == 'ready'

    def test_transient_failure_is_retried(self, http):
        http.add(responses.GET, 'https://example.test/a.csv', status=503)
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        _, zip_res = _zip_of(dataset['id'])
        assert int(zip_res['downloadall_included']) == 1

    def test_timeout_is_a_failed_resource_not_a_failed_job(self, http):
        http.add(responses.GET, 'https://example.test/slow.csv',
                 body=requests.exceptions.ReadTimeout('slow'))
        http.add(responses.GET, 'https://example.test/ok.csv', body=CSV)
        dataset = factories.Dataset(resources=[
            {'url': 'https://example.test/slow.csv', 'format': 'CSV'},
            {'url': 'https://example.test/ok.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        _, zip_res = _zip_of(dataset['id'])
        _, manifest, _ = _read(zip_res)
        statuses = _by_status(manifest)
        assert len(statuses['included']) == 1
        assert statuses['failed'][0]['reason'].startswith('connection failed')

    def test_manifest_hides_secrets(self, http):
        url = 'https://user:pass@example.test/a.csv?sig=SECRET&year=2026'
        # Το responses δεν ταιριάζει URL με στοιχεία σύνδεσης σε απλό string
        http.add(responses.GET, re.compile(r'https://.*example\.test/a\.csv.*'), body=CSV)
        dataset = factories.Dataset(resources=[{'url': url, 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        _, manifest, _ = _read(_zip_of(dataset['id'])[1])
        assert manifest['resources'][0]['url'] == \
            'https://example.test/a.csv?sig=REDACTED&year=2026'

    @pytest.mark.ckan_config('ckanext.downloadall.max_resource_size', '5')
    def test_size_limit(self, http):
        http.add(responses.GET, 'https://example.test/big.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/small.csv', body=b'a\n1\n')
        dataset = factories.Dataset(resources=[
            {'url': 'https://example.test/big.csv', 'format': 'CSV'},
            {'url': 'https://example.test/small.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        _, manifest, _ = _read(_zip_of(dataset['id'])[1])
        assert manifest['resources'][0]['status'] == 'failed'
        assert manifest['resources'][0]['reason'].startswith('larger than the limit')
        assert manifest['resources'][1]['status'] == 'included'

    def test_time_limit_before_the_job_timeout(self, tmp_path):
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        included, excluded = eligibility.split_resources(dataset)
        datapackage, pairs = tasks.generate_datapackage(dataset, included)
        manifest = tasks.write_zip(str(tmp_path / 'a.zip'), dataset, datapackage, pairs,
                                   excluded, str(tmp_path), deadline=monotonic() - 1)
        assert manifest['resources'][0] == dict(manifest['resources'][0],
                                                status='failed', reason='time limit')

    def test_no_zip_when_nothing_could_be_downloaded(self, http):
        '''#10: όχι ZIP μόνο με μεταδεδομένα· το job δεν αποτυγχάνει.'''
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        with mock.patch.object(tasks, 'job_deadline', return_value=monotonic() - 1):
            tasks.update_zip(dataset['id'])
        assert _zip_of(dataset['id'])[1] is None

    def test_api_resources_are_included_by_default(self, http):
        '''Όπως πριν το OD-857, χωρίς ρύθμιση δεν αποκλείεται καμία μορφή.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/service', body=CSV)
        dataset = factories.Dataset(resources=[
            {'url': 'https://example.test/a.csv', 'format': 'CSV'},
            {'url': 'https://example.test/service', 'format': 'API'}])
        tasks.update_zip(dataset['id'])
        zip_res = _zip_of(dataset['id'])[1]
        assert (int(zip_res['downloadall_included']),
                int(zip_res['downloadall_excluded'])) == (2, 0)

    @pytest.mark.ckan_config('ckanext.downloadall.exclude_resource_formats', 'API')
    def test_no_zip_when_every_resource_is_excluded(self, http):
        '''#10: π.χ. μόνο πόροι API· το υπάρχον ZIP σβήνεται.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        assert _zip_of(dataset['id'])[1] is not None
        resource_id = _zip_of(dataset['id'])[0]['resources'][0]['id']
        helpers.call_action('resource_patch', id=resource_id, format='API')
        tasks.update_zip(dataset['id'])
        shown, zip_res = _zip_of(dataset['id'])
        assert zip_res is None
        assert freshness.zip_state(shown) == 'hidden'

    @pytest.mark.parametrize('state', ['draft', 'deleted'])
    def test_inactive_dataset_gets_no_zip(self, http, state):
        '''#7: ένα draft δεν αποκτά πόρο ZIP (θα μπορούσε να δημοσιευτεί με
        μόνο αυτόν), ούτε ένα διαγραμμένο dataset.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        helpers.call_action('package_patch', id=dataset['id'], state=state)
        with mock.patch.object(tasks, 'save_zip') as save:
            tasks.update_zip(dataset['id'])
        save.assert_not_called()

    def test_unreadable_local_upload_is_a_failed_resource(self, tmp_path):
        '''#11: ένα τοπικό αρχείο που δεν διαβάζεται δεν ρίχνει το job.'''
        resource = {'id': 'r1', 'url': 'a.csv', 'format': 'CSV', 'url_type': 'upload'}
        missing = str(tmp_path / 'missing')
        with mock.patch.object(tasks, '_local_upload_path', return_value=missing), \
                zipfile.ZipFile(str(tmp_path / 'a.zip'), 'w') as zipf:
            with pytest.raises(tasks.DownloadError) as error:
                tasks.download_resource_into_zip(resource, 0, zipf, set(), str(tmp_path))
        assert error.value.message.startswith('could not read the uploaded file')

    def test_rq_timeout_is_not_swallowed(self):
        '''Πριν: τα γενικά except κρατούσαν το job ζωντανό μέχρι το SIGKILL.'''
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        with mock.patch.object(tasks.requests, 'get', side_effect=JobTimeoutException('timeout')):
            with pytest.raises(JobTimeoutException):
                tasks.update_zip(dataset['id'])

    def test_deleted_dataset_is_not_an_error(self):
        assert tasks.update_zip('no-such-dataset') is None

    def test_unchanged_dataset_is_not_rebuilt(self, http):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        with mock.patch.object(tasks, 'save_zip') as save:
            tasks.update_zip(dataset['id'])
        save.assert_not_called()

    def test_change_makes_the_zip_stale_until_rebuilt(self, http):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/b.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        resource_id = _zip_of(dataset['id'])[0]['resources'][0]['id']
        helpers.call_action('resource_patch', id=resource_id, url='https://example.test/b.csv')
        assert freshness.zip_state(_zip_of(dataset['id'])[0]) == 'stale'
        tasks.update_zip(dataset['id'])
        assert freshness.zip_state(_zip_of(dataset['id'])[0]) == 'ready'

    def test_legacy_zip_without_fingerprint_is_rebuilt(self, http):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        zip_id = _zip_of(dataset['id'])[1]['id']
        helpers.call_action('resource_patch', id=zip_id, downloadall_fingerprint='')
        tasks.update_zip(dataset['id'])
        assert _zip_of(dataset['id'])[1]['downloadall_fingerprint']

    def test_previous_zip_kept_when_nothing_could_be_downloaded(self, http):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/b.csv', status=404)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        before = _zip_of(dataset['id'])[1]
        resource_id = _zip_of(dataset['id'])[0]['resources'][0]['id']
        helpers.call_action('resource_patch', id=resource_id, url='https://example.test/b.csv')
        tasks.update_zip(dataset['id'])
        shown, after = _zip_of(dataset['id'])
        assert after['url'] == before['url']
        assert after['downloadall_fingerprint'] == before['downloadall_fingerprint']
        # #2: η προσπάθεια σημειώνεται, ώστε το προηγούμενο ZIP να μένει
        # διαθέσιμο αντί για κλειδωμένο· το --retry-failed το ξαναδοκιμάζει
        assert after[freshness.ATTEMPTED_FIELD] == freshness.compute_fingerprint(shown)
        assert freshness.zip_state(shown) == 'ready'
        assert freshness.needs_retry(shown)

    def test_failed_save_keeps_the_previous_zip_available(self, http):
        '''#3: π.χ. dataset που δεν περνά validation.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/b.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        resource_id = _zip_of(dataset['id'])[0]['resources'][0]['id']
        helpers.call_action('resource_patch', id=resource_id, url='https://example.test/b.csv')
        with mock.patch.object(tasks, 'save_zip',
                               side_effect=toolkit.ValidationError({'title': ['missing']})):
            with pytest.raises(toolkit.ValidationError):
                tasks.update_zip(dataset['id'])
        assert freshness.zip_state(_zip_of(dataset['id'])[0]) == 'ready'


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestHvdOnly(object):

    def test_hvd_dataset_gets_a_zip(self, http):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(extras=[{'key': 'hvd_category', 'value': HVD}],
                                    resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        with mock.patch.dict('ckan.plugins.toolkit.config', {'ckanext.downloadall.hvd_only': 'true'}):
            tasks.update_zip(dataset['id'])
        assert _zip_of(dataset['id'])[1] is not None

    def test_zip_of_non_hvd_dataset_is_removed(self, http):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        assert _zip_of(dataset['id'])[1] is not None
        with mock.patch.dict('ckan.plugins.toolkit.config', {'ckanext.downloadall.hvd_only': 'true'}):
            tasks.update_zip(dataset['id'])
        assert _zip_of(dataset['id'])[1] is None
