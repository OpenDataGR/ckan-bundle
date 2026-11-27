# -*- coding: utf-8 -*-
'''
Tests για το job_dedup (OD-856): ένα εκκρεμές job ανά dataset και ποτέ δύο
ταυτόχρονα για το ίδιο dataset. Χρησιμοποιεί την Redis των tests (βλ.
ckan.redis.url στο test ini).
'''
import uuid
from types import SimpleNamespace
from unittest import mock

import pytest
from rq.job import Job

from ckan.exceptions import CkanConfigurationException

from ckanext.archiver import job_dedup

KIND = 'test-dedup'

# Οι κανόνες ισχύουν με τη στρατηγική redis (προεπιλογή)· το none είναι η
# παλιά συμπεριφορά, βλ. TestStrategyNone
WITH_REDIS = pytest.mark.ckan_config('ckanext.%s.dedup_strategy' % KIND, 'redis')


# Κλειδιά jobs της RQ που δημιουργούν τα tests, για καθαρισμό στο τέλος
_CREATED_JOB_KEYS = set()


def _set_job_status(conn, job_id, status, worker_name=None):
    key = Job.key_for(job_id)
    mapping = {'description': 'test', 'status': status}
    if worker_name:
        mapping['worker_name'] = worker_name
    conn.hset(key, mapping=mapping)
    _CREATED_JOB_KEYS.add(key)


@pytest.fixture
def redis_conn():
    conn = job_dedup._redis()
    yield conn
    for key in conn.scan_iter(match='ckanext:*:%s:*' % KIND):
        conn.delete(key)
    for key in list(_CREATED_JOB_KEYS):
        conn.delete(key)
        _CREATED_JOB_KEYS.discard(key)


class FakeQueue(object):
    '''Καταγράφει τα jobs και δημιουργεί το κλειδί rq:job:<id> με status
    queued, όπως η RQ.'''

    def __init__(self, conn):
        self.conn = conn
        self.jobs = []

    def enqueue(self, queue):
        def _enqueue(job_id):
            self.jobs.append((queue, job_id))
            _set_job_status(self.conn, job_id, 'queued')
        return _enqueue

    def last_job_id(self):
        return self.jobs[-1][1]


class as_worker_job(object):
    '''Προσομοίωση εκτέλεσης μέσα σε RQ worker: το job είναι started, όπως
    το δηλώνει η RQ πριν εκτελέσει τη συνάρτησή του.'''

    def __init__(self, job_id, timeout=180, origin=None):
        self.job_id, self.timeout = job_id, timeout
        self._patch = mock.patch(
            'rq.get_current_job',
            return_value=SimpleNamespace(id=job_id, timeout=timeout, origin=origin))

    def __enter__(self):
        _set_job_status(job_dedup._redis(), self.job_id, 'started')
        return self._patch.__enter__()

    def __exit__(self, *exc):
        _set_job_status(job_dedup._redis(), self.job_id, 'finished')
        return self._patch.__exit__(*exc)


def _package_id():
    return 'pkg-' + str(uuid.uuid4())


@WITH_REDIS
class TestEnqueueOnce(object):

    def test_second_request_is_not_queued(self, redis_conn):
        queue, pkg = FakeQueue(redis_conn), _package_id()
        assert job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk')) == job_dedup.QUEUED
        assert job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk')) == job_dedup.ALREADY_QUEUED
        assert len(queue.jobs) == 1

    def test_bulk_request_does_not_add_to_queued_priority(self, redis_conn):
        queue, pkg = FakeQueue(redis_conn), _package_id()
        job_dedup.enqueue_once(KIND, pkg, 'priority', queue.enqueue('priority'))
        assert job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk')) == job_dedup.ALREADY_QUEUED
        assert [q for q, _ in queue.jobs] == ['priority']

    def test_priority_supersedes_queued_bulk_job(self, redis_conn):
        queue, pkg = FakeQueue(redis_conn), _package_id()
        job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk'))
        bulk_job = queue.last_job_id()
        assert job_dedup.enqueue_once(KIND, pkg, 'priority', queue.enqueue('priority')) == job_dedup.QUEUED
        priority_job = queue.last_job_id()

        work = mock.Mock(return_value='done')
        with as_worker_job(priority_job):
            assert job_dedup.run_once(KIND, pkg, work, mock.Mock()) == 'done'
        with as_worker_job(bulk_job):
            assert job_dedup.run_once(KIND, pkg, work, mock.Mock()) == job_dedup.SUPERSEDED
        assert work.call_count == 1

    def test_failed_enqueue_restores_previous_state(self, redis_conn):
        '''Αν αποτύχει το enqueue του νέου job priority, το job της bulk δεν
        μένει ακυρωμένο χωρίς αντικαταστάτη.'''
        queue, pkg = FakeQueue(redis_conn), _package_id()
        job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk'))
        bulk_job = queue.last_job_id()
        with pytest.raises(RuntimeError):
            job_dedup.enqueue_once(KIND, pkg, 'priority',
                                   mock.Mock(side_effect=RuntimeError('redis down')))
        work = mock.Mock(return_value='ran')
        with as_worker_job(bulk_job):
            assert job_dedup.run_once(KIND, pkg, work, mock.Mock()) == 'ran'

    def test_lost_job_is_queued_again(self, redis_conn):
        '''π.χ. μετά από `ckan jobs clear`: το pending δείχνει σε job που δεν υπάρχει.'''
        queue, pkg = FakeQueue(redis_conn), _package_id()
        job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk'))
        redis_conn.delete(Job.key_for(queue.last_job_id()))
        assert job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk')) == job_dedup.QUEUED
        assert len(queue.jobs) == 2

    def test_finished_job_does_not_block_new_requests(self, redis_conn):
        '''Αν το pending δείχνει σε job που έχει τελειώσει (π.χ. μετά από
        αλλαγή της στρατηγικής), νέο αίτημα μπαίνει κανονικά στην ουρά.'''
        queue, pkg = FakeQueue(redis_conn), _package_id()
        job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk'))
        redis_conn.hset(Job.key_for(queue.last_job_id()), 'status', 'finished')
        assert job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk')) == job_dedup.QUEUED
        assert len(queue.jobs) == 2

    def test_new_request_after_job_started_is_queued_once_more(self, redis_conn):
        queue, pkg = FakeQueue(redis_conn), _package_id()
        job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk'))
        with as_worker_job(queue.last_job_id()):
            job_dedup.run_once(KIND, pkg, lambda: None, mock.Mock())
        assert job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk')) == job_dedup.QUEUED


@WITH_REDIS
class TestRunOnce(object):

    def test_changes_while_running_cause_one_rerun(self, redis_conn):
        queue, pkg = FakeQueue(redis_conn), _package_id()
        job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk'))
        results = []

        def work():
            results.append(job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk')))
            results.append(job_dedup.enqueue_once(KIND, pkg, 'priority', queue.enqueue('priority')))

        requeue = mock.Mock()
        with as_worker_job(queue.last_job_id()):
            job_dedup.run_once(KIND, pkg, work, requeue)

        assert results == [job_dedup.RERUN_REQUESTED, job_dedup.RERUN_REQUESTED]
        assert len(queue.jobs) == 1  # κανένα job δεν μπήκε όσο έτρεχε
        requeue.assert_called_once_with('priority')  # μία επανάληψη, στην πιο γρήγορη ουρά

    def test_no_rerun_without_changes(self, redis_conn):
        queue, pkg = FakeQueue(redis_conn), _package_id()
        job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk'))
        requeue = mock.Mock()
        with as_worker_job(queue.last_job_id()):
            job_dedup.run_once(KIND, pkg, lambda: None, requeue)
        requeue.assert_not_called()

    def test_same_dataset_never_runs_concurrently(self, redis_conn):
        pkg = _package_id()
        outcomes = []
        second_requeue = mock.Mock()

        def first_work():
            # Δεύτερος worker ξεκινά job για το ίδιο dataset όσο τρέχει το πρώτο
            with as_worker_job('test-dedup-second'):
                outcomes.append(job_dedup.run_once(
                    KIND, pkg, lambda: 'second ran', second_requeue))

        first_requeue = mock.Mock()
        with as_worker_job('test-dedup-first'):
            job_dedup.run_once(KIND, pkg, first_work, first_requeue)

        assert outcomes == [job_dedup.DEFERRED]
        # Το δεύτερο δεν χάνεται: ξαναμπαίνει στην ουρά όταν τελειώσει το πρώτο
        first_requeue.assert_called_once_with('bulk')

    def test_request_at_the_end_of_a_run_is_not_lost(self, redis_conn):
        '''Αίτημα αμέσως πριν τελειώσει το job: είτε καταγράφεται ως επανάληψη
        είτε μπαίνει κανονικά στην ουρά· ποτέ δεν χάνεται.'''
        queue, pkg = FakeQueue(redis_conn), _package_id()
        job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk'))
        requeue = mock.Mock()
        results = []
        with as_worker_job(queue.last_job_id()):
            job_dedup.run_once(
                KIND, pkg,
                lambda: results.append(job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk'))),
                requeue)
        assert results == [job_dedup.RERUN_REQUESTED]
        requeue.assert_called_once_with('bulk')
        # Μετά το τέλος, νέο αίτημα μπαίνει κανονικά
        assert job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk')) == job_dedup.QUEUED

    def test_dead_running_job_does_not_block_requests(self, redis_conn):
        '''Αν ο worker σκοτώθηκε απότομα, το running δείχνει σε job που δεν
        είναι πια started: νέο αίτημα μπαίνει κανονικά στην ουρά.'''
        queue, pkg = FakeQueue(redis_conn), _package_id()
        _, running_key, _ = job_dedup._keys(KIND, pkg)
        redis_conn.set(running_key, 'test-dedup-killed', ex=3600)
        _set_job_status(redis_conn, 'test-dedup-killed', 'failed')
        assert job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk')) == job_dedup.QUEUED
        assert not redis_conn.exists(running_key)

    def test_rerun_lives_as_long_as_the_running_job(self, redis_conn):
        pkg = _package_id()
        _, _, rerun_key = job_dedup._keys(KIND, pkg)
        ttls = []

        def work():
            job_dedup.enqueue_once(KIND, pkg, 'bulk', mock.Mock())
            ttls.append(redis_conn.ttl(rerun_key))

        with as_worker_job('test-dedup-long', timeout=21600):
            job_dedup.run_once(KIND, pkg, work, mock.Mock())
        assert ttls[0] > 21600

    def test_finishing_job_keeps_another_jobs_running_key(self, redis_conn):
        pkg = _package_id()
        _, running_key, _ = job_dedup._keys(KIND, pkg)

        def work():
            # π.χ. το running έληξε και άλλο job πήρε το dataset
            redis_conn.set(running_key, 'test-dedup-other', ex=3600)

        with as_worker_job('test-dedup-first'):
            job_dedup.run_once(KIND, pkg, work, mock.Mock())
        assert job_dedup._text(redis_conn.get(running_key)) == 'test-dedup-other'

    def test_running_key_released_on_error(self, redis_conn):
        pkg = _package_id()
        with as_worker_job('test-dedup-error'):
            with pytest.raises(RuntimeError):
                job_dedup.run_once(KIND, pkg, mock.Mock(side_effect=RuntimeError('boom')), mock.Mock())
        _, running_key, _ = job_dedup._keys(KIND, pkg)
        assert not redis_conn.exists(running_key)

    def test_job_queued_before_deployment_runs(self, redis_conn):
        '''Jobs χωρίς κλειδί pending (π.χ. από πριν την αλλαγή) εκτελούνται.'''
        work = mock.Mock(return_value='ran')
        with as_worker_job('test-dedup-old'):
            assert job_dedup.run_once(KIND, _package_id(), work, mock.Mock()) == 'ran'

    def test_outside_worker_runs_directly(self, redis_conn):
        pkg = _package_id()
        with mock.patch('rq.get_current_job', return_value=None):
            assert job_dedup.run_once(KIND, pkg, lambda: 'direct', mock.Mock()) == 'direct'
        assert not any(redis_conn.scan_iter(match='ckanext:*:%s:*%s' % (KIND, pkg)))


def _origin(queue):
    from ckan.lib.jobs import add_queue_name_prefix
    return add_queue_name_prefix(queue)


@WITH_REDIS
class TestSecondReview(object):
    '''Διορθώσεις μετά το δεύτερο code review.'''

    def test_priority_job_does_not_yield_to_waiting_bulk_job(self, redis_conn):
        '''(7) Job της priority χωρίς pending (π.χ. από πριν το deploy) δεν
        υποχωρεί σε job της bulk· εκτελείται και ακυρώνει εκείνο.'''
        queue, pkg = FakeQueue(redis_conn), _package_id()
        job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk'))
        bulk_job = queue.last_job_id()
        work = mock.Mock(return_value='ran')
        with as_worker_job('test-dedup-legacy-priority', origin=_origin('priority')):
            assert job_dedup.run_once(KIND, pkg, work, mock.Mock()) == 'ran'
        with as_worker_job(bulk_job, origin=_origin('bulk')):
            assert job_dedup.run_once(KIND, pkg, work, mock.Mock()) == job_dedup.SUPERSEDED
        assert work.call_count == 1

    def test_bulk_job_yields_to_waiting_priority_job(self, redis_conn):
        queue, pkg = FakeQueue(redis_conn), _package_id()
        job_dedup.enqueue_once(KIND, pkg, 'priority', queue.enqueue('priority'))
        work = mock.Mock()
        with as_worker_job('test-dedup-legacy-bulk', origin=_origin('bulk')):
            assert job_dedup.run_once(KIND, pkg, work, mock.Mock()) == job_dedup.SUPERSEDED
        work.assert_not_called()

    @pytest.mark.ckan_config('ckanext.%s.queue.priority' % KIND, 'custom_priority')
    def test_queue_of_job_follows_configured_names(self):
        job = SimpleNamespace(origin=_origin('custom_priority'))
        assert job_dedup._job_queue(KIND, job) == 'priority'
        assert job_dedup._job_queue(KIND, SimpleNamespace(origin=_origin('other'))) == 'bulk'
        assert job_dedup._job_queue(KIND, SimpleNamespace()) == 'bulk'

    def test_job_of_dead_worker_does_not_block_requests(self, redis_conn):
        '''(8) SIGKILL στον worker (π.χ. restart του container): το job μένει
        started, αλλά ο worker δεν ζει πια. Νέο αίτημα μπαίνει στην ουρά, αντί
        να γίνει επανάληψη που δεν θα εκτελεστεί ποτέ.'''
        queue, pkg = FakeQueue(redis_conn), _package_id()
        _, running_key, _ = job_dedup._keys(KIND, pkg)
        redis_conn.set(running_key, 'test-dedup-orphan', ex=3600)
        _set_job_status(redis_conn, 'test-dedup-orphan', 'started',
                        worker_name='test-dedup-gone-worker')
        assert job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk')) == job_dedup.QUEUED
        assert not redis_conn.exists(running_key)

    def test_job_of_live_worker_gets_a_rerun(self, redis_conn):
        from rq.worker import Worker
        queue, pkg = FakeQueue(redis_conn), _package_id()
        _, running_key, _ = job_dedup._keys(KIND, pkg)
        worker_key = Worker.redis_worker_namespace_prefix + 'test-dedup-live-worker'
        redis_conn.hset(worker_key, 'state', 'busy')
        try:
            redis_conn.set(running_key, 'test-dedup-busy', ex=3600)
            _set_job_status(redis_conn, 'test-dedup-busy', 'started',
                            worker_name='test-dedup-live-worker')
            assert job_dedup.enqueue_once(KIND, pkg, 'bulk', queue.enqueue('bulk')) == \
                job_dedup.RERUN_REQUESTED
            assert queue.jobs == []
        finally:
            redis_conn.delete(worker_key)


@pytest.mark.ckan_config('ckanext.%s.dedup_strategy' % KIND, 'none')
class TestStrategyNone(object):
    '''Διακόπτης none: η παλιά συμπεριφορά, χωρίς κλειδιά στη Redis.'''

    def test_every_request_is_queued(self, redis_conn):
        enqueue_fn = mock.Mock()
        pkg = _package_id()
        assert job_dedup.enqueue_once(KIND, pkg, 'bulk', enqueue_fn) == job_dedup.QUEUED
        assert job_dedup.enqueue_once(KIND, pkg, 'bulk', enqueue_fn) == job_dedup.QUEUED
        assert enqueue_fn.call_args_list == [mock.call(None), mock.call(None)]
        assert not any(redis_conn.scan_iter(match='ckanext:*:%s:*' % KIND))

    def test_job_runs_directly(self, redis_conn):
        with as_worker_job('test-dedup-none'):
            assert job_dedup.run_once(KIND, _package_id(), lambda: 'ran', mock.Mock()) == 'ran'
        assert not any(redis_conn.scan_iter(match='ckanext:*:%s:*' % KIND))


class TestStrategyConfig(object):

    def test_default_is_redis(self):
        assert job_dedup.get_strategy('qa') == 'redis'
        assert job_dedup.get_strategy('archiver') == 'redis'

    @pytest.mark.ckan_config('ckanext.archiver.dedup_strategy', 'bogus')
    def test_unknown_value_is_rejected(self):
        with pytest.raises(CkanConfigurationException):
            job_dedup.get_strategy('archiver')

    @pytest.mark.ckan_config('ckanext.archiver.dedup_strategy', 'bogus')
    def test_plugin_refuses_to_start(self):
        from ckan.plugins.toolkit import config
        from ckanext.archiver.plugin import ArchiverPlugin
        with pytest.raises(CkanConfigurationException):
            ArchiverPlugin().update_config(config)
