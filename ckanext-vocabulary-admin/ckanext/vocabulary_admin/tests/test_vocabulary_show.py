# -*- coding: utf-8 -*-
'''
Tests για το vocabularyadmin_vocabulary_show (OD-856): τα metadata των tags
φορτώνονται με ένα query, με το ίδιο αποτέλεσμα όπως πριν.
'''
from unittest import mock

import pytest

from ckan import model
from ckan.tests import helpers

from ckanext.vocabulary_admin.model import tag_metadata as tag_metadata_model
from ckanext.vocabulary_admin.model.tag_metadata import VocabularyTagMetadata


@pytest.fixture
def metadata_table(clean_db):
    tag_metadata_model.vocabulary_tag_metadata_table.create(
        model.meta.engine, checkfirst=True)


@pytest.mark.usefixtures('with_plugins', 'metadata_table')
@pytest.mark.ckan_config('ckan.plugins', 'vocabulary_admin')
class TestVocabularyShow(object):

    def _vocabulary(self):
        vocab = helpers.call_action('vocabulary_create', name='od856_vocab', tags=[
            {'name': 'zeta'}, {'name': 'alpha'}, {'name': 'beta'}, {'name': 'hidden'}])
        ids = {tag['name']: tag['id'] for tag in vocab['tags']}
        VocabularyTagMetadata.create(ids['zeta'], label_el=u'Ζήτα', order_index=1)
        VocabularyTagMetadata.create(ids['beta'], label_en='Beta', order_index=2)
        VocabularyTagMetadata.create(ids['hidden'], is_active=False)
        return ids

    def test_active_tags_enriched_and_ordered(self):
        self._vocabulary()

        result = helpers.call_action('vocabularyadmin_vocabulary_show', id='od856_vocab')

        # Πρώτα όσα έχουν order_index, μετά τα υπόλοιπα αλφαβητικά· το
        # ανενεργό εξαιρείται, το tag χωρίς metadata θεωρείται ενεργό.
        assert [tag['name'] for tag in result['tags']] == ['zeta', 'beta', 'alpha']
        assert result['tags'][0]['label_el'] == u'Ζήτα'
        assert result['tags'][1]['label_en'] == 'Beta'
        assert 'is_active' not in result['tags'][2]

    def test_metadata_loaded_with_one_query(self):
        self._vocabulary()
        with mock.patch.object(tag_metadata_model, 'get_tag_metadata',
                               side_effect=AssertionError('one query per tag')):
            result = helpers.call_action('vocabularyadmin_vocabulary_show',
                                         id='od856_vocab')
        assert len(result['tags']) == 3

    def test_get_tags_metadata(self):
        ids = self._vocabulary()
        metadata = tag_metadata_model.get_tags_metadata(list(ids.values()) + [None])
        assert set(metadata) == {ids['zeta'], ids['beta'], ids['hidden']}
        assert metadata[ids['hidden']]['is_active'] is False
        assert metadata[ids['zeta']] == tag_metadata_model.get_tag_metadata(ids['zeta'])
        assert tag_metadata_model.get_tags_metadata([]) == {}
