# -*- coding: utf-8 -*-
'''
Tests για τα ευρήματα του code review του OD-857 (αριθμοί όπως στην αναφορά):
διπλό ZIP (#1), σφάλματα ανά πόρο (#2), παλιά μεταδεδομένα στο session (#3),
lock μετά από σφάλμα της Redis (#4), επανάληψη κοντά στο χρονικό όριο (#5),
απώλεια μεμονωμένων αιτημάτων (#6, #7, #8), attempted fingerprint (#10), αργός
server (#11) και σφάλμα ενός dataset στο update-all-zips (#12).
'''
import http.server
import threading
import time
import zipfile
from time import monotonic
from unittest import mock

import pytest
import requests
import responses
import sqlalchemy as sa
from rq.timeouts import JobTimeoutException
from urllib3.exceptions import LocationParseError

from ckan import model
from ckan.tests import factories, helpers

from ckanext.downloadall import cli, dedup, freshness, lib, storage, tasks
from ckanext.downloadall.tests.test_od857_build import _read, _zip_of
from ckanext.downloadall.tests.test_od857_lifecycle import cloud  # noqa: F401 (fixture)

CSV = b'a,b\n1,2\n'
HVD = '["http://data.europa.eu/bna/c_ac64a52d"]'


def _zip_resources(dataset_id):
    shown = helpers.call_action('package_show', id=dataset_id)
    return [r for r in shown['resources'] if r.get('downloadall_metadata_modified')]


def _set_title_elsewhere(dataset_id, title):
    '''Αλλαγή του dataset από άλλη διεργασία (άλλη σύνδεση, ήδη commit).'''
    with model.meta.engine.begin() as conn:
        conn.execute(sa.text(
            'UPDATE package SET title = :title, metadata_modified = now() '
            'WHERE id = :id'), {'title': title, 'id': dataset_id})


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestSave(object):

    def test_zip_created_meanwhile_is_updated_not_duplicated(self, http, tmp_path):
        '''#1: το job ξεκίνησε χωρίς ZIP, αλλά στο μεταξύ άλλο job το έφτιαξε.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        (created,) = _zip_resources(dataset['id'])
        zip_path = tmp_path / 'late.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zipf:
            zipf.writestr('a.csv', CSV)
        shown = helpers.call_action('package_show', id=dataset['id'])
        tasks.save_zip(shown, None, str(zip_path), 'fp', 'hash',
                       {'included': 1, 'excluded': 0, 'failed': 0})
        assert [z['id'] for z in _zip_resources(dataset['id'])] == [created['id']]

    def test_saving_waits_for_the_lock_of_the_dataset(self):
        '''#1: δύο jobs δεν αποθηκεύουν ταυτόχρονα το ZIP του ίδιου dataset.'''
        dataset = factories.Dataset()
        acquired = threading.Event()

        def other_job():
            try:
                tasks._lock_dataset_zip(dataset['id'])
                acquired.set()
            finally:
                model.Session.rollback()
                model.Session.remove()

        tasks._lock_dataset_zip(dataset['id'])
        thread = threading.Thread(target=other_job)
        thread.start()
        try:
            assert not acquired.wait(0.5)
        finally:
            model.Session.rollback()  # τέλος του transaction: το lock ελευθερώνεται
        thread.join(5)
        assert acquired.is_set()

    def test_save_reads_the_zip_under_the_lock(self, http):
        '''#1: πρώτα το lock και μετά η ανάγνωση του τρέχοντος ZIP.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        calls = []
        lock, current = tasks._lock_dataset_zip, tasks._current_zip
        with mock.patch.object(tasks, '_lock_dataset_zip',
                               side_effect=lambda *a: calls.append('lock') or lock(*a)), \
                mock.patch.object(tasks, '_current_zip',
                                  side_effect=lambda *a: calls.append('read') or current(*a)):
            tasks.update_zip(dataset['id'])
        # Μετά ξανά lock για το cleanup_pending (_store_pending)
        assert calls[:2] == ['lock', 'read']

    def test_edit_during_the_build_is_not_overwritten(self, http):
        '''#3: το resource_patch του ZIP γράφει όλο το dataset· όχι την εικόνα
        του από την αρχή του build.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        original = tasks.write_zip

        def write_zip_and_edit(*args, **kwargs):
            manifest = original(*args, **kwargs)
            _set_title_elsewhere(dataset['id'], u'Νέος τίτλος')
            return manifest

        with mock.patch.object(tasks, 'write_zip', side_effect=write_zip_and_edit):
            tasks.update_zip(dataset['id'])
        model.Session.expire_all()
        assert helpers.call_action('package_show', id=dataset['id'])['title'] == u'Νέος τίτλος'

    def test_change_from_elsewhere_is_built_from_the_new_state(self, http):
        '''#3: π.χ. update-all-zips --synchronous ή δεύτερη επεξεργασία στο
        ίδιο job, με το dataset ήδη φορτωμένο στο session.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        assert model.Package.get(dataset['id']).title  # στο session
        _set_title_elsewhere(dataset['id'], u'Νέος τίτλος')
        tasks.update_zip(dataset['id'])
        _, _, datapackage = _read(_zip_of(dataset['id'])[1])
        assert datapackage['title'] == u'Νέος τίτλος'

    def test_ready_right_after_the_first_build_whatever_the_licence_title(self, http):
        '''Τοπική δοκιμή 19/11: η σελίδα μπορεί να πάρει το dataset με άλλο
        τίτλο άδειας (Solr ή βάση, μετάφραση) από αυτόν που είδε το job.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(license_id='cc-by', resources=[
            {'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        shown = _zip_of(dataset['id'])[0]
        shown['license_title'] = u'Άλλη μετάφραση του τίτλου'
        shown['license_url'] = 'https://example.test/licence'
        assert freshness.zip_state(shown) == 'ready'

    def test_successful_build_clears_the_failed_attempt(self, http):
        '''#10: μια παλιά αποτυχημένη προσπάθεια δεν κάνει «ready» ένα ZIP
        άλλης εκδοχής του dataset.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/gone.csv', status=404)
        http.add(responses.GET, 'https://example.test/c.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        resource_id = dataset['resources'][0]['id']

        def set_url(url):
            helpers.call_action('resource_patch', id=resource_id, url=url)
            tasks.update_zip(dataset['id'])

        tasks.update_zip(dataset['id'])
        set_url('https://example.test/gone.csv')  # αποτυχία: attempted
        set_url('https://example.test/c.csv')     # επιτυχία
        assert not _zip_of(dataset['id'])[1].get(freshness.ATTEMPTED_FIELD)
        helpers.call_action('resource_patch', id=resource_id,
                            url='https://example.test/gone.csv')
        assert freshness.zip_state(_zip_of(dataset['id'])[0]) == 'stale'


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestResourceErrors(object):

    def test_unexpected_request_error_fails_only_the_resource(self):
        '''#2: π.χ. host με πολύ μεγάλο όνομα (LocationParseError).'''
        with mock.patch.object(tasks.requests, 'get',
                               side_effect=LocationParseError('label too long')):
            with pytest.raises(tasks.DownloadError):
                tasks._open('https://example.test/a.csv', None)

    def test_rq_timeout_still_stops_the_job(self):
        with mock.patch.object(tasks.requests, 'get', side_effect=JobTimeoutException()):
            with pytest.raises(JobTimeoutException):
                tasks._open('https://example.test/a.csv', None)

    def test_unexpected_error_while_adding_fails_only_the_resource(self, http, tmp_path):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        resource = {'id': 'r1', 'url': 'https://example.test/a.csv', 'format': 'CSV'}
        with zipfile.ZipFile(str(tmp_path / 'a.zip'), 'w') as zipf, \
                mock.patch.object(tasks.filenames, 'choose_filename',
                                  side_effect=RuntimeError('bug')):
            with pytest.raises(tasks.DownloadError):
                tasks.download_resource_into_zip(resource, 0, zipf, set(), str(tmp_path))

    def test_zip_is_built_when_one_resource_raises_unexpectedly(self, http):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/b.csv', body=LocationParseError('bad'))
        dataset = factories.Dataset(resources=[
            {'url': 'https://example.test/a.csv', 'format': 'CSV'},
            {'url': 'https://example.test/b.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        zip_res = _zip_of(dataset['id'])[1]
        assert (zip_res['downloadall_included'], zip_res['downloadall_failed']) in \
            ((1, 1), ('1', '1'))


class _TrickleHandler(http.server.BaseHTTPRequestHandler):
    '''Server που στέλνει ένα byte κάθε 0,1s, για ~8s.'''

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Length', '100000')
        self.end_headers()
        try:
            for _ in range(80):
                self.wfile.write(b'x')
                self.wfile.flush()
                time.sleep(0.1)
        except OSError:
            pass

    def log_message(self, *args):
        pass


class _KeepAliveTrickleHandler(_TrickleHandler):
    protocol_version = 'HTTP/1.1'


@pytest.mark.parametrize('handler', [_TrickleHandler, _KeepAliveTrickleHandler])
def test_slow_server_is_cut_at_the_time_limit(tmp_path, handler):
    '''#11: το read_timeout ισχύει ανά ανάγνωση· ένας server που στέλνει λίγα
    bytes κάθε λίγο κόβεται στο χρονικό όριο, όχι στο timeout της RQ. Με
    HTTP/1.0 και με keep-alive το socket βρίσκεται σε άλλο σημείο.'''
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1:%d/slow.csv' % server.server_address[1]
    resource = {'id': 'r1', 'url': url, 'format': 'CSV'}
    started = monotonic()
    try:
        with zipfile.ZipFile(str(tmp_path / 'a.zip'), 'w') as zipf:
            with pytest.raises(tasks.DownloadError) as error:
                tasks.download_resource_into_zip(resource, 0, zipf, set(), str(tmp_path),
                                                 deadline=monotonic() + 1)
    finally:
        server.shutdown()
    assert error.value.message == 'time limit'
    assert monotonic() - started < 4


@mock.patch.object(tasks, 'RELEASE_RETRY_SECONDS', 0)
class TestRedisErrors(object):
    '''#4: μετά από σφάλμα της Redis το lock δεν μένει ως το TTL.'''

    def test_lock_released_after_running_without_coordination(self):
        with mock.patch.object(dedup, 'prepare_iteration',
                               side_effect=dedup.RedisDedupError('down')), \
                mock.patch.object(dedup, 'release_lock') as release_lock, \
                mock.patch.object(tasks.lib, 'enqueue_zip') as enqueue_zip, \
                mock.patch.object(tasks, '_update_zip_once'):
            tasks.update_zip('dataset-id', None, True, 'token')
        release_lock.assert_called_once_with('dataset-id', 'token')
        assert not enqueue_zip.called

    def test_lock_released_when_that_run_fails(self):
        with mock.patch.object(dedup, 'prepare_iteration',
                               side_effect=dedup.RedisDedupError('down')), \
                mock.patch.object(dedup, 'release_lock') as release_lock, \
                mock.patch.object(tasks, '_update_zip_once', side_effect=RuntimeError('x')):
            with pytest.raises(RuntimeError):
                tasks.update_zip('dataset-id', None, True, 'token')
        release_lock.assert_called_once_with('dataset-id', 'token')

    @pytest.mark.parametrize('dirty, queued', [(True, 1), (False, 0)])
    def test_failed_finish_releases_and_keeps_changes(self, dirty, queued):
        with mock.patch.object(dedup, 'prepare_iteration', return_value=True), \
                mock.patch.object(dedup, 'take_force', return_value=False), \
                mock.patch.object(dedup, 'finish_iteration',
                                  side_effect=dedup.RedisDedupError('down')), \
                mock.patch.object(dedup, 'release_lock') as release_lock, \
                mock.patch.object(dedup, 'is_dirty', return_value=dirty), \
                mock.patch.object(tasks.lib, 'enqueue_zip') as enqueue_zip, \
                mock.patch.object(tasks, '_update_zip_once'):
            tasks.update_zip('dataset-id', None, True, 'token')
        release_lock.assert_called_once_with('dataset-id', 'token')
        assert enqueue_zip.call_count == queued

    def test_short_redis_error_is_retried(self):
        with mock.patch.object(dedup, 'release_lock',
                               side_effect=[dedup.RedisDedupError('blip'), True]) as release_lock, \
                mock.patch.object(dedup, 'is_dirty', return_value=False):
            tasks._release_and_requeue('dataset-id', 'token', True, tasks.REQUEUE_IF_CHANGED)
        assert release_lock.call_count == 2


class TestRerunTime(object):
    '''#5: νέα επεξεργασία μέσα στο job μόνο αν προλαβαίνει.'''

    def _run(self, deadline):
        clock = iter([0, 60, 60, 60, 120, 120])
        with mock.patch.object(tasks, 'job_deadline', return_value=deadline), \
                mock.patch.object(tasks, 'monotonic', side_effect=lambda: next(clock)), \
                mock.patch.object(dedup, 'prepare_iteration', return_value=True), \
                mock.patch.object(dedup, 'take_force', return_value=False), \
                mock.patch.object(dedup, 'finish_iteration', side_effect=[True, False]), \
                mock.patch.object(dedup, 'release_lock'), \
                mock.patch.object(tasks.lib, 'enqueue_zip') as enqueue_zip, \
                mock.patch.object(tasks, '_update_zip_once') as update_once:
            tasks.update_zip('dataset-id', None, True, 'token')
        return update_once.call_count, enqueue_zip.call_count

    def test_not_enough_time_for_another_build_queues_a_new_job(self):
        # Η πρώτη επεξεργασία κράτησε 60s· μένουν 40s ως το όριο
        assert self._run(deadline=100) == (1, 1)

    def test_enough_time_reruns_in_the_same_job(self):
        assert self._run(deadline=1000) == (2, 0)


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestForcedRebuild(object):
    '''#7: το --retry-failed δεν χάνεται όταν υπάρχει ήδη job για το dataset.'''

    def test_force_reaches_the_job_that_holds_the_lock(self):
        assert dedup.mark_dirty_and_acquire('dataset-id') is not None
        assert dedup.mark_dirty_and_acquire('dataset-id', force=True) is None
        assert dedup.take_force('dataset-id')
        assert not dedup.take_force('dataset-id')

    @pytest.mark.ckan_config('ckanext.downloadall.dedup_strategy', 'redis')
    def test_retry_failed_while_a_job_is_pending(self, enqueue_calls):
        dataset = factories.Dataset()
        assert len(enqueue_calls) == 1
        assert lib.enqueue_zip(dataset['id'], skip_if_no_changes=False) == lib.ALREADY_QUEUED
        assert dedup.take_force(dataset['id'])

    def test_job_rebuilds_without_change_check_when_forced(self):
        with mock.patch.object(dedup, 'prepare_iteration', return_value=True), \
                mock.patch.object(dedup, 'take_force', return_value=True), \
                mock.patch.object(dedup, 'finish_iteration', return_value=False), \
                mock.patch.object(tasks, '_update_zip_once') as update_once:
            tasks.update_zip('dataset-id', None, True, 'token')
        update_once.assert_called_once_with('dataset-id', None, False, None)


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'clean_dedup_keys', 'with_request_context')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestRequestCache(object):
    '''#8: με request_cache, κάθε commit του ίδιου αιτήματος βάζει job.'''

    def test_each_commit_in_the_same_request_queues_a_job(self, enqueue_calls):
        dataset = factories.Dataset()
        helpers.call_action('package_patch', id=dataset['id'], notes='first')
        helpers.call_action('package_patch', id=dataset['id'], notes='second')
        assert enqueue_calls.package_ids() == [dataset['id']] * 3

    def test_direct_calls_still_queue_once_per_request(self, enqueue_calls):
        dataset = factories.Dataset()
        del enqueue_calls[:]
        assert lib.enqueue_zip(dataset['id']) == lib.QUEUED
        assert lib.enqueue_zip(dataset['id']) == lib.ALREADY_QUEUED
        assert len(enqueue_calls) == 1


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestCommands(object):

    def test_blob_that_became_current_is_not_deleted(self, http, cloud):  # noqa: F811
        '''#6: το ZIP ξαναχτίστηκε όσο γινόταν η λίστα των blobs.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        current = _zip_of(dataset['id'])[1]
        blobs = [{'resource_id': current['id'], 'filename': storage.upload_filename(current)}]
        assert cli._apply_cleanup([], blobs, limit=0) == (0, 0)
        assert cloud.container.deleted == []
        assert blobs[0]['deleted'] is False and blobs[0]['skipped']

    def test_retry_failed_judges_the_current_state(self, http):
        '''#3: το πέρασμα δεν κρίνει από την εικόνα του dataset στο session.'''
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        helpers.call_action('package_show', id=dataset['id'])  # στο session
        _set_title_elsewhere(dataset['id'], u'Νέος τίτλος')
        counts = cli._update_all(synchronous=False, dry_run=True, retry_failed=True)
        assert (counts['queued'], counts['current']) == (1, 0)

    def test_one_failing_dataset_does_not_stop_update_all(self):
        '''#12: π.χ. το ημερήσιο cron.'''
        first = factories.Dataset(name='a-first')
        second = factories.Dataset(name='b-second')
        with mock.patch.object(tasks, 'update_zip',
                               side_effect=[RuntimeError('broken'), None]) as update_zip:
            counts = cli._update_all(synchronous=True, dry_run=False, retry_failed=False)
        assert [c.args[0] for c in update_zip.call_args_list] == [first['id'], second['id']]
        assert counts['errors'] == 1 and counts['queued'] == 2


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestPrivateDatasets(object):
    '''#9: τα ιδιωτικά datasets δεν παίρνουν ZIP· το παίρνουν όταν γίνουν
    δημόσια.'''

    def _dataset(self, http, private):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        org = factories.Organization()
        return factories.Dataset(owner_org=org['id'], private=private, resources=[
            {'url': 'https://example.test/a.csv', 'format': 'CSV'}])

    def test_private_dataset_gets_no_zip(self, http):
        dataset = self._dataset(http, private=True)
        tasks.update_zip(dataset['id'])
        assert _zip_resources(dataset['id']) == []
        shown = helpers.call_action('package_show', id=dataset['id'])
        assert freshness.zip_state(shown) == 'hidden'
        assert not freshness.needs_retry(shown)

    def test_zip_removed_when_the_dataset_becomes_private(self, http):
        dataset = self._dataset(http, private=False)
        tasks.update_zip(dataset['id'])
        assert len(_zip_resources(dataset['id'])) == 1
        helpers.call_action('package_patch', id=dataset['id'], private=True)
        tasks.update_zip(dataset['id'])
        assert _zip_resources(dataset['id']) == []

    def test_publishing_queues_the_first_zip(self, http, enqueue_calls):
        dataset = self._dataset(http, private=True)
        del enqueue_calls[:]
        helpers.call_action('package_patch', id=dataset['id'], notes='still private')
        assert enqueue_calls.package_ids() == []
        helpers.call_action('package_patch', id=dataset['id'], private=False)
        assert enqueue_calls.package_ids() == [dataset['id']]
        tasks.update_zip(dataset['id'])
        assert len(_zip_resources(dataset['id'])) == 1

    def test_commands_treat_private_datasets_as_not_eligible(self, http):
        dataset = self._dataset(http, private=True)
        zip_res = helpers.call_action(
            'resource_create', package_id=dataset['id'], url='https://example.test/old.zip',
            format='ZIP', downloadall_metadata_modified='2026-01-01T00:00:00')
        zip_resources, _ = cli._cleanup_plan()
        assert [(z['resource_id'], z['reason']) for z in zip_resources] == \
            [(zip_res['id'], 'private dataset')]
        counts = cli._update_all(synchronous=False, dry_run=True, retry_failed=False)
        assert (counts['queued'], counts['skipped']) == (0, 1)


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestRetryFailed(object):
    '''#13: το ημερήσιο --retry-failed ξαναχτίζει μόνο για προσωρινές
    αποτυχίες, με όριο ανά εκδοχή του dataset.'''

    @pytest.mark.parametrize('status, transient', [(404, False), (403, False),
                                                   (503, True), (429, True)])
    def test_http_failure_kinds(self, http, status, transient):
        http.add(responses.GET, 'https://example.test/a.csv', status=status)
        with pytest.raises(tasks.DownloadError) as error:
            tasks._open('https://example.test/a.csv', None)
        assert error.value.transient is transient

    def test_connection_failure_is_temporary(self, http):
        with pytest.raises(tasks.DownloadError) as error:
            tasks._open('https://unreachable.example.test/a.csv', None)
        assert error.value.transient

    def test_connection_cut_during_the_download_is_temporary(self, http, tmp_path):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        resource = {'id': 'r1', 'url': 'https://example.test/a.csv', 'format': 'CSV'}
        cut = requests.exceptions.ChunkedEncodingError('connection broken')
        with zipfile.ZipFile(str(tmp_path / 'a.zip'), 'w') as zipf, \
                mock.patch.object(requests.Response, 'iter_content', side_effect=cut):
            with pytest.raises(tasks.DownloadError) as error:
                tasks.download_resource_into_zip(resource, 0, zipf, set(), str(tmp_path))
        assert error.value.transient

    def test_invalid_request_is_permanent(self):
        with mock.patch.object(tasks.requests, 'get',
                               side_effect=LocationParseError('label too long')):
            with pytest.raises(tasks.DownloadError) as error:
                tasks._open('https://example.test/a.csv', None)
        assert not error.value.transient

    def test_counts_on_the_zip_resource(self, http):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/down.csv', status=503)
        http.add(responses.GET, 'https://example.test/gone.csv', status=404)
        dataset = factories.Dataset(resources=[
            {'url': 'https://example.test/a.csv', 'format': 'CSV'},
            {'url': 'https://example.test/down.csv', 'format': 'CSV'},
            {'url': 'https://example.test/gone.csv', 'format': 'CSV'}])

        def counts():
            zip_res = _zip_of(dataset['id'])[1]
            return tuple(freshness.build_count(zip_res, key) for key in (
                'downloadall_failed', freshness.TRANSIENT_FIELD, freshness.RETRIES_FIELD))

        tasks.update_zip(dataset['id'])
        assert counts() == (2, 1, 0)
        tasks.update_zip(dataset['id'], None, False)  # όπως το --retry-failed
        assert counts() == (2, 1, 1)
        helpers.call_action('package_patch', id=dataset['id'], notes='changed')
        tasks.update_zip(dataset['id'])
        assert counts() == (2, 1, 0)

    def test_failed_builds_of_the_same_version_are_counted(self, http):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/gone.csv', status=404)
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        helpers.call_action('resource_patch', id=dataset['resources'][0]['id'],
                            url='https://example.test/gone.csv')
        tasks.update_zip(dataset['id'])
        tasks.update_zip(dataset['id'], None, False)
        zip_res = _zip_of(dataset['id'])[1]
        assert freshness.build_count(zip_res, freshness.ATTEMPTS_FIELD) == 2
