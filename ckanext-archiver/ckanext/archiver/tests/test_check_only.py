# -*- coding: utf-8 -*-
'''
Tests για το ckanext.archiver.mode = check_only (OD-856) και για τη διατήρηση
της σημερινής συμπεριφοράς στο archive mode.

Όλα τα HTTP αιτήματα γίνονται mock· δεν χρησιμοποιείται δίκτυο ή Azure.
'''
import datetime
import itertools
import logging
import os
import ssl
import tempfile
import uuid
from types import SimpleNamespace
from unittest import mock

import pytest
import requests
from urllib3.exceptions import MaxRetryError, SSLError as Urllib3SSLError

from ckan import model
from ckan.exceptions import CkanConfigurationException
from ckan.tests import factories
from ckan.tests import helpers as test_helpers

from rq.job import Job

from ckanext.archiver import job_dedup
from ckanext.archiver import lib as archiver_lib
from ckanext.archiver import model as archiver_model
from ckanext.archiver import tasks
from ckanext.archiver.model import Archival, Status
from ckanext.archiver.resource_evaluation import get_url_check_state

log = logging.getLogger(__name__)

CHECK_ONLY = pytest.mark.ckan_config('ckanext.archiver.mode', 'check_only')


class FakeResponse(object):
    def __init__(self, status_code=200, url=None, headers=None, reason=None):
        self.status_code = status_code
        self.url = url
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})
        self.reason = reason or {200: 'OK', 404: 'Not Found', 405: 'Method Not Allowed',
                                 410: 'Gone', 429: 'Too Many Requests',
                                 503: 'Service Unavailable'}.get(status_code, '')
        self.closed = False

    def close(self):
        self.closed = True


def _responses(url, *codes, **kwargs):
    return [FakeResponse(code, url=url, **kwargs) for code in codes]


@pytest.fixture(autouse=True)
def no_jobs_and_no_delay():
    '''Τα datasets που δημιουργούνται στα tests δεν βάζουν πραγματικά jobs στο
    Redis και οι επαναλήψεις δεν περιμένουν.'''
    with mock.patch('ckan.plugins.toolkit.enqueue_job'), \
            mock.patch.object(tasks, 'RETRY_DELAY_SECONDS', 0):
        yield


@pytest.fixture(autouse=True)
def clean_archiver_dedup_keys():
    yield
    conn = job_dedup._redis()
    for key in conn.scan_iter(match='ckanext:*:archiver:*'):
        conn.delete(key)


@pytest.fixture
def archiver_tables(clean_db):
    archiver_model.init_tables(model.meta.engine)


def _resource(url='http://example.com/data/file.csv', format='CSV'):
    dataset = factories.Dataset(resources=[{'url': url, 'format': format}])
    return dataset, dataset['resources'][0]


def _check(resource_id):
    return tasks._update_resource(resource_id, 'priority', log)


@pytest.mark.usefixtures('with_plugins', 'archiver_tables')
@pytest.mark.ckan_config('ckan.plugins', 'archiver')
@CHECK_ONLY
class TestCheckOnlyResults(object):

    def test_head_ok_saves_header_metadata(self):
        _, res = _resource()
        response = FakeResponse(200, url=res['url'], headers={
            'ETag': '"abc"', 'Last-Modified': 'Mon, 01 Jan 2024 00:00:00 GMT',
            'Content-Type': 'text/csv; charset=utf-8', 'Content-Length': '1234'})
        with mock.patch.object(tasks.requests, 'head', return_value=response), \
                mock.patch.object(tasks.requests, 'get') as get:
            assert _check(res['id']) is True
        get.assert_not_called()
        assert response.closed

        archival = Archival.get_for_resource(res['id'])
        assert archival.status == 'URL checked successfully'
        assert archival.is_broken is False
        assert Status.is_ok(archival.status_id)
        assert archival.etag == '"abc"'
        assert archival.last_modified == 'Mon, 01 Jan 2024 00:00:00 GMT'
        assert archival.mimetype == 'text/csv'
        assert archival.size == 1234
        assert archival.failure_count == 0
        assert archival.last_success is not None
        assert archival.as_dict()['check_state'] == 'available'

    def test_redirect_chain_is_recorded(self):
        _, res = _resource()
        final = 'https://cdn.example.com/final/file.csv'
        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(200, url=final)) as head:
            _check(res['id'])
        assert head.call_args.kwargs['allow_redirects'] is True
        archival = Archival.get_for_resource(res['id'])
        assert archival.url_redirected_to == final
        assert archival.status == 'URL checked successfully'

    def test_head_not_allowed_falls_back_to_streamed_get(self):
        _, res = _resource()
        get_response = FakeResponse(200, url=res['url'])
        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(405, url=res['url'])), \
                mock.patch.object(tasks.requests, 'get',
                                  return_value=get_response) as get:
            _check(res['id'])
        assert get.call_args.kwargs['stream'] is True
        assert get_response.closed
        assert Archival.get_for_resource(res['id']).status == 'URL checked successfully'

    def test_head_blocked_but_get_ok(self):
        _, res = _resource()
        with mock.patch.object(tasks.requests, 'head',
                               side_effect=requests.exceptions.ConnectionError('reset')), \
                mock.patch.object(tasks.requests, 'get',
                                  return_value=FakeResponse(200, url=res['url'])):
            _check(res['id'])
        assert Archival.get_for_resource(res['id']).status == 'URL checked successfully'

    @pytest.mark.parametrize('code', [404, 410])
    def test_not_found_is_broken_immediately(self, code):
        _, res = _resource()
        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(code, url=res['url'])), \
                mock.patch.object(tasks.requests, 'get',
                                  return_value=FakeResponse(code, url=res['url'])):
            _check(res['id'])
        archival = Archival.get_for_resource(res['id'])
        assert archival.status == 'URL request failed'
        assert archival.is_broken is True
        assert archival.failure_count == 1
        assert 'Server reported status error: %s' % code in archival.reason
        assert archival.as_dict()['check_state'] == 'confirmed_broken'

    def test_invalid_url_is_broken(self):
        _, res = _resource(url='ftp:/missing-host')
        with mock.patch.object(tasks.requests, 'head') as head:
            _check(res['id'])
        head.assert_not_called()
        archival = Archival.get_for_resource(res['id'])
        assert archival.status == 'URL invalid'
        assert archival.is_broken is True

    @pytest.mark.parametrize('code', [429, 500, 502, 503])
    def test_http_errors_are_transient_first(self, code):
        _, res = _resource()
        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(code, url=res['url'])), \
                mock.patch.object(tasks.requests, 'get',
                                  return_value=FakeResponse(code, url=res['url'])):
            _check(res['id'])
        archival = Archival.get_for_resource(res['id'])
        assert archival.status == 'URL check temporarily failed'
        assert archival.is_broken is None
        assert archival.as_dict()['check_state'] == 'transient_failure'

    @pytest.mark.parametrize('error', [requests.exceptions.ConnectTimeout('slow'),
                                       requests.exceptions.ConnectionError('dns')])
    def test_network_errors_are_transient(self, error):
        _, res = _resource()
        with mock.patch.object(tasks.requests, 'head', side_effect=error), \
                mock.patch.object(tasks.requests, 'get', side_effect=error):
            _check(res['id'])
        archival = Archival.get_for_resource(res['id'])
        assert archival.status == 'URL check temporarily failed'
        assert archival.is_broken is None

    def test_transient_failure_is_retried(self):
        _, res = _resource()
        reset = requests.exceptions.ConnectionError('Connection reset by peer')
        with mock.patch.object(tasks.requests, 'head', side_effect=[
                reset, FakeResponse(200, url=res['url'])]), \
                mock.patch.object(tasks.requests, 'get', side_effect=reset):
            _check(res['id'])
        assert Archival.get_for_resource(res['id']).status == 'URL checked successfully'

    @pytest.mark.parametrize('code', [400, 401, 403, 405, 429, 500, 502, 503, 504])
    def test_http_errors_are_not_retried(self, code):
        '''Ο server απάντησε, π.χ. 403 σε αυτόματα αιτήματα ή 502 όταν έχει
        πέσει το GeoServer πίσω από τον proxy: HEAD και GET μία φορά, χωρίς
        επανάληψη· αποτυχία όπως πριν.'''
        _, res = _resource()
        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(code, url=res['url'])) as head, \
                mock.patch.object(tasks.requests, 'get',
                                  return_value=FakeResponse(code, url=res['url'])) as get:
            _check(res['id'])
        assert head.call_count == 1
        assert get.call_count == 1
        archival = Archival.get_for_resource(res['id'])
        assert archival.status == 'URL check temporarily failed'
        assert archival.failure_count == 1

    def test_head_error_then_lost_get_is_retried(self):
        '''405 στο HEAD και σύνδεση που κόπηκε στο GET: στο GET δεν ήρθε
        απάντηση, άρα μία νέα προσπάθεια μπορεί να πετύχει.'''
        _, res = _resource()
        reset = requests.exceptions.ConnectionError('Connection reset by peer')
        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(405, url=res['url'])) as head, \
                mock.patch.object(tasks.requests, 'get',
                                  side_effect=[reset, FakeResponse(200, url=res['url'])]) as get:
            _check(res['id'])
        assert (head.call_count, get.call_count) == (2, 2)
        assert Archival.get_for_resource(res['id']).status == 'URL checked successfully'

    def test_head_error_then_get_unavailable_is_not_retried(self):
        '''405 στο HEAD (δεν το υποστηρίζει) και 502 στο GET: χωρίς επανάληψη.'''
        _, res = _resource()
        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(405, url=res['url'])) as head, \
                mock.patch.object(tasks.requests, 'get',
                                  return_value=FakeResponse(502, url=res['url'])) as get:
            _check(res['id'])
        assert head.call_count == 1
        assert get.call_count == 1

    @pytest.mark.ckan_config('ckanext.archiver.check_only.retries', '0')
    def test_becomes_broken_after_failure_threshold(self):
        _, res = _resource()
        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(503, url=res['url'])), \
                mock.patch.object(tasks.requests, 'get',
                                  return_value=FakeResponse(503, url=res['url'])):
            statuses = []
            for _attempt in range(3):
                _check(res['id'])
                archival = Archival.get_for_resource(res['id'])
                statuses.append((archival.status, archival.failure_count))
        assert statuses == [('URL check temporarily failed', 1),
                            ('URL check temporarily failed', 2),
                            ('URL request failed', 3)]
        assert archival.is_broken is True

    def test_success_resets_failure_history(self):
        _, res = _resource()
        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(503, url=res['url'])), \
                mock.patch.object(tasks.requests, 'get',
                                  return_value=FakeResponse(503, url=res['url'])):
            _check(res['id'])
        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(200, url=res['url'])):
            _check(res['id'])
        archival = Archival.get_for_resource(res['id'])
        assert archival.failure_count == 0
        assert archival.first_failure is None

    def test_same_etag_still_updates_check_timestamp(self):
        _, res = _resource()
        response = FakeResponse(200, url=res['url'], headers={'ETag': '"same"'})
        with mock.patch.object(tasks.requests, 'head', return_value=response):
            assert _check(res['id']) is True
            first_updated = Archival.get_for_resource(res['id']).updated
            assert _check(res['id']) is False  # ίδιο αποτέλεσμα, καμία αλλαγή
        archival = Archival.get_for_resource(res['id'])
        assert archival.updated > first_updated
        assert archival.status == 'URL checked successfully'

    def test_no_download_temp_file_or_azure_upload(self):
        _, res = _resource()
        forbidden = AssertionError('must not be called in check_only')
        with mock.patch.object(tasks, 'download', side_effect=forbidden), \
                mock.patch.object(tasks, 'archive_resource', side_effect=forbidden), \
                mock.patch.object(tasks, 'AzureResourceUploader', side_effect=forbidden), \
                mock.patch.object(tasks.tempfile, 'mkstemp', side_effect=forbidden), \
                mock.patch.object(tasks.requests, 'head',
                                  return_value=FakeResponse(200, url=res['url'])):
            _check(res['id'])
        assert Archival.get_for_resource(res['id']).status == 'URL checked successfully'

    def test_legacy_cache_fields_are_kept(self):
        _, res = _resource()
        archival = Archival.create(res['id'])
        archival.status_id = Status.by_text('Archived successfully')
        archival.is_broken = False
        archival.cache_url = 'https://blob.example.com/cached/file.csv'
        archival.cache_filepath = 'file.csv'
        archival.hash = 'legacy-hash'
        model.Session.add(archival)
        model.Session.commit()

        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(404, url=res['url'])), \
                mock.patch.object(tasks.requests, 'get',
                                  return_value=FakeResponse(404, url=res['url'])):
            _check(res['id'])

        archival = Archival.get_for_resource(res['id'])
        assert archival.status == 'URL request failed'
        assert archival.cache_url == 'https://blob.example.com/cached/file.csv'
        assert archival.cache_filepath == 'file.csv'
        assert archival.hash == 'legacy-hash'

    def test_non_evaluable_resource_is_not_requested(self):
        _, res = _resource(url='')
        with mock.patch.object(tasks.requests, 'head') as head:
            _check(res['id'])
        head.assert_not_called()
        assert Archival.get_for_resource(res['id']).status == 'Chose not to download'


@pytest.mark.usefixtures('with_plugins')
@pytest.mark.ckan_config('ckan.plugins', 'archiver')
class TestCheckOnlyLocalUpload(object):

    def _outcome(self, filepath):
        resource = {'id': 'abc', 'url_type': 'upload',
                    'url': '/dataset/1/resource/abc/download/file.csv'}
        uploader = SimpleNamespace(get_path=lambda resource_id: filepath)
        with mock.patch.object(tasks.uploader, 'get_resource_uploader',
                               return_value=uploader), \
                mock.patch.object(tasks.requests, 'head') as head:
            outcome = tasks._url_check_outcome(resource, log)
        head.assert_not_called()
        return outcome

    def test_existing_local_file_is_ok(self):
        with tempfile.NamedTemporaryFile(suffix='.csv') as fp:
            fp.write(b'a,b\n1,2\n')
            fp.flush()
            outcome = self._outcome(fp.name)
        assert outcome['result'] == tasks.URL_OK
        assert outcome['headers']['content-length'] == '8'

    def test_missing_local_file_is_broken(self):
        outcome = self._outcome(os.path.join(tempfile.gettempdir(), 'missing-od856.csv'))
        assert outcome['result'] == tasks.URL_BROKEN
        assert outcome['status_text'] == 'URL request failed'


@pytest.mark.usefixtures('with_plugins', 'archiver_tables')
@pytest.mark.ckan_config('ckan.plugins', 'archiver')
class TestPackageFlow(object):

    @CHECK_ONLY
    def test_notify_and_reindex_only_when_result_changes(self):
        dataset, res = _resource()
        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(200, url=res['url'])), \
                mock.patch.object(tasks, 'notify_package') as notify, \
                mock.patch.object(tasks, '_update_search_index') as reindex:
            tasks._update_package(dataset['id'], 'priority', log)
            assert notify.call_count == 1
            assert notify.call_args.args[1] == 'priority'
            assert reindex.call_count == 1

            tasks._update_package(dataset['id'], 'priority', log)
            assert notify.call_count == 1
            assert reindex.call_count == 1

    def test_archive_mode_still_downloads(self):
        dataset, res = _resource()
        with mock.patch.object(tasks, '_check_resource_url',
                               side_effect=AssertionError('check_only path')), \
                mock.patch.object(tasks, 'download',
                                  side_effect=tasks.DownloadError('Server reported status error: 404 Not Found')) as download:
            tasks._update_resource(res['id'], 'priority', log)
        assert download.called
        archival = Archival.get_for_resource(res['id'])
        assert archival.status == 'Download error'


@pytest.mark.usefixtures('with_plugins')
@pytest.mark.ckan_config('ckan.plugins', 'archiver')
class TestQueuesAndConfig(object):

    @pytest.fixture(autouse=True)
    def clean_dedup_keys(self):
        yield
        conn = job_dedup._redis()
        for key in conn.scan_iter(match='ckanext:*:archiver:*'):
            conn.delete(key)

    def _enqueue(self, queue, package_id=None):
        package = SimpleNamespace(id=package_id or 'pkg-' + str(uuid.uuid4()), name='pkg')
        with mock.patch('ckan.plugins.toolkit.enqueue_job') as enqueue:
            archiver_lib.create_archiver_package_task(package, queue)
        return package.id, enqueue.call_args

    def test_queue_name_reaches_the_job(self):
        package_id, call = self._enqueue('priority')
        assert call.kwargs['args'] == [package_id, 'priority']
        assert call.kwargs['queue'] == 'priority'
        # Με την προεπιλεγμένη στρατηγική redis το job έχει δικό μας job id
        assert set(call.kwargs['rq_kwargs']) == {'job_id'}

    @pytest.mark.ckan_config('ckanext.archiver.dedup_strategy', 'none')
    def test_no_job_id_with_none_strategy(self):
        _, call = self._enqueue('priority')
        assert call.kwargs['rq_kwargs'] is None

    @pytest.mark.ckan_config('ckanext.archiver.queue.priority', 'archiver_priority')
    @pytest.mark.ckan_config('ckanext.archiver.job_timeout', '600')
    def test_configured_queue_and_timeout(self):
        package_id, call = self._enqueue('priority')
        # Στο job περνά το λογικό όνομα, ώστε το QA να επιλέξει τη δική του ουρά
        assert call.kwargs['args'] == [package_id, 'priority']
        assert call.kwargs['queue'] == 'archiver_priority'
        assert call.kwargs['rq_kwargs']['timeout'] == 600

    def test_one_pending_job_per_dataset(self):
        '''Δεύτερο αίτημα για dataset που ήδη περιμένει στην ουρά δεν βάζει job.'''
        conn = job_dedup._redis()
        created = []

        def fake_enqueue(fn, args=None, queue=None, rq_kwargs=None, **kwargs):
            created.append(rq_kwargs['job_id'])
            conn.hset(Job.key_for(rq_kwargs['job_id']), mapping={'description': 'test', 'status': 'queued'})

        package = SimpleNamespace(id='pkg-' + str(uuid.uuid4()), name='pkg')
        try:
            with mock.patch('ckan.plugins.toolkit.enqueue_job', side_effect=fake_enqueue):
                archiver_lib.create_archiver_package_task(package, 'bulk')
                archiver_lib.create_archiver_package_task(package, 'bulk')
            assert len(created) == 1
        finally:
            for job_id in created:
                conn.delete(Job.key_for(job_id))

    def test_default_mode_is_archive(self):
        assert archiver_lib.archiver_mode() == 'archive'


class TestInvalidMode(object):
    '''Άγνωστη τιμή σταματά την εκκίνηση του plugin (δεν φορτώνεται εδώ, γιατί
    το with_plugins θα αποτύγχανε ήδη στο setup).'''

    @pytest.mark.ckan_config('ckanext.archiver.mode', 'bogus')
    def test_unknown_mode_is_rejected(self):
        with pytest.raises(CkanConfigurationException):
            archiver_lib.archiver_mode()

    @pytest.mark.ckan_config('ckanext.archiver.mode', 'bogus')
    def test_plugin_refuses_to_start(self):
        from ckan.plugins.toolkit import config
        from ckanext.archiver.plugin import ArchiverPlugin
        with pytest.raises(CkanConfigurationException):
            ArchiverPlugin().update_config(config)


class TestStatusesAndCheckState(object):

    def test_new_statuses(self):
        assert Status.is_ok(Status.by_text('URL checked successfully'))
        assert Status.is_status_broken(Status.by_text('URL checked successfully')) is False
        assert Status.is_status_broken(Status.by_text('URL check temporarily failed')) is None
        assert not Status.is_ok(Status.by_text('URL check temporarily failed'))

    @pytest.mark.parametrize('status_text,is_broken,expected', [
        ('URL checked successfully', False, 'available'),
        ('Archived successfully', False, 'available'),
        ('URL request failed', True, 'confirmed_broken'),
        ('URL check temporarily failed', None, 'transient_failure'),
        ('Chose not to download', None, 'unknown'),
    ])
    def test_states(self, status_text, is_broken, expected):
        archival = SimpleNamespace(status_id=Status.by_text(status_text),
                                   is_broken=is_broken,
                                   updated=datetime.datetime.now())
        assert get_url_check_state(archival) == expected

    def test_missing_archival_is_unknown(self):
        assert get_url_check_state(None) == 'unknown'

    @CHECK_ONLY
    def test_old_check_is_stale(self):
        archival = SimpleNamespace(status_id=Status.by_text('URL checked successfully'),
                                   is_broken=False,
                                   updated=datetime.datetime.now() - datetime.timedelta(days=30))
        assert get_url_check_state(archival) == 'stale'


@pytest.mark.usefixtures('with_plugins', 'archiver_tables')
@pytest.mark.ckan_config('ckan.plugins', 'archiver')
class TestReviewFixes(object):
    '''Διορθώσεις μετά το code review.'''

    @CHECK_ONLY
    def test_check_keeps_header_fields_of_legacy_copy(self):
        '''(1) Με παλιό αρχειοθετημένο αντίγραφο, ο έλεγχος δεν γράφει το ETag
        του, ώστε ένα μελλοντικό archive να μην το θεωρήσει «αμετάβλητο».'''
        _, res = _resource()
        archival = Archival.create(res['id'])
        archival.status_id = Status.by_text('Archived successfully')
        archival.is_broken = False
        archival.cache_url = 'https://blob.example.com/cached/file.csv'
        archival.etag = '"v1"'
        archival.size = 10
        model.Session.add(archival)
        model.Session.commit()
        response = FakeResponse(200, url=res['url'], headers={
            'ETag': '"v2"', 'Content-Length': '99'})
        with mock.patch.object(tasks.requests, 'head', return_value=response):
            _check(res['id'])
        archival = Archival.get_for_resource(res['id'])
        assert archival.status == 'URL checked successfully'
        assert archival.etag == '"v1"'
        assert archival.size == 10

    def test_archive_mode_ignores_etag_without_archived_copy(self):
        '''(1) Στο archive mode το ETag χρησιμοποιείται για το «δεν άλλαξε»
        μόνο αν υπάρχει αρχειοθετημένο αντίγραφο.'''
        _, res = _resource()
        archival = Archival.create(res['id'])
        archival.status_id = Status.by_text('URL checked successfully')
        archival.etag = '"from-check"'
        model.Session.add(archival)
        model.Session.commit()
        seen = []

        def fake_download(context, resource, *args, **kwargs):
            seen.append(context['previous'])
            raise tasks.DownloadError('stop')

        with mock.patch.object(tasks, 'download', side_effect=fake_download):
            tasks._update_resource(res['id'], 'priority', log)
        assert seen and all(previous is None for previous in seen)

    @CHECK_ONLY
    def test_unexpected_error_does_not_abort_the_check(self):
        '''(5) Απρόσμενο σφάλμα σε έναν πόρο δεν διακόπτει το job. Δεν είναι
        αποτυχία του συνδέσμου, άρα δεν αποθηκεύεται αποτέλεσμα (2ο review, 1).'''
        _, res = _resource()
        with mock.patch.object(tasks, '_url_check_outcome', side_effect=ValueError('boom')):
            assert _check(res['id']) is False
        assert Archival.get_for_resource(res['id']) is None

    @CHECK_ONLY
    def test_unexpected_get_error_is_transient(self):
        _, res = _resource()
        with mock.patch.object(tasks.requests, 'head', side_effect=ValueError('bad host')), \
                mock.patch.object(tasks.requests, 'get', side_effect=ValueError('bad host')):
            _check(res['id'])
        assert Archival.get_for_resource(res['id']).status == 'URL check temporarily failed'

    def test_malformed_content_type(self):
        assert tasks._clean_content_type('text/html charset=utf-8') == 'text/html'
        assert tasks._clean_content_type('text/csv; charset=utf-8') == 'text/csv'
        assert tasks._clean_content_type('text/csv;charset=utf-8') == 'text/csv'
        assert tasks._clean_content_type('application/json') == 'application/json'


@pytest.mark.usefixtures('with_plugins')
@pytest.mark.ckan_config('ckan.plugins', 'archiver')
class TestReviewFixesUnit(object):

    def _upload_outcome(self, filepath, url='/dataset/1/resource/abc/download/file.csv'):
        resource = {'id': 'abc', 'url_type': 'upload', 'url': url}
        uploader = SimpleNamespace(get_path=lambda resource_id: filepath)
        with mock.patch.object(tasks.uploader, 'get_resource_uploader',
                               return_value=uploader), \
                mock.patch.object(tasks.requests, 'head',
                                  return_value=FakeResponse(200)) as head:
            return tasks._url_check_outcome(resource, log), head

    @pytest.mark.ckan_config('ckanext-archiver.archive_cloud', 'false')
    def test_cloud_upload_skipped_without_archive_cloud(self):
        '''(7) Όπως στο archive mode: uploads στο cloud δεν ελέγχονται.'''
        outcome, head = self._upload_outcome('https://blob.example.com/file.csv')
        head.assert_not_called()
        assert outcome['result'] == tasks.URL_SKIPPED
        assert outcome['status_text'] == 'Chose not to download'

    @pytest.mark.ckan_config('ckanext-archiver.archive_cloud', 'true')
    def test_cloud_upload_checked_with_archive_cloud(self):
        outcome, head = self._upload_outcome('https://blob.example.com/file.csv')
        assert head.called
        assert outcome['result'] == tasks.URL_OK

    @pytest.mark.ckan_config('ckan.site_url_internally', 'http://internal:5000')
    def test_local_upload_with_internal_site_url(self):
        '''(13) Με site_url_internally, το τοπικό upload ελέγχεται στον δίσκο.'''
        with tempfile.NamedTemporaryFile(suffix='.csv') as fp:
            fp.write(b'a,b\n')
            fp.flush()
            outcome, head = self._upload_outcome(fp.name)
        head.assert_not_called()
        assert outcome['result'] == tasks.URL_OK

    @CHECK_ONLY
    def test_default_job_timeout_in_check_only(self):
        '''(8) Χωρίς ckanext.archiver.job_timeout, 3600 στο check_only.'''
        assert archiver_lib._job_rq_kwargs() == {'timeout': 3600}

    def test_no_default_job_timeout_in_archive_mode(self):
        assert archiver_lib._job_rq_kwargs() is None

    @pytest.mark.ckan_config('ckanext.archiver.check_only.retries', '-1')
    @pytest.mark.ckan_config('ckanext.archiver.check_only.timeout', 'abc')
    def test_invalid_numbers_are_bounded(self):
        '''(11) Αρνητικές ή μη έγκυρες τιμές δεν ρίχνουν τα jobs.'''
        assert archiver_lib.check_only_retries() == 0
        assert archiver_lib.check_only_timeout() == 15

    @pytest.mark.ckan_config('ckanext.archiver.check_only.retries', '0')
    def test_zero_retries_is_respected(self):
        assert archiver_lib.check_only_retries() == 0

    def test_old_archive_is_not_stale_in_archive_mode(self):
        '''(10) Στο archive mode το updated δεν δείχνει τον τελευταίο έλεγχο.'''
        archival = SimpleNamespace(status_id=Status.by_text('Archived successfully'),
                                   is_broken=False,
                                   updated=datetime.datetime.now() - datetime.timedelta(days=30))
        assert get_url_check_state(archival) == 'available'

    def test_reindex_declared_by_ipipe_observer(self):
        '''(12) Ο archiver ρωτά τους IPipe observers αντί να διαβάζει ρυθμίσεις του QA.'''
        yes = SimpleNamespace(reindexes_after_package_archived=lambda: True)
        no = SimpleNamespace(reindexes_after_package_archived=lambda: False)
        with mock.patch.object(tasks.p, 'PluginImplementations', return_value=[no, yes]):
            assert tasks._qa_reindexes_after_notify() is True
        with mock.patch.object(tasks.p, 'PluginImplementations', return_value=[no, object()]):
            assert tasks._qa_reindexes_after_notify() is False


@pytest.mark.usefixtures('with_plugins', 'archiver_tables')
@pytest.mark.ckan_config('ckan.plugins', 'archiver')
class TestSecondReviewFixes(object):
    '''Διορθώσεις μετά το δεύτερο code review.'''

    @CHECK_ONLY
    def test_unexpected_error_keeps_failure_history(self):
        '''(1) Απρόσμενο σφάλμα (π.χ. bug) δεν μετρά στο κατώφλι αποτυχιών,
        άρα δεν κάνει broken έναν σύνδεσμο που απλώς αργούσε.'''
        _, res = _resource()
        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(503, url=res['url'])), \
                mock.patch.object(tasks.requests, 'get',
                                  return_value=FakeResponse(503, url=res['url'])):
            _check(res['id'])
            _check(res['id'])
        with mock.patch.object(tasks, '_url_check_outcome', side_effect=ValueError('bug')):
            for _attempt in range(3):
                _check(res['id'])
        archival = Archival.get_for_resource(res['id'])
        assert archival.status == 'URL check temporarily failed'
        assert archival.failure_count == 2
        assert archival.is_broken is None

    @CHECK_ONLY
    def test_resource_edit_counts_as_change(self):
        '''(2) Νέο format/URL με το ίδιο status: μετρά ως αλλαγή, ώστε να
        σταλεί package-archived και το QA σε archival mode να ξαναβαθμολογήσει.'''
        _, res = _resource()
        with mock.patch.object(tasks.requests, 'head',
                               return_value=FakeResponse(200, url=res['url'])):
            assert _check(res['id']) is True
            assert _check(res['id']) is False
            test_helpers.call_action('resource_patch', id=res['id'], format='JSON')
            assert _check(res['id']) is True
            assert _check(res['id']) is False

    def test_notify_queues_archiver_after_commit(self):
        '''(3) Το notify εκτελείται πριν από το commit: το job μπαίνει στην
        ουρά μετά το commit (μία φορά) και καθόλου σε rollback.'''
        from ckanext.archiver.plugin import ArchiverPlugin
        dataset, _ = _resource()
        package = model.Package.get(dataset['id'])
        with mock.patch.object(archiver_lib, 'enqueue_archiver_package') as enqueue:
            ArchiverPlugin().notify(package, 'changed')
            ArchiverPlugin().notify(package, 'changed')
            enqueue.assert_not_called()
            model.Session.commit()
            enqueue.assert_called_once_with(dataset['id'], 'priority')

            # Ανοιχτό transaction, ώστε το rollback να είναι πραγματικό
            model.Session.query(model.Package).first()
            ArchiverPlugin().notify(package, 'changed')
            model.Session.rollback()
            model.Session.commit()
            enqueue.assert_called_once_with(dataset['id'], 'priority')

    def test_after_commit_keeps_the_most_urgent_queue(self):
        enqueue = mock.Mock()
        model.Session.query(model.Package).first()
        job_dedup.enqueue_after_commit('archiver', 'pkg-1', 'bulk', enqueue)
        job_dedup.enqueue_after_commit('archiver', 'pkg-1', 'priority', enqueue)
        job_dedup.enqueue_after_commit('archiver', 'pkg-1', 'bulk', enqueue)
        model.Session.commit()
        enqueue.assert_called_once_with('pkg-1', 'priority')

    @CHECK_ONLY
    def test_time_limit_checks_oldest_first_and_continues(self):
        '''(5) Στο χρονικό όριο το job σταματά και κάνει notify για όσους
        ελέγχθηκαν· το επόμενο συνεχίζει από τους πόρους που έμειναν.'''
        urls = ['http://example.com/%d.csv' % i for i in range(3)]
        dataset = factories.Dataset(resources=[{'url': url, 'format': 'CSV'} for url in urls])
        checked = []

        def head(url, **kwargs):
            checked.append(url)
            return FakeResponse(200, url=url)

        with mock.patch.object(tasks.requests, 'head', side_effect=head), \
                mock.patch.object(tasks, '_check_only_deadline',
                                  side_effect=lambda: tasks.monotonic() - 1), \
                mock.patch.object(tasks, 'notify_package') as notify, \
                mock.patch.object(tasks, '_update_search_index'):
            for _run in range(4):
                tasks._update_package(dataset['id'], 'priority', log)
        # Ένας πόρος ανά job· ο τέταρτος ξαναρχίζει από τον παλαιότερο έλεγχο
        assert checked == urls + [urls[0]]
        assert notify.call_count == 3

    def test_deadline_leaves_room_before_job_timeout(self):
        with mock.patch('rq.get_current_job', return_value=SimpleNamespace(timeout=3600)):
            remaining = tasks._check_only_deadline() - tasks.monotonic()
        # Περιθώριο 10% (360s), μεγαλύτερο από τον χειρότερο πόρο + 60s
        assert 3230 < remaining <= 3240
        with mock.patch('rq.get_current_job', return_value=SimpleNamespace(timeout=300)):
            remaining = tasks._check_only_deadline() - tasks.monotonic()
        # 2 προσπάθειες x (HEAD + GET) x 15s + 60s = 120s περιθώριο (στα tests
        # η παύση ανάμεσα στις προσπάθειες είναι 0· στην παραγωγή +2s)
        assert 170 < remaining <= 180
        with mock.patch('rq.get_current_job', return_value=None):
            assert tasks._check_only_deadline() is None


@pytest.mark.usefixtures('with_plugins')
@pytest.mark.ckan_config('ckan.plugins', 'archiver')
class TestSecondReviewFixesUnit(object):

    @pytest.mark.parametrize('url,expected', [
        ('https://example.com/data/%CE%B1.csv', 'https://example.com/data/%CE%B1.csv'),
        (u'https://example.com/data/\u03b1.csv', 'https://example.com/data/%CE%B1.csv'),
        ('https://example.com/my%20file.csv?x=1', 'https://example.com/my%20file.csv?x=1'),
        ('https://example.com/a;b=c/file(1).csv', 'https://example.com/a;b=c/file(1).csv'),
    ])
    def test_tidy_url_does_not_double_encode(self, url, expected):
        '''(4) Τα %XX δεν ξανακωδικοποιούνται· πριν γίνονταν %25XX και ο
        server απαντούσε 404.'''
        assert tasks.tidy_url(url) == expected

    @CHECK_ONLY
    @pytest.mark.ckan_config('ckanext.archiver.job_timeout', '0')
    def test_zero_job_timeout_means_no_override(self):
        '''(10) 0: ισχύει το ckan.jobs.timeout (πριν γινόταν 1s).'''
        assert archiver_lib._job_rq_kwargs() is None

    @CHECK_ONLY
    @pytest.mark.ckan_config('ckanext.archiver.job_timeout', '-1')
    def test_negative_job_timeout_means_no_override(self):
        assert archiver_lib._job_rq_kwargs() is None

    @pytest.mark.parametrize('check_only,shows_date', [(False, True), (True, False)])
    def test_cached_on_date_hidden_in_check_only(self, app, check_only, shows_date):
        '''(11) Στο check_only το last_success είναι η ημερομηνία ελέγχου, όχι
        του αντιγράφου.'''
        from ckanext.archiver import helpers as archiver_helpers
        resource = {'id': 'abc', 'archiver': {
            'cache_url': 'https://blob.example.com/cached/file.csv', 'size': 10,
            'last_success': '2026-11-01T10:00:00', 'is_broken': False}}
        with mock.patch.object(archiver_lib, 'is_check_only_mode', return_value=check_only), \
                app.flask_app.test_request_context():
            html = archiver_helpers.archiver_is_resource_cached_html(resource)
        assert 'Download cached copy' in html
        assert ('Cached on' in html) is shows_date

    @pytest.mark.ckan_config('ckanext-archiver.archive_cloud', 'false')
    def test_archive_mode_reads_archive_cloud_as_boolean(self):
        '''(14) Στο archive mode το "false" διαβαζόταν ως αληθές (μη κενό
        string) και τα uploads στο cloud κατέβαιναν.'''
        from ckan.plugins.toolkit import config
        resource = {'id': 'abc', 'url_type': 'upload',
                    'url': 'https://blob.example.com/file.csv'}
        with mock.patch.object(tasks.requests, 'get') as get, \
                mock.patch.object(tasks.requests, 'head') as head:
            with pytest.raises(tasks.ChooseNotToDownload):
                tasks.download({'site_url': config['ckan.site_url']}, resource)
        get.assert_not_called()
        head.assert_not_called()


@pytest.mark.usefixtures('with_plugins', 'archiver_tables')
@pytest.mark.ckan_config('ckan.plugins', 'archiver')
@CHECK_ONLY
class TestBrokenLinksReport(object):
    '''Η αναφορά σπασμένων συνδέσμων συνεχίζει να λειτουργεί με τα
    αποτελέσματα του check_only (handoff, 22.2).'''

    def test_only_confirmed_broken_links_are_reported(self):
        from ckanext.archiver import reports
        org = factories.Organization()
        dataset = factories.Dataset(owner_org=org['id'], resources=[
            {'url': 'http://example.com/ok.csv', 'format': 'CSV'},
            {'url': 'http://example.com/slow.csv', 'format': 'CSV'},
            {'url': 'http://example.com/gone.csv', 'format': 'CSV'},
        ])
        codes = {'http://example.com/ok.csv': 200,
                 'http://example.com/slow.csv': 503,
                 'http://example.com/gone.csv': 404}

        def respond(url, **kwargs):
            return FakeResponse(codes[url], url=url)

        with mock.patch.object(tasks.requests, 'head', side_effect=respond), \
                mock.patch.object(tasks.requests, 'get', side_effect=respond), \
                mock.patch.object(tasks, '_update_search_index'):
            tasks._update_package(dataset['id'], 'bulk', log)

        report = reports.broken_links_for_organization(org['name'])
        assert report['num_resources'] == 3
        assert report['num_broken_resources'] == 1
        assert report['num_broken_packages'] == 1
        assert [(row['resource_url'], row['status']) for row in report['table']] == \
            [('http://example.com/gone.csv', 'URL request failed')]
        assert report['table'][0]['failure_count'] == 1


def _link(url, resource_id=None):
    return {'id': resource_id or uuid.uuid4().hex, 'url': url, 'format': 'CSV'}


def _timeout(url=None):
    '''Timeout όπως τον δίνει η requests· με url, το αίτημα που έληξε (π.χ. ο
    προορισμός μιας ανακατεύθυνσης).'''
    request = requests.Request('GET', url).prepare() if url else None
    return requests.exceptions.ReadTimeout('slow', request=request)


def _ssl_error(cause, url='https://badcert.example/'):
    '''Σφάλμα SSL τυλιγμένο όπως το δίνει η requests (επαληθευμένο με
    πραγματικούς servers): SSLError → MaxRetryError → SSLError του urllib3.'''
    return requests.exceptions.SSLError(
        MaxRetryError(None, url, Urllib3SSLError(cause)))


def _missing_intermediate():
    '''Όπως στο services.heraklion.gr: ο server στέλνει μόνο το leaf.'''
    return _ssl_error(ssl.SSLCertVerificationError(
        1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: '
           'unable to get local issuer certificate (_ssl.c:1000)'))


@pytest.mark.usefixtures('with_plugins')
@pytest.mark.ckan_config('ckan.plugins', 'archiver')
class TestHostTimeouts(object):
    '''Server που δεν απαντά (HostTimeouts). Τα tests ορίζουν ρητά το όριο· η
    προεπιλογή ελέγχεται στο test_defaults. Με retries=1, ο πρώτος αργός
    σύνδεσμος ενός server δοκιμάζεται 2 φορές και οι επόμενοι μία.'''

    def _check(self, hosts, urls, head, get=None):
        '''(αποτελέσματα, mock του HEAD, mock του GET). Χωρίς get, ένα GET είναι
        λάθος του test· ελέγχεται εδώ, γιατί μια εξαίρεση μέσα στο GET θα την
        «κατάπινε» το _http_check_once.'''
        with mock.patch.object(tasks.requests, 'head', side_effect=head) as head_mock, \
                mock.patch.object(tasks.requests, 'get', side_effect=get) as get_mock:
            outcomes = [tasks._url_check_outcome(_link(url), log, hosts) for url in urls]
        if get is None:
            assert not get_mock.called, 'unexpected GET'
        return outcomes, head_mock, get_mock

    def test_defaults(self):
        assert archiver_lib.check_only_timeout() == 15
        assert archiver_lib.check_only_host_timeout_limit() == 3

    def test_host_includes_the_port(self):
        '''Το http και το https του ίδιου host είναι διαφορετικοί servers.'''
        host = tasks.HostTimeouts.host
        assert host('https://secure.sstpa.gr:8445/a') == 'secure.sstpa.gr:8445'
        assert host('http://User:pw@Example.COM/a') == 'example.com:80'
        assert host('https://example.com/a') == 'example.com:443'
        assert host('not a url') is None

    def test_remaining_links_of_a_server_that_times_out_are_not_requested(self):
        hosts = tasks.HostTimeouts(2, log)
        urls = ['http://dead.example/%d.csv' % i for i in range(5)]
        outcomes, head, _ = self._check(hosts, urls, _timeout())
        # 1ος σύνδεσμος: 2 προσπάθειες· 2ος: μία· οι υπόλοιποι 3 χωρίς αίτημα
        assert head.call_count == 3
        assert all(o['result'] == tasks.URL_TRANSIENT for o in outcomes)
        assert [o['not_requested'] for o in outcomes] == [False, False, True, True, True]
        assert outcomes[2]['reason'].startswith('Not checked: the server dead.example:80')
        assert hosts.skipped == {'dead.example:80': 3}

    def test_connect_timeout_counts_too(self):
        hosts = tasks.HostTimeouts(2, log)
        urls = ['http://dead.example/%d.csv' % i for i in range(3)]
        _, head, _ = self._check(hosts, urls, requests.exceptions.ConnectTimeout('down'))
        assert head.call_count == 3

    def test_slow_failure_counts_by_elapsed_time(self):
        '''Π.χ. DNS που κρεμά: σφάλμα σύνδεσης και όχι timeout, αλλά αργό.'''
        hosts = tasks.HostTimeouts(2, log)
        urls = ['http://gone.example/%d.csv' % i for i in range(4)]
        clock = itertools.count(0, 20)  # κάθε κλήση του monotonic: +20s
        dns = requests.exceptions.ConnectionError('Name resolution failed')
        with mock.patch.object(tasks, 'monotonic', side_effect=lambda: next(clock)):
            outcomes, _, _ = self._check(hosts, urls, dns, get=dns)
        assert [o['not_requested'] for o in outcomes] == [False, False, True, True]

    def test_fast_failures_do_not_count(self):
        '''Π.χ. άρνηση σύνδεσης: δεν κοστίζει χρόνο, δεν μπλοκάρει.'''
        hosts = tasks.HostTimeouts(2, log)
        urls = ['http://refusing.example/%d.csv' % i for i in range(3)]
        refused = requests.exceptions.ConnectionError('Connection refused')
        outcomes, head, _ = self._check(hosts, urls, refused, get=refused)
        assert head.call_count == 6  # 3 σύνδεσμοι × 2 προσπάθειες
        assert not any(o['not_requested'] for o in outcomes)

    def test_a_response_resets_the_counter(self):
        hosts = tasks.HostTimeouts(2, log)
        timeout = _timeout()
        url = 'http://flaky.example/%d.csv'
        # timeout ×2, 404 (ο server ζει), timeout ×2, timeout (χωρίς επανάληψη)
        head = [timeout, timeout, FakeResponse(404, url=url % 1),
                timeout, timeout, timeout]
        outcomes, head_mock, _ = self._check(
            hosts, [url % i for i in range(5)], head,
            get=[FakeResponse(404, url=url % 1)])
        assert outcomes[1]['result'] == tasks.URL_BROKEN
        assert head_mock.call_count == 6
        assert [o['not_requested'] for o in outcomes] == [False, False, False, False, True]

    def test_head_answer_before_a_get_timeout_means_alive(self):
        '''Ο server απάντησε στο HEAD (405) και μετά το GET έληξε: ζει.'''
        hosts = tasks.HostTimeouts(2, log)
        urls = ['http://nohead.example/%d.csv' % i for i in range(4)]
        head = [FakeResponse(405, url=u) for u in urls for _ in range(2)]
        outcomes, head_mock, get_mock = self._check(
            hosts, urls, head, get=[_timeout() for _ in range(8)])
        assert not any(o['not_requested'] for o in outcomes)
        assert head_mock.call_count == 8

    def test_timeout_after_redirect_counts_for_the_link_server(self):
        '''Π.χ. http → https που κρεμά: μετρά ο server του URL του πόρου, ώστε
        οι υπόλοιποι σύνδεσμοί του να παραλείπονται.'''
        hosts = tasks.HostTimeouts(2, log)
        urls = ['http://h.example/%d.csv' % i for i in range(4)]
        outcomes, head, _ = self._check(hosts, urls, _timeout('https://h.example/x.csv'))
        assert [o['not_requested'] for o in outcomes] == [False, False, True, True]
        assert hosts.slow == {'h.example:80': 2}
        assert head.call_count == 3

    def test_a_response_in_any_attempt_means_alive(self):
        '''1η προσπάθεια: 405 στο HEAD και κομμένο GET· 2η: timeout. Ο server
        απάντησε σε μία από τις προσπάθειες, άρα ζει.'''
        hosts = tasks.HostTimeouts(2, log)
        urls = ['http://busy.example/%d.csv' % i for i in range(4)]
        head = []
        for u in urls:
            head += [FakeResponse(405, url=u), _timeout()]
        reset = requests.exceptions.ConnectionError('Connection reset by peer')
        outcomes, head_mock, get_mock = self._check(hosts, urls, head, get=reset)
        assert not any(o['not_requested'] for o in outcomes)
        assert head_mock.call_count == 8
        assert get_mock.call_count == 4

    def test_too_many_redirects_means_alive(self):
        hosts = tasks.HostTimeouts(2, log)
        url = 'http://loop.example/%d.csv'
        timeout = _timeout()
        loop = requests.exceptions.TooManyRedirects('loop')
        # timeout ×2, κύκλος ανακατευθύνσεων (ζει), timeout ×2, timeout
        head = [timeout, timeout, loop, timeout, timeout, timeout]
        outcomes, _, _ = self._check(hosts, [url % i for i in range(5)], head, get=[loop])
        assert outcomes[1]['result'] == tasks.URL_BROKEN
        assert [o['not_requested'] for o in outcomes] == [False, False, False, False, True]

    def test_fast_failures_are_judged_per_attempt(self):
        '''Δύο αποτυχίες των 8s (κάτω από το timeout των 15s) δεν κάνουν τον
        σύνδεσμο «αργό», ακόμη κι αν μαζί ξεπερνούν το timeout.'''
        hosts = tasks.HostTimeouts(2, log)
        clock = [0]
        refused = requests.exceptions.ConnectionError('refused')

        def head(url, **kwargs):
            clock[0] += 8
            raise refused

        urls = ['http://refusing.example/%d.csv' % i for i in range(3)]
        with mock.patch.object(tasks, 'monotonic', side_effect=lambda: clock[0]):
            outcomes, head_mock, _ = self._check(hosts, urls, head, get=refused)
        assert head_mock.call_count == 6
        assert not any(o['not_requested'] for o in outcomes)

    def test_other_servers_are_not_affected(self):
        hosts = tasks.HostTimeouts(2, log)
        timeout = _timeout()
        ok = FakeResponse(200, url='http://alive.example/a.csv')
        urls = ['http://dead.example/1.csv', 'http://dead.example/2.csv',
                'http://alive.example/a.csv', 'http://dead.example/3.csv']
        outcomes, head, _ = self._check(hosts, urls, [timeout] * 3 + [ok])
        assert outcomes[2]['result'] == tasks.URL_OK
        assert outcomes[3]['not_requested']
        assert head.call_count == 4

    def test_limit_zero_disables(self):
        hosts = tasks.HostTimeouts(0, log)
        urls = ['http://dead.example/%d.csv' % i for i in range(3)]
        _, head, _ = self._check(hosts, urls, _timeout())
        assert head.call_count == 6

    def test_without_hosts_every_link_is_requested(self):
        '''update_resource για έναν πόρο: όπως πριν.'''
        with mock.patch.object(tasks.requests, 'head', side_effect=_timeout()) as head, \
                mock.patch.object(tasks.requests, 'get') as get:
            for i in range(3):
                tasks._url_check_outcome(_link('http://dead.example/%d.csv' % i), log)
        assert head.call_count == 6
        assert not get.called


@pytest.mark.usefixtures('with_plugins', 'archiver_tables')
@pytest.mark.ckan_config('ckan.plugins', 'archiver')
@CHECK_ONLY
class TestCertificateErrors(object):
    '''Αποτυχία επαλήθευσης πιστοποιητικού: ίδια με νέα προσπάθεια ή με GET,
    οπότε ο έλεγχος σταματά στο HEAD, χωρίς GET και χωρίς επανάληψη.'''

    def _check(self, urls, head, get=None, hosts=None):
        with mock.patch.object(tasks.requests, 'head', side_effect=head) as head_mock, \
                mock.patch.object(tasks.requests, 'get', side_effect=get) as get_mock:
            outcomes = [tasks._url_check_outcome(_link(url), log, hosts) for url in urls]
        if get is None:
            assert not get_mock.called, 'unexpected GET'
        return outcomes, head_mock, get_mock

    def test_missing_intermediate_stops_at_head(self):
        (outcome,), head, _ = self._check(['https://badcert.example/a.csv'],
                                          _missing_intermediate())
        assert head.call_count == 1
        assert outcome['result'] == tasks.URL_TRANSIENT
        assert outcome['retry'] is False
        assert 'unable to get local issuer certificate' in outcome['reason']

    def test_hostname_mismatch_stops_at_head(self):
        '''Στο urllib3 1.x το λάθος όνομα δεν είναι SSLCertVerificationError.'''
        mismatch = _ssl_error(tasks._HostnameMismatch(
            "hostname 'badcert.example' doesn't match 'other.example'"))
        (outcome,), head, _ = self._check(['https://badcert.example/a.csv'], mismatch)
        assert head.call_count == 1
        assert outcome['retry'] is False

    def test_other_ssl_errors_keep_get_and_retry(self):
        '''Π.χ. σύνδεση που κόπηκε στο handshake: μπορεί να είναι προσωρινό.'''
        other = _ssl_error(ssl.SSLError(1, '[SSL: WRONG_VERSION_NUMBER] wrong version number'))
        (outcome,), head, get = self._check(['https://flaky.example/a.csv'], other, get=other)
        assert head.call_count == 2
        assert get.call_count == 2
        assert outcome['retry'] is True

    def test_certificate_error_on_get_is_not_retried(self):
        '''Π.χ. ο server απαντά 405 στο HEAD και το GET ανακατευθύνει σε
        server με λάθος πιστοποιητικό: χωρίς επανάληψη, αλλά ο server ζει.'''
        url = 'http://alive.example/a.csv'
        (outcome,), head, get = self._check(
            [url], [FakeResponse(405, url=url)], get=_missing_intermediate())
        assert head.call_count == 1
        assert get.call_count == 1
        assert outcome['retry'] is False
        assert outcome['responded']

    def test_detector_survives_self_referencing_errors(self):
        '''Ένας κύκλος στην αλυσίδα δεν πρέπει να κρεμάσει τον worker.'''
        error = requests.exceptions.SSLError('loop')
        error.reason = error
        assert tasks._cert_verify_failed(error) is False

    def test_certificate_errors_do_not_block_the_server(self):
        '''Είναι άμεσες, άρα δεν μετρούν στο HostTimeouts.'''
        hosts = tasks.HostTimeouts(2, log)
        urls = ['https://badcert.example/%d.csv' % i for i in range(3)]
        outcomes, head, _ = self._check(urls, _missing_intermediate(), hosts=hosts)
        assert head.call_count == 3
        assert not any(o['not_requested'] for o in outcomes)

    def test_saved_as_a_temporary_failure(self):
        '''Το αποτέλεσμα αποθηκεύεται όπως πριν (αποτυχία, όχι ακόμα σπασμένος).'''
        _, res = _resource('https://badcert.example/data.csv')
        with mock.patch.object(tasks.requests, 'head',
                               side_effect=_missing_intermediate()) as head, \
                mock.patch.object(tasks.requests, 'get') as get:
            _check(res['id'])
        assert head.call_count == 1
        assert not get.called
        archival = Archival.get_for_resource(res['id'])
        assert archival.status == 'URL check temporarily failed'
        assert archival.failure_count == 1
        assert 'CERTIFICATE_VERIFY_FAILED' in archival.reason


@pytest.mark.usefixtures('with_plugins', 'archiver_tables')
@pytest.mark.ckan_config('ckan.plugins', 'archiver')
@CHECK_ONLY
class TestHostTimeoutsInPackage(object):

    def _pass(self, dataset_id, head, get=None):
        '''Ένα πέρασμα του archiver· τα URL του HEAD με τη σειρά που ζητήθηκαν.'''
        with mock.patch.object(tasks.requests, 'head', side_effect=head) as head_mock, \
                mock.patch.object(tasks.requests, 'get', side_effect=get) as get_mock, \
                mock.patch.object(tasks, 'notify_package'), \
                mock.patch.object(tasks, '_update_search_index'):
            tasks._update_package(dataset_id, 'bulk', log)
        if get is None:
            assert not get_mock.called, 'unexpected GET'
        return [c.args[0] for c in head_mock.call_args_list]

    def _dataset(self, count):
        return factories.Dataset(resources=[
            {'url': 'http://dead.example/%d.csv' % i, 'format': 'CSV'} for i in range(count)])

    def _archivals(self, dataset):
        return [Archival.get_for_resource(r['id']) for r in dataset['resources']]

    def test_dataset_on_a_dead_server(self):
        '''Με το προεπιλεγμένο όριο (3): οι πόροι που δεν ζητήθηκαν
        καταγράφονται ως προσωρινή αποτυχία και μετρούν στις αποτυχίες, αλλά
        κρατούν την προηγούμενη ώρα ελέγχου.'''
        dataset = self._dataset(5)
        requested = self._pass(dataset['id'], _timeout())
        assert len(requested) == 4  # 2 + 1 + 1 προσπάθειες
        archivals = self._archivals(dataset)
        assert all(a.status == 'URL check temporarily failed' for a in archivals)
        assert all(a.failure_count == 1 for a in archivals)
        skipped = [a for a in archivals if a.reason.startswith('Not checked')]
        assert len(skipped) == 2
        assert all(a.updated is None for a in skipped)
        assert all(a.updated is not None for a in archivals if a not in skipped)

    def test_skipped_links_are_checked_first_next_time(self):
        dataset = self._dataset(5)
        urls = [r['url'] for r in dataset['resources']]
        first = self._pass(dataset['id'], _timeout())
        assert first == [urls[0], urls[0], urls[1], urls[2]]
        # Οι 3 και 4 δεν ζητήθηκαν· τώρα ελέγχονται πρώτοι και απαντούν, οπότε
        # ο server δεν «κόβεται» και ελέγχονται όλοι
        ok = [FakeResponse(200, url=u) for u in urls]
        second = self._pass(dataset['id'], ok[3:5] + ok[:3])
        assert second[:2] == urls[3:5]
        assert sorted(second) == sorted(urls)
        archivals = self._archivals(dataset)
        assert all(a.status == 'URL checked successfully' for a in archivals)
        assert all(a.failure_count == 0 for a in archivals)

    @pytest.mark.ckan_config('ckanext.archiver.check_only.host_timeout_limit', '1')
    def test_a_link_is_never_broken_without_being_requested(self):
        '''Αργοί σύνδεσμοι πριν από έναν καλό στον ίδιο server: ο καλός δεν
        γίνεται broken χωρίς να ζητηθεί και ελέγχεται όταν έρθει η σειρά του.'''
        dataset = self._dataset(4)
        good = dataset['resources'][3]

        def head(url, **kwargs):
            if url == good['url']:
                return FakeResponse(200, url=url)
            raise _timeout()

        for _ in range(3):
            assert good['url'] not in self._pass(dataset['id'], head)
        archival = Archival.get_for_resource(good['id'])
        # Οι παραλείψεις ανεβάζουν τον μετρητή έως ένα κάτω από το κατώφλι (3)
        assert archival.failure_count == 2
        assert archival.status == 'URL check temporarily failed'
        assert archival.is_broken is not True
        # 4ο πέρασμα: ελέγχεται πρώτος, απαντά, και ο μετρητής μηδενίζεται
        assert self._pass(dataset['id'], head)[0] == good['url']
        archival = Archival.get_for_resource(good['id'])
        assert archival.status == 'URL checked successfully'
        assert archival.failure_count == 0

    def test_skipping_does_not_touch_a_broken_link(self):
        '''Ένας σύνδεσμος ήδη broken (404) που δεν ζητήθηκε μένει broken.'''
        dataset = self._dataset(4)
        broken = dataset['resources'][3]

        def first(url, **kwargs):
            return FakeResponse(404 if url == broken['url'] else 200, url=url)

        self._pass(dataset['id'], first, get=first)
        before = Archival.get_for_resource(broken['id'])
        assert before.status == 'URL request failed' and before.is_broken is True
        before = (before.status_id, before.reason, before.failure_count, before.updated)
        requested = self._pass(dataset['id'], _timeout())
        assert broken['url'] not in requested
        after = Archival.get_for_resource(broken['id'])
        assert (after.status_id, after.reason, after.failure_count, after.updated) == before
        assert after.is_broken is True

    def test_edited_broken_link_is_not_kept_broken_when_skipped(self):
        '''Το URL ενός broken πόρου άλλαξε και ο νέος σύνδεσμος παραλείπεται: η
        παλιά ετυμηγορία δεν ισχύει, και η αλλαγή μένει για τον πραγματικό
        έλεγχο.'''
        dataset = self._dataset(4)
        broken = dataset['resources'][3]

        def first(url, **kwargs):
            return FakeResponse(404 if url == broken['url'] else 200, url=url)

        self._pass(dataset['id'], first, get=first)
        before = Archival.get_for_resource(broken['id']).resource_timestamp
        test_helpers.call_action('resource_patch', id=broken['id'],
                                 url='http://dead.example/new.csv')
        assert broken['url'] not in self._pass(dataset['id'], _timeout())
        after = Archival.get_for_resource(broken['id'])
        assert after.status == 'URL check temporarily failed'
        assert after.is_broken is not True
        assert after.resource_timestamp == before

    def test_view_with_a_link_never_checked(self):
        '''`ckan archiver view` δεν σκάει με σύνδεσμο που δεν ελέγχθηκε ποτέ.'''
        from ckanext.archiver import utils
        dataset = self._dataset(5)
        self._pass(dataset['id'], _timeout())
        assert any(a.updated is None for a in self._archivals(dataset))
        utils.view()
