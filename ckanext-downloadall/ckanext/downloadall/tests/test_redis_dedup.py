import uuid

from unittest import mock
import pytest

from ckanext.downloadall import dedup
from ckanext.downloadall import tasks


def test_redis_keys_are_scoped_by_site_and_dataset():
    with mock.patch.object(dedup, 'config', {'ckan.site_id': 'test-site'}):
        assert dedup._keys('dataset-id') == (
            'ckan:test-site:downloadall:{dataset-id}:lock',
            'ckan:test-site:downloadall:{dataset-id}:dirty',
        )


def test_acquire_returns_unique_token_only_for_lock_owner():
    with mock.patch.object(dedup, '_eval', side_effect=[1, 0]):
        assert dedup.mark_dirty_and_acquire('dataset-id') is not None
        assert dedup.mark_dirty_and_acquire('dataset-id') is None


def test_invalid_strategy_falls_back_to_request_cache():
    with mock.patch.object(
            dedup, 'config', {dedup.STRATEGY_CONFIG: 'invalid'}):
        assert dedup.get_strategy() == dedup.STRATEGY_REQUEST_CACHE


def test_real_redis_coordination_round_trip():
    dataset_id = 'downloadall-test-{}'.format(uuid.uuid4().hex)
    lock_key, dirty_key = dedup._keys(dataset_id)
    redis_conn = dedup._connect()

    try:
        token = dedup.mark_dirty_and_acquire(dataset_id)
        assert token is not None
        assert dedup.mark_dirty_and_acquire(dataset_id) is None

        assert dedup.prepare_iteration(dataset_id, token)

        # A new change while the job is running is coalesced into another
        # iteration owned by the same job.
        assert dedup.mark_dirty_and_acquire(dataset_id) is None
        assert dedup.finish_iteration(dataset_id, token)
        assert dedup.prepare_iteration(dataset_id, token)
        assert not dedup.finish_iteration(dataset_id, token)

        replacement_token = dedup.mark_dirty_and_acquire(dataset_id)
        assert replacement_token is not None
        assert not dedup.release_lock(dataset_id, 'old-token')
        stored_token = redis_conn.get(lock_key)
        if isinstance(stored_token, bytes):
            stored_token = stored_token.decode('utf-8')
        assert stored_token == replacement_token
        assert dedup.release_lock(dataset_id, replacement_token)
    finally:
        redis_conn.delete(lock_key, dirty_key)


def test_job_without_token_does_not_touch_redis():
    with mock.patch.object(tasks, '_update_zip_once') as update_once, \
            mock.patch.object(dedup, 'prepare_iteration') as prepare:
        tasks.update_zip('dataset-id', 'user', True)

    update_once.assert_called_once_with('dataset-id', 'user', True, None)
    assert not prepare.called


def test_redis_failure_in_worker_runs_job_once_without_coordination():
    with mock.patch.object(
            dedup, 'prepare_iteration',
            side_effect=dedup.RedisDedupError('unavailable')), \
            mock.patch.object(tasks, '_update_zip_once') as update_once:
        tasks.update_zip('dataset-id', 'user', True, 'token')

    update_once.assert_called_once_with('dataset-id', 'user', True, None)


def test_redis_job_processes_again_when_dataset_becomes_dirty():
    with mock.patch.object(
            dedup, 'prepare_iteration', side_effect=[True, True]) as prepare, \
            mock.patch.object(
                dedup, 'finish_iteration',
                side_effect=[True, False]) as finish, \
            mock.patch.object(tasks, '_update_zip_once') as update_once:
        tasks.update_zip('dataset-id', 'user', True, 'token')

    assert prepare.call_count == 2
    assert finish.call_count == 2
    assert update_once.call_count == 2


def test_superseded_redis_job_does_not_process_dataset():
    with mock.patch.object(
            dedup, 'prepare_iteration', return_value=False), \
            mock.patch.object(tasks, '_update_zip_once') as update_once:
        tasks.update_zip('dataset-id', 'user', True, 'old-token')

    assert not update_once.called


def test_failed_redis_job_releases_only_its_own_lock():
    with mock.patch.object(
            dedup, 'prepare_iteration', return_value=True), \
            mock.patch.object(
                dedup, 'release_lock') as release_lock, \
            mock.patch.object(dedup, 'is_dirty', return_value=False), \
            mock.patch.object(tasks.lib, 'enqueue_zip') as enqueue_zip, \
            mock.patch.object(
                tasks, '_update_zip_once',
                side_effect=RuntimeError('failed')):
        with pytest.raises(RuntimeError):
            tasks.update_zip('dataset-id', 'user', True, 'token')

    release_lock.assert_called_once_with('dataset-id', 'token')
    assert not enqueue_zip.called


# OD-857: κενά του μηχανισμού που καλύφθηκαν

def test_change_during_a_failed_job_queues_a_new_job():
    '''#5: αλλαγή όσο έτρεχε το job που απέτυχε (dirty) δεν χάνεται.'''
    with mock.patch.object(dedup, 'prepare_iteration', return_value=True), \
            mock.patch.object(dedup, 'release_lock'), \
            mock.patch.object(dedup, 'is_dirty', return_value=True), \
            mock.patch.object(tasks.lib, 'enqueue_zip') as enqueue_zip, \
            mock.patch.object(tasks, '_update_zip_once',
                              side_effect=RuntimeError('failed')):
        with pytest.raises(RuntimeError):
            tasks.update_zip('dataset-id', 'user', True, 'token')

    enqueue_zip.assert_called_once_with('dataset-id', True)


def test_deadline_is_computed_once_per_job():
    '''#6: οι επαναλήψεις μέσα στο job έχουν το ίδιο χρονικό όριο.'''
    with mock.patch.object(tasks, 'job_deadline', return_value=None) as deadline, \
            mock.patch.object(dedup, 'prepare_iteration', return_value=True), \
            mock.patch.object(dedup, 'finish_iteration', side_effect=[True, False]), \
            mock.patch.object(tasks, '_update_zip_once') as update_once:
        tasks.update_zip('dataset-id', 'user', True, 'token')

    assert deadline.call_count == 1
    assert update_once.call_count == 2


def test_rerun_without_time_left_is_handed_to_a_new_job():
    '''#6: αν δεν μένει χρόνος για νέα επεξεργασία, μπαίνει νέο job.'''
    from time import monotonic
    with mock.patch.object(tasks, 'job_deadline', return_value=monotonic() - 1), \
            mock.patch.object(dedup, 'prepare_iteration', return_value=True), \
            mock.patch.object(dedup, 'finish_iteration', return_value=True), \
            mock.patch.object(dedup, 'release_lock') as release_lock, \
            mock.patch.object(tasks.lib, 'enqueue_zip') as enqueue_zip, \
            mock.patch.object(tasks, '_update_zip_once') as update_once:
        tasks.update_zip('dataset-id', 'user', True, 'token')

    assert update_once.call_count == 1
    release_lock.assert_called_once_with('dataset-id', 'token')
    enqueue_zip.assert_called_once_with('dataset-id', True)


@pytest.mark.ckan_config('ckanext.downloadall.redis_lock_ttl', '600')
@pytest.mark.ckan_config('ckanext.downloadall.job_timeout', '1800')
def test_lock_ttl_covers_the_job_timeout():
    '''#13: το lock δεν λήγει πριν τελειώσει το job.'''
    assert dedup.get_lock_ttl() == 1800 + dedup.LOCK_TTL_MARGIN


@pytest.mark.ckan_config('ckanext.downloadall.redis_lock_ttl', '7200')
@pytest.mark.ckan_config('ckanext.downloadall.job_timeout', '1800')
def test_longer_lock_ttl_is_kept():
    assert dedup.get_lock_ttl() == 7200


def test_is_dirty_round_trip():
    dataset_id = 'downloadall-test-{}'.format(uuid.uuid4().hex)
    lock_key, dirty_key = dedup._keys(dataset_id)
    try:
        assert not dedup.is_dirty(dataset_id)
        token = dedup.mark_dirty_and_acquire(dataset_id)
        assert dedup.is_dirty(dataset_id)
        assert dedup.prepare_iteration(dataset_id, token)
        assert not dedup.is_dirty(dataset_id)
    finally:
        dedup._connect().delete(lock_key, dirty_key)
