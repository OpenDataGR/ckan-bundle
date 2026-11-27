# -*- coding: utf-8 -*-
'''
Tests για τους κανόνες του OD-857 που δεν χρειάζονται βάση: επιλεξιμότητα
datasets και πόρων, ονόματα αρχείων μέσα στο ZIP, fingerprint και κατάσταση
του κουμπιού «Λήψη όλων».
'''
from unittest import mock

import pytest

from ckanext.downloadall import config, eligibility, filenames, freshness

HVD = '["http://data.europa.eu/bna/c_ac64a52d"]'
EXCLUDE_API = {'ckanext.downloadall.exclude_resource_formats': 'API'}


def _dataset(**kwargs):
    dataset = {'id': 'd1', 'name': 'roads', 'type': 'dataset', 'title': 'Roads',
               'metadata_modified': '2026-11-01T10:00:00',
               'resources': [
                   {'id': 'r1', 'name': 'Roads CSV', 'url': 'https://example.test/roads.csv',
                    'format': 'CSV'},
               ]}
    dataset.update(kwargs)
    return dataset


class TestConfigLists(object):

    @pytest.mark.parametrize('value,expected', [
        ('["capabilities document", "WMS"]', ['capabilities document', 'WMS']),
        ('capabilities document, WMS', ['capabilities document', 'WMS']),
        ('capabilities document\nWMS', ['capabilities document', 'WMS']),
        ('', []),
        (['API'], ['API']),
    ])
    def test_as_list(self, value, expected):
        assert config.as_list(value) == expected

    @pytest.mark.parametrize('value,expected', [
        ('roads, 2026.zip', ['roads, 2026.zip']),
        ('["a.zip", "b.zip"]', ['a.zip', 'b.zip']),
        (['a.zip', '', None], ['a.zip']),
        (None, []),
    ])
    def test_as_list_without_splitting(self, value, expected):
        assert config.as_list(value, split=False) == expected


class TestDatasetEligibility(object):

    def test_default_every_dataset_gets_a_zip(self):
        assert eligibility.dataset_exclusion_reason(_dataset()) is None

    def test_data_service_and_showcase_never(self):
        assert eligibility.dataset_exclusion_reason(_dataset(type='data-service'))
        assert eligibility.dataset_exclusion_reason(_dataset(type='showcase'))

    @pytest.mark.ckan_config('ckanext.downloadall.hvd_only', 'true')
    @pytest.mark.parametrize('value,expected', [
        (['http://data.europa.eu/bna/c_ac64a52d'], True),
        (HVD, True),
        ('http://data.europa.eu/bna/c_ac64a52d', True),
        ('[]', False),
        ([], False),
        (None, False),
        ('', False),
    ])
    def test_hvd_only(self, value, expected):
        dataset = _dataset(hvd_category=value)
        assert (eligibility.dataset_exclusion_reason(dataset) is None) is expected

    @pytest.mark.ckan_config('ckanext.downloadall.hvd_only', 'true')
    def test_hvd_category_in_core_extras(self):
        dataset = _dataset(extras=[{'key': 'hvd_category', 'value': HVD}])
        assert eligibility.dataset_exclusion_reason(dataset) is None


class TestResourceExclusion(object):

    def test_no_format_excluded_by_default(self):
        '''Όπως πριν το OD-857.'''
        assert eligibility.resource_exclusion_reason({'format': 'API'}) is None

    def test_excluded_format_any_case(self):
        with mock.patch.dict('ckan.plugins.toolkit.config', EXCLUDE_API):
            assert eligibility.resource_exclusion_reason({'format': 'Api'}) == eligibility.REASON_FORMAT
            assert eligibility.resource_exclusion_reason({'format': 'CSV'}) is None

    # #8: μια τιμή που δεν είναι boolean δεν ρίχνει τη σελίδα (ValueError)
    @pytest.mark.parametrize('marker,excluded', [(True, True), ('true', True), ('false', False),
                                                 (None, False), (u'ναι', False)])
    def test_explicit_marker(self, marker, excluded):
        reason = eligibility.resource_exclusion_reason({'format': 'XML', 'downloadall_exclude': marker})
        assert (reason == eligibility.REASON_MARKER) is excluded

    @pytest.mark.ckan_config('ckanext.downloadall.exclude_resource_name_patterns',
                             '["capabilities document"]')
    @pytest.mark.parametrize('resource', [
        {'name': 'WMS Capabilities Document - roads'},
        {'name': 'roads', 'name_translated': {'el': 'x', 'en': 'WMS capabilities document - roads'}},
        {'name': 'roads', 'name_translated': '{"en": "WFS CAPABILITIES DOCUMENT - roads"}'},
    ])
    def test_name_patterns_case_insensitive_and_translated(self, resource):
        assert eligibility.resource_exclusion_reason(resource) == eligibility.REASON_NAME

    @pytest.mark.ckan_config('ckanext.downloadall.exclude_resource_name_patterns',
                             '["capabilities document"]')
    def test_other_names_are_included(self):
        assert eligibility.resource_exclusion_reason({'name': 'Roads 2026', 'format': 'CSV'}) is None


class TestFilenames(object):

    def test_url_without_filename_and_without_format(self):
        '''Πριν: KeyError: 'format' και αποτυχία όλου του job.'''
        name = filenames.choose_filename({'url': 'https://example.test/api/', 'name': ''}, 0)
        assert name == 'resource-1'

    def test_url_basename_is_decoded_and_query_dropped(self):
        resource = {'url': 'https://example.test/data/%CE%B4%CE%B5%CE%B4%CE%BF%CE%BC%CE%AD%CE%BD%CE%B1.csv?sig=SECRET#x'}
        assert filenames.choose_filename(resource, 0) == u'δεδομένα.csv'

    def test_extension_from_format(self):
        resource = {'url': 'https://example.test/download/1234', 'format': 'JSON'}
        assert filenames.choose_filename(resource, 0) == '1234.json'

    def test_extension_from_content_type(self):
        resource = {'url': 'https://example.test/export?id=7', 'name': 'Export'}
        assert filenames.choose_filename(resource, 0, content_type='text/csv; charset=utf-8') == 'export.csv'

    def test_content_disposition_wins(self):
        resource = {'url': 'https://example.test/download?id=1', 'format': 'CSV'}
        assert filenames.choose_filename(
            resource, 0, content_disposition='attachment; filename="stations.csv"') == 'stations.csv'
        assert filenames.choose_filename(
            resource, 0,
            content_disposition="attachment; filename*=UTF-8''%CF%83%CF%84%CE%B1%CE%B8%CE%BC%CE%BF%CE%AF.xlsx") \
            == u'σταθμοί.xlsx'

    def test_version_like_suffix_gets_real_extension(self):
        resource = {'url': 'https://example.test/files/report-v1.2', 'format': 'PDF'}
        assert filenames.choose_filename(resource, 0) == 'report-v1.2.pdf'

    def test_unsafe_characters(self):
        assert filenames.sanitize('a/b\\c:d*e?.csv') == 'a_b_c_d_e_.csv'

    def test_collisions_are_numbered(self):
        used = set()
        names = [filenames.make_unique(n, used) for n in ('data.csv', 'Data.csv', 'data.csv', 'notes')]
        assert names == ['data.csv', 'Data (2).csv', 'data (3).csv', 'notes']


class TestFingerprint(object):

    def test_stable_against_unrelated_fields(self):
        base = _dataset()
        changed = _dataset(metadata_modified='2026-11-17T00:00:00',
                           qa={'openness_score': 3}, archiver={'status': 'x'})
        changed['resources'][0]['qa'] = {'openness_score': 3}
        changed['resources'][0]['metadata_modified'] = '2026-11-17T00:00:00'
        changed['resources'].append({'id': 'zip', 'url': 'x.zip', 'downloadall_metadata_modified': 'y'})
        assert freshness.compute_fingerprint(base) == freshness.compute_fingerprint(changed)

    def test_stable_when_extras_are_rearranged(self):
        '''Το scheming ξανατακτοποιεί τα extras στο package_update της πρώτης
        αποθήκευσης του ZIP· δεν πρέπει να κάνει το νέο ZIP «μη ενημερωμένο».'''
        before = _dataset(extras=[{'key': 'identifier', 'value': 'x'}, {'key': 'issued', 'value': '2024'}])
        after = _dataset(extras=[{'key': 'harvest_object_id', 'value': 'y'}])
        assert freshness.compute_fingerprint(before) == freshness.compute_fingerprint(after)

    def test_stable_when_the_licence_title_is_translated(self):
        '''Τοπική δοκιμή 19/11: το παλιό index του Solr έχει τον αγγλικό τίτλο
        της άδειας, το dataset από τη βάση τον ελληνικό· μετά την πρώτη
        αποθήκευση του ZIP το κουμπί έδειχνε «stale».'''
        before = _dataset(license_id='cc-by-sa', license_title='Creative Commons Attribution Share-Alike',
                          license_url='http://www.opendefinition.org/licenses/cc-by-sa')
        after = _dataset(license_id='cc-by-sa', license_title=u'Creative Commons Αναφορά - Παρόμοια διανομή',
                         license_url='https://creativecommons.org/licenses/by-sa/4.0/')
        assert freshness.compute_fingerprint(before) == freshness.compute_fingerprint(after)

    def test_changes_with_the_licence(self):
        assert freshness.compute_fingerprint(_dataset(license_id='cc-by-sa')) != \
            freshness.compute_fingerprint(_dataset(license_id='cc-by'))

    def test_changes_with_resource_url_or_format(self):
        base = freshness.compute_fingerprint(_dataset())
        new_url = _dataset()
        new_url['resources'][0]['url'] = 'https://example.test/roads-2.csv'
        new_format = _dataset()
        new_format['resources'][0]['format'] = 'XLSX'
        assert freshness.compute_fingerprint(new_url) != base
        assert freshness.compute_fingerprint(new_format) != base

    def test_excluded_resource_does_not_count(self):
        base = _dataset()
        with_api = _dataset()
        with_api['resources'].append({'id': 'api', 'url': 'https://example.test/api', 'format': 'API'})
        with mock.patch.dict('ckan.plugins.toolkit.config', EXCLUDE_API):
            assert freshness.compute_fingerprint(base) == freshness.compute_fingerprint(with_api)

    def test_upload_url_does_not_depend_on_site_url(self):
        a = _dataset()
        a['resources'][0].update(url_type='upload', url='http://internal:5000/dataset/d1/resource/r1/download/roads.csv')
        b = _dataset()
        b['resources'][0].update(url_type='upload', url='https://data.example/dataset/d1/resource/r1/download/roads.csv')
        assert freshness.compute_fingerprint(a) == freshness.compute_fingerprint(b)


class TestZipState(object):

    def _with_zip(self, dataset, **zip_fields):
        zip_res = dict({'id': 'zip', 'url': 'roads.zip', 'downloadall_metadata_modified': 'x'}, **zip_fields)
        dataset['resources'].append(zip_res)
        return dataset

    def test_ready_when_fingerprint_matches(self):
        dataset = _dataset()
        fingerprint = freshness.compute_fingerprint(dataset)
        assert freshness.zip_state(self._with_zip(dataset, downloadall_fingerprint=fingerprint)) == 'ready'

    def test_stale_after_a_change(self):
        dataset = _dataset()
        fingerprint = freshness.compute_fingerprint(dataset)
        dataset['resources'][0]['url'] = 'https://example.test/new.csv'
        assert freshness.zip_state(self._with_zip(dataset, downloadall_fingerprint=fingerprint)) == 'stale'

    def test_legacy_zip_without_fingerprint_is_ready(self):
        assert freshness.zip_state(self._with_zip(_dataset())) == 'ready'

    def test_none_without_zip(self):
        assert freshness.zip_state(_dataset()) == 'none'

    def test_hidden_without_resources_or_not_eligible(self):
        assert freshness.zip_state(_dataset(resources=[])) == 'hidden'
        assert freshness.zip_state(_dataset(type='data-service')) == 'hidden'

    def test_hidden_when_every_resource_is_excluded(self):
        dataset = _dataset()
        dataset['resources'][0]['format'] = 'API'
        with mock.patch.dict('ckan.plugins.toolkit.config', EXCLUDE_API):
            assert freshness.zip_state(self._with_zip(dataset)) == 'hidden'

    @pytest.mark.parametrize('state', ['draft', 'deleted'])
    def test_hidden_for_inactive_dataset(self, state):
        assert freshness.zip_state(_dataset(state=state)) == 'hidden'

    def test_previous_zip_ready_after_a_failed_attempt(self):
        dataset = _dataset()
        old = freshness.compute_fingerprint(dataset)
        dataset['resources'][0]['url'] = 'https://example.test/new.csv'
        current = freshness.compute_fingerprint(dataset)
        dataset = self._with_zip(dataset, downloadall_fingerprint=old,
                                 downloadall_attempted_fingerprint=current)
        assert freshness.zip_state(dataset) == 'ready'


class TestNeedsRetry(object):
    '''update-all-zips --retry-failed'''

    def _with_zip(self, dataset, **zip_fields):
        fields = dict({'id': 'zip', 'url': 'roads.zip', 'downloadall_metadata_modified': 'x',
                       'downloadall_fingerprint': freshness.compute_fingerprint(dataset)},
                      **zip_fields)
        dataset['resources'].append(fields)
        return dataset

    def test_current_zip_without_failures_is_not_retried(self):
        assert not freshness.needs_retry(self._with_zip(_dataset()))

    def test_failed_resources_are_retried(self):
        assert freshness.needs_retry(self._with_zip(_dataset(), downloadall_failed='2'))

    def test_only_temporary_failures_are_retried(self):
        '''#13: π.χ. 404 δεν ξαναδοκιμάζεται κάθε βράδυ, timeout ναι.'''
        assert not freshness.needs_retry(self._with_zip(
            _dataset(), downloadall_failed='2', downloadall_failed_transient='0'))
        assert freshness.needs_retry(self._with_zip(
            _dataset(), downloadall_failed='2', downloadall_failed_transient='1'))

    def test_temporary_failures_stop_at_the_limit(self):
        def zip_with(retries):
            return self._with_zip(_dataset(), downloadall_failed='1',
                                  downloadall_failed_transient='1',
                                  downloadall_retries=retries)
        assert freshness.needs_retry(zip_with('2'))
        assert not freshness.needs_retry(zip_with('3'))

    def test_failed_build_stops_at_the_limit(self):
        '''Η πρώτη αποτυχία και μετά 3 νέες προσπάθειες.'''
        def zip_with(attempts):
            dataset = _dataset()
            return self._with_zip(
                dataset, downloadall_fingerprint='old',
                downloadall_attempted_fingerprint=freshness.compute_fingerprint(dataset),
                downloadall_attempts=attempts)
        assert freshness.needs_retry(zip_with('3'))
        assert not freshness.needs_retry(zip_with('4'))

    def test_default_limit(self):
        from ckanext.downloadall import config as dl_config
        assert dl_config.retry_failed_limit() == 3

    @pytest.mark.ckan_config('ckanext.downloadall.retry_failed_limit', '0')
    def test_zero_limit_means_no_limit(self):
        assert freshness.needs_retry(self._with_zip(
            _dataset(), downloadall_failed='1', downloadall_failed_transient='1',
            downloadall_retries='99'))

    def test_missing_or_stale_zip_is_retried(self):
        assert freshness.needs_retry(_dataset())
        assert freshness.needs_retry(self._with_zip(_dataset(), downloadall_fingerprint='old'))

    def test_not_eligible_is_not_retried(self):
        assert not freshness.needs_retry(_dataset(type='data-service'))
        assert not freshness.needs_retry(_dataset(resources=[]))

    @pytest.mark.ckan_config('ckanext.downloadall.hvd_only', 'true')
    def test_hidden_for_non_hvd_with_hvd_only(self):
        assert freshness.zip_state(self._with_zip(_dataset())) == 'hidden'
        assert freshness.zip_state(_dataset(hvd_category=HVD)) == 'none'
