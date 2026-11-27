# -*- coding: utf-8 -*-
'''
Tests για την ουρά του DownloadAll (OD-857): παραμετρική ουρά, enqueue μετά το
commit, συντονισμός jobs του dedup.py (request_cache / redis), καμία
αναπαραγωγή από την ενημέρωση του ίδιου του ZIP, και hvd_only.
'''
import pytest
import responses

from ckan import model
from ckan.tests import factories, helpers

from ckanext.downloadall import dedup, lib, tasks
from ckanext.downloadall.plugin import DownloadallPlugin

HVD = '["http://data.europa.eu/bna/c_ac64a52d"]'


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestQueue(object):

    @pytest.mark.ckan_config('ckanext.downloadall.queue', 'downloadall')
    def test_change_queues_a_job_in_the_configured_queue(self, enqueue_calls):
        dataset = factories.Dataset()
        assert enqueue_calls.package_ids() == [dataset['id']]
        call = enqueue_calls[0]
        assert call['queue'] == 'downloadall'
        assert call['fn'] is tasks.update_zip
        assert call['args'] == [dataset['id'], None, True]
        assert call['rq_kwargs'] == {'timeout': 1800}

    def test_job_is_queued_only_after_commit(self, enqueue_calls):
        dataset = factories.Dataset()
        del enqueue_calls[:]
        package = model.Package.get(dataset['id'])
        # Ανοιχτό transaction, ώστε το rollback να είναι πραγματικό
        model.Session.query(model.Package).first()
        DownloadallPlugin().notify(package, 'changed')
        assert enqueue_calls == []
        model.Session.rollback()
        model.Session.commit()
        assert enqueue_calls == []

        package = model.Package.get(dataset['id'])
        DownloadallPlugin().notify(package, 'changed')
        model.Session.commit()
        assert enqueue_calls.package_ids() == [dataset['id']]

    @pytest.mark.ckan_config('ckanext.downloadall.dedup_strategy', 'redis')
    def test_redis_one_pending_job_per_dataset(self, enqueue_calls):
        '''Με redis, οι αλλαγές όσο υπάρχει job για το dataset δεν βάζουν
        δεύτερο job· το job έχει το token του lock.'''
        dataset = factories.Dataset()
        helpers.call_action('package_patch', id=dataset['id'], notes='first change')
        helpers.call_action('package_patch', id=dataset['id'], notes='second change')
        assert enqueue_calls.package_ids() == [dataset['id']]
        assert len(enqueue_calls[0]['args']) == 4

    def test_request_cache_queues_each_change(self, enqueue_calls):
        '''Προεπιλογή (request_cache): ένα job ανά αίτημα, όπως πριν.'''
        dataset = factories.Dataset()
        helpers.call_action('package_patch', id=dataset['id'], notes='change')
        assert enqueue_calls.package_ids() == [dataset['id'], dataset['id']]

    def test_saving_the_zip_does_not_queue_another_job(self, enqueue_calls, http):
        http.add(responses.GET, 'https://example.test/a.csv', body=b'a\n1\n')
        dataset = factories.Dataset(resources=[{'url': 'https://example.test/a.csv', 'format': 'CSV'}])
        del enqueue_calls[:]
        tasks.update_zip(dataset['id'])
        assert enqueue_calls == []
        assert not lib.in_own_update()

    @pytest.mark.ckan_config('ckanext.downloadall.dedup_strategy', 'redis')
    @pytest.mark.usefixtures('with_request_context')
    def test_redis_marks_dirty_again_within_the_same_request(self, enqueue_calls):
        '''#12: δεύτερη αλλαγή στο ίδιο αίτημα, αφού το job ξεκίνησε, πρέπει
        να σημειωθεί dirty, ώστε το job να ξαναεπεξεργαστεί το dataset.'''
        dataset = factories.Dataset()
        token = enqueue_calls[0]['args'][3]
        # Το job ξεκινά: το dirty σβήνεται
        assert dedup.prepare_iteration(dataset['id'], token)
        assert lib.enqueue_zip(dataset['id']) == lib.ALREADY_QUEUED
        assert dedup.is_dirty(dataset['id'])
        assert len(enqueue_calls) == 1

    def test_draft_dataset_queues_no_job(self, enqueue_calls):
        '''#7'''
        factories.Dataset(state='draft')
        assert enqueue_calls == []

    @pytest.mark.ckan_config('ckanext.downloadall.hvd_only', 'true')
    def test_hvd_only_queues_only_hvd_datasets(self, enqueue_calls):
        factories.Dataset()
        hvd = factories.Dataset(extras=[{'key': 'hvd_category', 'value': HVD}])
        assert enqueue_calls.package_ids() == [hvd['id']]
