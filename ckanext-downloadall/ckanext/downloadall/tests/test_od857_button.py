# -*- coding: utf-8 -*-
'''
Tests για το κουμπί «Λήψη όλων» στη σελίδα του dataset (OD-857): ενεργό όταν
το ZIP είναι ενημερωμένο, απενεργοποιημένο όσο ενημερώνεται, κρυφό για
datasets χωρίς δικαίωμα σε ZIP.
'''
from unittest import mock

import pytest
import responses

from ckan.plugins import toolkit
from ckan.tests import factories, helpers

from ckanext.downloadall import freshness, tasks

CSV = b'a,b\n1,2\n'


def _page(app, dataset):
    return app.get(toolkit.url_for('dataset.read', id=dataset['name'])).body


def _zip_link(dataset):
    zip_res = freshness.zip_resource(helpers.call_action('package_show', id=dataset['id']))
    return 'href="%s"' % zip_res['url']


@pytest.mark.usefixtures('with_plugins', 'clean_db', 'enqueue_calls', 'clean_dedup_keys')
@pytest.mark.ckan_config('ckan.plugins', 'downloadall')
class TestButton(object):

    def _dataset_with_zip(self, http):
        http.add(responses.GET, 'https://example.test/a.csv', body=CSV)
        http.add(responses.GET, 'https://example.test/gone.csv', status=404)
        dataset = factories.Dataset(resources=[
            {'url': 'https://example.test/a.csv', 'format': 'CSV'},
            {'url': 'https://example.test/gone.csv', 'format': 'CSV'}])
        tasks.update_zip(dataset['id'])
        return dataset

    def test_ready_button_mentions_missing_resources(self, app, http):
        dataset = self._dataset_with_zip(http)
        body = _page(app, dataset)
        assert _zip_link(dataset) in body
        assert 'does not include 1 of the resources' in body

    def test_stale_button_is_disabled(self, app, http):
        dataset = self._dataset_with_zip(http)
        resource_id = helpers.call_action('package_show', id=dataset['id'])['resources'][0]['id']
        helpers.call_action('resource_patch', id=resource_id, url='https://example.test/b.csv')
        body = _page(app, dataset)
        assert 'The download is being updated' in body
        assert _zip_link(dataset) not in body

    def test_hidden_for_non_hvd_with_hvd_only(self, app, http):
        dataset = self._dataset_with_zip(http)
        with mock.patch.dict('ckan.plugins.toolkit.config', {'ckanext.downloadall.hvd_only': 'true'}):
            body = _page(app, dataset)
        assert 'Download all' not in body
        assert _zip_link(dataset) not in body
