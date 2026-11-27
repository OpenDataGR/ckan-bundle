# -*- coding: utf-8 -*-
'''
Tests για τη διατήρηση του πόρου ZIP «Λήψη όλων» σε package_update (π.χ. από
harvesters WMS/CSW/DCAT/CKAN ή API scripts που στέλνουν νέα λίστα πόρων χωρίς
το ZIP).
'''
import os
import zipfile
from unittest import mock

import pytest
import responses

from ckan import model
from ckan.lib.uploader import get_resource_uploader
from ckan.logic import schema as ckan_schema
from ckan.plugins import toolkit
from ckan.tests import factories, helpers

from ckanext.downloadall import cli, dedup, eligibility, freshness, lib, storage, tasks

CSV_V1 = b'a,b\n1,2\n'
CSV_V2 = b'a,b\n1,2\n3,4\n'


def _build_dataset_with_zip(http, url='https://example.com/data.csv',
                            body=CSV_V1, extra_resources=None):
    resources = [{'url': url, 'name': 'Data', 'format': 'CSV'}]
    if extra_resources:
        resources.extend(extra_resources)
    dataset = factories.Dataset(resources=resources)
    http.add(responses.GET, url, body=body, status=200)
    tasks.update_zip(dataset['id'])
    shown = helpers.call_action('package_show', id=dataset['id'])
    zip_res = freshness.zip_resource(shown)
    assert zip_res is not None
    return shown, zip_res


def _zip_local_path(zip_res):
    return get_resource_uploader({'id': zip_res['id']}).get_path(zip_res['id'])


@pytest.mark.usefixtures('clean_db', 'with_plugins')
class TestPreserveZipOnPackageUpdate(object):

    def test_harvester_package_update_preserves_zip_and_updates_in_place(
            self, http, enqueue_calls):
        '''Ένας harvester στέλνει package_update με νέα λίστα πόρων (χωρίς id
        και χωρίς το ZIP). Το ZIP κρατά το ίδιο id, το κουμπί γίνεται stale
        (όχι none/hidden) και το επόμενο build ενημερώνει τον ίδιο πόρο ZIP.'''
        shown, zip_res = _build_dataset_with_zip(http)
        old_zip_id = zip_res['id']
        old_fingerprint = zip_res['downloadall_fingerprint']
        old_size = zip_res['size']
        old_file = _zip_local_path(zip_res)
        old_extras = dict(model.Resource.get(old_zip_id).extras or {})
        assert os.path.exists(old_file)

        enqueue_calls.clear()
        new_url = 'https://example.com/data-v2.csv'
        http.add(responses.GET, new_url, body=CSV_V2, status=200)

        payload = {
            'id': shown['id'],
            'name': shown['name'],
            'title': shown['title'],
            'resources': [
                {'url': new_url, 'name': 'Data v2', 'format': 'CSV'},
            ],
        }
        original_resources_snapshot = list(payload['resources'])

        updated = helpers.call_action('package_update', **payload)

        # Δεν αλλοιώνεται το dict/list του caller
        assert payload['resources'] == original_resources_snapshot

        # Το ZIP έμεινε στον ίδιο πόρο με τα ίδια μεταδεδομένα, extras και αρχείο
        preserved = freshness.zip_resource(updated)
        assert preserved is not None
        assert preserved['id'] == old_zip_id
        assert preserved['url_type'] == 'upload'
        assert preserved['size'] == old_size
        assert preserved['downloadall_fingerprint'] == old_fingerprint
        assert preserved['downloadall_metadata_modified'] == \
            zip_res['downloadall_metadata_modified']
        model.Session.expire_all()
        assert dict(model.Resource.get(old_zip_id).extras or {}) == old_extras
        assert os.path.exists(old_file)

        # Το κουμπί παραμένει ορατό (stale), δεν εξαφανίζεται
        assert freshness.zip_state(updated) == freshness.STATE_STALE

        # Μπήκε αναγκαστικό job χωρίς αύξηση του downloadall_retries
        assert enqueue_calls.package_ids() == [shown['id']]
        assert enqueue_calls[0]['args'][:3] == [shown['id'], None, False]
        assert enqueue_calls[0]['kwargs'] == {'count_retry': False}

        # Το επόμενο build ενημερώνει τον ΙΔΙΟ πόρο ZIP (ίδιο id)
        call = enqueue_calls[0]
        call['fn'](*call['args'], **call['kwargs'])
        rebuilt = helpers.call_action('package_show', id=shown['id'])
        rebuilt_zip = freshness.zip_resource(rebuilt)
        assert rebuilt_zip is not None
        assert rebuilt_zip['id'] == old_zip_id
        assert rebuilt_zip['downloadall_fingerprint'] != old_fingerprint
        assert freshness.zip_state(rebuilt) == freshness.STATE_READY

    def test_spatial_default_schema_preserves_zip_and_downloadall_extras(
            self, http, enqueue_calls):
        '''Όπως στον spatial/CSW harvester (base.py): το context περνάει
        default_update_package_schema(). Τα downloadall_* extras διατηρούνται.'''
        shown, zip_res = _build_dataset_with_zip(http)
        old_zip_id = zip_res['id']

        context = {
            'model': model,
            'session': model.Session,
            'ignore_auth': True,
            'schema': ckan_schema.default_update_package_schema(),
        }
        payload = {
            'id': shown['id'],
            'name': shown['name'],
            'title': 'Updated by CSW',
            'resources': [
                {'url': 'https://example.com/csw-layer.csv',
                 'name': 'Layer', 'format': 'CSV'},
            ],
        }
        updated = toolkit.get_action('package_update')(context, payload)

        preserved = freshness.zip_resource(updated)
        assert preserved is not None
        assert preserved['id'] == old_zip_id
        assert preserved['downloadall_fingerprint'] == \
            zip_res['downloadall_fingerprint']
        assert preserved['downloadall_metadata_modified'] == \
            zip_res['downloadall_metadata_modified']

    def test_unchanged_resources_with_same_ids_forces_rebuild_without_counting_retry(
            self, http, enqueue_calls):
        '''Όπως σε WMS/CSW harvester με preserve_resource_ids_by_url: ίδιοι
        πόροι με ίδια id/URL χωρίς το ZIP. Το ZIP μένει ready όσο χτίζεται,
        αλλά το job ξαναχτίζει αναγκαστικά στον ίδιο πόρο ZIP (ώστε να πιάσει
        αλλαγμένα δεδομένα πίσω από το ίδιο URL) χωρίς να αυξάνει το
        downloadall_retries.'''
        url = 'https://example.com/wfs-data.csv'
        failing_url = 'https://example.com/temp-down.csv'
        http.add(responses.GET, failing_url, status=503)
        shown, zip_res = _build_dataset_with_zip(
            http,
            url=url,
            body=CSV_V1,
            extra_resources=[
                {'url': failing_url, 'name': 'Temp down', 'format': 'CSV'},
            ],
        )
        data_res = [r for r in shown['resources'] if r['id'] != zip_res['id']]
        assert freshness.build_count(zip_res, freshness.RETRIES_FIELD) == 0

        # Τα δεδομένα πίσω από το ίδιο URL αλλάζουν χωρίς αλλαγή μεταδεδομένων/id
        http.replace(responses.GET, url, body=CSV_V2, status=200)
        enqueue_calls.clear()

        payload = dict(shown)
        payload['resources'] = data_res

        updated = helpers.call_action('package_update', **payload)
        preserved = freshness.zip_resource(updated)
        assert preserved['id'] == zip_res['id']
        assert freshness.zip_state(updated) == freshness.STATE_READY

        # Μπήκε αναγκαστικό job χωρίς count_retry
        assert len(enqueue_calls) == 1
        call = enqueue_calls[0]
        assert call['args'][:3] == [shown['id'], None, False]
        assert call['kwargs'] == {'count_retry': False}

        # Εκτέλεση του queued job: ξανακατεβάζει το URL στον ΙΔΙΟ πόρο ZIP
        before_calls = len(http.calls)
        call['fn'](*call['args'], **call['kwargs'])
        assert len(http.calls) > before_calls

        after = helpers.call_action('package_show', id=shown['id'])
        after_zip = freshness.zip_resource(after)
        assert after_zip['id'] == zip_res['id']
        # Το νέο ZIP περιέχει τα ανανεωμένα δεδομένα CSV_V2
        with zipfile.ZipFile(_zip_local_path(after_zip)) as zf:
            csv_members = [n for n in zf.namelist() if n.endswith('.csv')]
            assert len(csv_members) == 1
            assert zf.read(csv_members[0]) == CSV_V2
        # Το harvest rebuild ΔΕΝ μετράει ως --retry-failed επανάληψη
        assert freshness.build_count(after_zip, freshness.RETRIES_FIELD) == 0

        # Αντίθετα, ένα ρητό --retry-failed (count_retry default) μετράει κανονικά
        tasks.update_zip(shown['id'], None, False)
        after_retry = helpers.call_action('package_show', id=shown['id'])
        assert freshness.build_count(
            freshness.zip_resource(after_retry), freshness.RETRIES_FIELD) == 1

    @pytest.mark.usefixtures('clean_dedup_keys')
    @pytest.mark.ckan_config('ckanext.downloadall.dedup_strategy', 'redis')
    def test_redis_refresh_reaches_pending_job_without_counting_retry(
            self, http, enqueue_calls):
        '''Με dedup_strategy=redis, αν υπάρχει ήδη εκκρεμές κανονικό job, ένα
        harvest package_update περνάει FORCE_REFRESH σε αυτό χωρίς να αυξηθεί
        το downloadall_retries.'''
        url = 'https://example.com/redis-wfs.csv'
        http.add(responses.GET, url, body=CSV_V1, status=200)
        dataset = factories.Dataset(
            resources=[{'url': url, 'name': 'Data', 'format': 'CSV'}])
        # Ολοκληρώνεται το αρχικό job (ώστε να φτιαχτεί το ZIP και να ελευθερωθεί το lock)
        assert len(enqueue_calls) == 1
        initial_call = enqueue_calls[0]
        initial_call['fn'](*initial_call['args'], **initial_call['kwargs'])

        shown = helpers.call_action('package_show', id=dataset['id'])
        zip_res = freshness.zip_resource(shown)
        assert zip_res is not None
        data_res = [r for r in shown['resources'] if r['id'] != zip_res['id']]

        # Ένα κανονικό job κρατά ήδη το lock της Redis
        enqueue_calls.clear()
        assert lib.enqueue_zip(shown['id'], skip_if_no_changes=True) == lib.QUEUED
        assert len(enqueue_calls) == 1
        pending_call = enqueue_calls[0]

        # Ενημερώνονται τα δεδομένα στο URL και φτάνει harvest package_update
        http.replace(responses.GET, url, body=CSV_V2, status=200)
        payload = dict(shown)
        payload['resources'] = data_res
        helpers.call_action('package_update', **payload)

        # Δεν μπήκε δεύτερο job· το αίτημα FORCE_REFRESH πέρασε στο υπάρχον
        assert len(enqueue_calls) == 1

        before_calls = len(http.calls)
        pending_call['fn'](*pending_call['args'], **pending_call['kwargs'])
        assert len(http.calls) > before_calls

        after = helpers.call_action('package_show', id=shown['id'])
        after_zip = freshness.zip_resource(after)
        assert after_zip['id'] == zip_res['id']
        assert freshness.build_count(after_zip, freshness.RETRIES_FIELD) == 0
        with zipfile.ZipFile(_zip_local_path(after_zip)) as zf:
            csv_members = [n for n in zf.namelist() if n.endswith('.csv')]
            assert zf.read(csv_members[0]) == CSV_V2

    @pytest.mark.usefixtures('clean_dedup_keys')
    def test_redis_refresh_does_not_downgrade_retry_force(self):
        '''Αν υπάρχει ήδη αίτημα FORCE_RETRY από --retry-failed, ένα
        FORCE_REFRESH δεν το υποβαθμίζει.'''
        assert dedup.mark_dirty_and_acquire('ds-force-order') is not None
        assert dedup.mark_dirty_and_acquire(
            'ds-force-order', force=dedup.FORCE_RETRY) is None
        assert dedup.mark_dirty_and_acquire(
            'ds-force-order', force=dedup.FORCE_REFRESH) is None
        assert dedup.take_force('ds-force-order') == dedup.FORCE_RETRY

    def test_failed_package_update_clears_forced_rebuild_marker(
            self, http, enqueue_calls):
        '''Αν αποτύχει ένα package_update (π.χ. ValidationError), δεν μένει
        σημείωση forced rebuild στο Session.info για επόμενο commit.'''
        shown, zip_res = _build_dataset_with_zip(http)
        enqueue_calls.clear()

        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                'package_update',
                id=shown['id'],
                name='INVALID NAME WITH SPACES!',
                resources=[{'url': 'https://example.com/bad.csv',
                            'name': 'Bad', 'format': 'CSV'}],
            )

        assert not model.Session().info.get(lib._AFTER_COMMIT_FORCE_KEY)
        # Επόμενο κανονικό package_patch βάζει κανονικό job (skip_if_no_changes=True)
        helpers.call_action('package_patch', id=shown['id'], notes='after error')
        assert len(enqueue_calls) == 1
        assert enqueue_calls[0]['args'][:3] == [shown['id'], None, True]
        assert enqueue_calls[0]['kwargs'] == {}

    def test_package_update_by_name_preserves_zip(self, http, enqueue_calls):
        shown, zip_res = _build_dataset_with_zip(http)
        updated = helpers.call_action(
            'package_update',
            name=shown['name'],
            title=shown['title'],
            resources=[
                {'url': 'https://example.com/other.csv',
                 'name': 'Other', 'format': 'CSV'},
            ],
        )
        assert freshness.zip_resource(updated)['id'] == zip_res['id']

    def test_partial_update_without_resources_key_keeps_all_resources(
            self, http, enqueue_calls):
        '''Επεξεργασία μεταδεδομένων (allow_partial_update=True, χωρίς κλειδί
        resources): δεν πρέπει να προστεθεί resources=[zip] και να χαθούν οι
        υπόλοιποι πόροι.'''
        shown, zip_res = _build_dataset_with_zip(http)
        data_res_ids = {
            r['id'] for r in shown['resources'] if r['id'] != zip_res['id']
        }

        context = {
            'model': model,
            'session': model.Session,
            'ignore_auth': True,
            'allow_partial_update': True,
        }
        updated = toolkit.get_action('package_update')(
            context, {'id': shown['id'], 'title': 'Edited title only'})

        after_ids = {r['id'] for r in updated['resources']}
        assert zip_res['id'] in after_ids
        assert data_res_ids.issubset(after_ids)

    def test_package_patch_metadata_and_resources(self, http, enqueue_calls):
        shown, zip_res = _build_dataset_with_zip(http)

        # 1. Metadata-only patch
        patched_meta = helpers.call_action(
            'package_patch', id=shown['id'], notes='Patched notes')
        assert freshness.zip_resource(patched_meta)['id'] == zip_res['id']

        # 2. Patch που αντικαθιστά τη λίστα resources χωρίς το ZIP
        patched_res = helpers.call_action(
            'package_patch',
            id=shown['id'],
            resources=[{'url': 'https://example.com/patched.csv',
                        'name': 'Patched', 'format': 'CSV'}],
        )
        assert freshness.zip_resource(patched_res)['id'] == zip_res['id']
        assert len(patched_res['resources']) == 2

    def test_resource_delete_explicitly_deletes_zip(self, http, enqueue_calls):
        '''Ρητή διαγραφή του ZIP με resource_delete (από χρήστη/API, εκτός
        lib.own_update) εξαιρείται και σβήνει κανονικά το ZIP.'''
        shown, zip_res = _build_dataset_with_zip(http)

        helpers.call_action('resource_delete', id=zip_res['id'])

        after = helpers.call_action('package_show', id=shown['id'])
        assert freshness.zip_resource(after) is None
        assert len(after['resources']) == 1

    def test_resource_delete_of_data_resource_keeps_zip(
            self, http, enqueue_calls):
        shown, zip_res = _build_dataset_with_zip(
            http,
            extra_resources=[{'url': 'https://example.com/extra.csv',
                              'name': 'Extra', 'format': 'CSV'}],
        )
        http.add(responses.GET, 'https://example.com/extra.csv',
                 body=CSV_V2, status=200)
        data_res = [r for r in shown['resources'] if r['id'] != zip_res['id']]

        helpers.call_action('resource_delete', id=data_res[0]['id'])

        after = helpers.call_action('package_show', id=shown['id'])
        assert freshness.zip_resource(after)['id'] == zip_res['id']
        assert len(after['resources']) == 2

    def test_empty_resources_list_preserves_until_job_deletes_cleanly(
            self, http, enqueue_calls):
        '''Αν ο harvester αδειάσει όλους τους πόρους (resources=[]), το ZIP δεν
        σβήνεται αθόρυβα από το package_update· το επόμενο job το σβήνει καθαρά
        με resource_delete (ώστε να καθαριστεί και το blob στο storage).'''
        shown, zip_res = _build_dataset_with_zip(http)
        enqueue_calls.clear()

        updated = helpers.call_action(
            'package_update',
            id=shown['id'],
            name=shown['name'],
            title=shown['title'],
            resources=[],
        )
        assert freshness.zip_resource(updated)['id'] == zip_res['id']
        assert freshness.zip_state(updated) == freshness.STATE_HIDDEN
        assert enqueue_calls.package_ids() == [shown['id']]

        tasks.update_zip(shown['id'])
        after = helpers.call_action('package_show', id=shown['id'])
        assert freshness.zip_resource(after) is None
        assert after['resources'] == []

    def test_duplicate_zips_preserved_on_update_and_cleaned_by_cleanup(
            self, http, enqueue_calls):
        '''Αν υπάρχουν διπλά ZIP στο dataset, το package_update τα διατηρεί όλα
        (ώστε να μην ορφανέψει blob) και το cleanup σβήνει το διπλό μέσω
        resource_delete.'''
        shown, zip_res = _build_dataset_with_zip(http)
        dup_zip = helpers.call_action(
            'resource_create',
            package_id=shown['id'],
            url='https://example.com/dup.zip',
            name='All resource data',
            format='ZIP',
            downloadall_metadata_modified=shown['metadata_modified'],
        )

        updated = helpers.call_action(
            'package_update',
            id=shown['id'],
            name=shown['name'],
            title=shown['title'],
            resources=[{'url': 'https://example.com/new.csv',
                        'name': 'New', 'format': 'CSV'}],
        )
        zips = [r for r in updated['resources']
                if eligibility.is_zip_resource(r)]
        assert [r['id'] for r in zips] == [zip_res['id'], dup_zip['id']]

        with mock.patch.object(storage, 'cloudstorage_enabled',
                               return_value=False):
            zip_plan, _blobs = cli._cleanup_plan()
            assert [item['resource_id'] for item in zip_plan] == [dup_zip['id']]
            deleted, failed = cli._apply_cleanup(zip_plan, [], limit=0)
            assert (deleted, failed) == (1, 0)

        after = helpers.call_action('package_show', id=shown['id'])
        remaining_zips = [r for r in after['resources']
                          if eligibility.is_zip_resource(r)]
        assert [r['id'] for r in remaining_zips] == [zip_res['id']]

    def test_caller_already_including_zip_does_not_duplicate(
            self, http, enqueue_calls):
        shown, zip_res = _build_dataset_with_zip(http)
        updated = helpers.call_action(
            'package_update',
            id=shown['id'],
            name=shown['name'],
            title='Title updated with full resources',
            resources=shown['resources'],
        )
        zips = [r for r in updated['resources']
                if eligibility.is_zip_resource(r)]
        assert [r['id'] for r in zips] == [zip_res['id']]

    def test_package_update_to_deleted_does_not_force_a_rebuild(
            self, http, enqueue_calls):
        '''Ένα package_update που διαγράφει το dataset (state=deleted) με λίστα
        πόρων χωρίς το ZIP δεν βάζει αναγκαστικό job: το dataset δεν χρειάζεται
        πια ZIP.'''
        shown, zip_res = _build_dataset_with_zip(http)
        enqueue_calls.clear()

        payload = dict(shown)
        payload['state'] = 'deleted'
        payload['resources'] = [r for r in shown['resources']
                                if r['id'] != zip_res['id']]
        helpers.call_action('package_update', **payload)

        assert enqueue_calls == []

    def test_dictize_applies_plugin_show_package_schema_converters(
            self, http, enqueue_calls):
        '''Παλινδρόμηση scheming (dcat_ap_gr_recommended.yaml): πεδία πόρου
        αποθηκευμένα ως JSON string στα extras (π.χ. language_options='[]')
        περνούν από το show_package_schema του package plugin ώστε το
        package_update validation να τα πάρει στη μορφή που περιμένει.'''
        import json
        import ckan.lib.plugins as lib_plugins

        shown, zip_res = _build_dataset_with_zip(http)
        # Αποθήκευση JSON string στα extras του ZIP, όπως κάνει το scheming
        orm_zip = model.Resource.get(zip_res['id'])
        extras = dict(orm_zip.extras or {})
        extras['language_options'] = '[]'
        orm_zip.extras = extras
        model.Session.commit()

        real_plugin = lib_plugins.lookup_package_plugin('dataset')
        orig_show = real_plugin.show_package_schema
        orig_update = real_plugin.update_package_schema

        def fake_show_schema():
            schema = orig_show()
            schema['resources']['language_options'] = [
                lambda v: json.loads(v) if isinstance(v, str) else v
            ]
            return schema

        def fake_update_schema():
            schema = orig_update()

            def must_be_list(value, _context):
                if not isinstance(value, list):
                    raise toolkit.Invalid(
                        'unexpected choice %r' % (value,))
                return json.dumps(value)

            schema['resources']['language_options'] = [
                toolkit.get_validator('ignore_missing'), must_be_list
            ]
            return schema

        with mock.patch.object(real_plugin, 'show_package_schema',
                               side_effect=fake_show_schema), \
                mock.patch.object(real_plugin, 'update_package_schema',
                                  side_effect=fake_update_schema):
            updated = helpers.call_action(
                'package_update',
                id=shown['id'],
                name=shown['name'],
                title=shown['title'],
                resources=[{'url': 'https://example.com/scheming.csv',
                            'name': 'Scheming', 'format': 'CSV'}],
            )

        preserved = freshness.zip_resource(updated)
        assert preserved is not None
        assert preserved['id'] == zip_res['id']


def _run_retry_job_with_change_in_first_iteration(http, enqueue_calls, change):
    '''Job --retry-failed με Redis· όσο τρέχει η 1η επανάληψη, το dataset
    αλλάζει (change), οπότε το ίδιο job κάνει και 2η επανάληψη.

    Επιστρέφει ανά επανάληψη (έλεγχος αλλαγών, λήψεις) και τον πόρο ZIP στο
    τέλος.'''
    url = 'https://example.com/two-iterations.csv'
    http.add(responses.GET, url, body=CSV_V1, status=200)
    dataset = factories.Dataset(
        resources=[{'url': url, 'name': 'Data', 'format': 'CSV'}])
    # Το αρχικό job φτιάχνει το ZIP και αφήνει το lock
    assert len(enqueue_calls) == 1
    initial_call = enqueue_calls[0]
    initial_call['fn'](*initial_call['args'], **initial_call['kwargs'])

    enqueue_calls.clear()
    assert lib.enqueue_zip(dataset['id'], skip_if_no_changes=False) == \
        lib.QUEUED
    assert len(enqueue_calls) == 1
    retry_call = enqueue_calls[0]

    real_once = tasks._update_zip_once
    iterations = []

    def once(package_id, user, skip_if_no_changes, deadline, **kwargs):
        before = len(http.calls)
        result = real_once(package_id, user, skip_if_no_changes, deadline,
                           **kwargs)
        iterations.append((skip_if_no_changes, len(http.calls) - before))
        if len(iterations) == 1:
            change(dataset['id'])
        return result

    with mock.patch.object(tasks, '_update_zip_once', side_effect=once):
        retry_call['fn'](*retry_call['args'], **retry_call['kwargs'])

    after = helpers.call_action('package_show', id=dataset['id'])
    return iterations, freshness.zip_resource(after)


@pytest.mark.usefixtures('clean_db', 'with_plugins', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckanext.downloadall.dedup_strategy', 'redis')
class TestForcedRebuildAcrossIterations(object):
    '''Οι ρυθμίσεις ενός job --retry-failed ισχύουν μόνο για την 1η επανάληψη
    του· οι επόμενες τις παίρνουν από το :force του Redis.'''

    def test_harvest_during_retry_job_does_not_count_a_second_retry(
            self, http, enqueue_calls):
        def harvest(package_id):
            shown = helpers.call_action('package_show', id=package_id)
            payload = dict(shown)
            payload['resources'] = [r for r in shown['resources']
                                    if not eligibility.is_zip_resource(r)]
            helpers.call_action('package_update', **payload)

        iterations, zip_res = _run_retry_job_with_change_in_first_iteration(
            http, enqueue_calls, harvest)

        # Το harvest ξαναχτίζει αναγκαστικά (χωρίς έλεγχο αλλαγών, με λήψη στη
        # 2η επανάληψη), αλλά μετρά μόνο το --retry-failed της 1ης
        assert len(iterations) == 2
        assert iterations[1][0] is False
        assert iterations[1][1] > 0
        assert freshness.build_count(zip_res, freshness.RETRIES_FIELD) == 1

    def test_plain_change_during_retry_job_checks_for_changes(
            self, http, enqueue_calls):
        def change_outside_fingerprint(package_id):
            # Αλλάζει το datapackage.json, όχι το fingerprint
            helpers.call_action(
                'package_patch', id=package_id,
                extras=[{'key': 'od_note', 'value': 'x'}])

        iterations, zip_res = _run_retry_job_with_change_in_first_iteration(
            http, enqueue_calls, change_outside_fingerprint)

        # Η 2η επανάληψη είναι κανονική: με έλεγχο αλλαγών και χωρίς να μετρά
        # ως νέα επανάληψη του --retry-failed
        assert len(iterations) == 2
        assert iterations[0][0] is False
        assert iterations[1][0] is True
        assert freshness.build_count(zip_res, freshness.RETRIES_FIELD) == 1
