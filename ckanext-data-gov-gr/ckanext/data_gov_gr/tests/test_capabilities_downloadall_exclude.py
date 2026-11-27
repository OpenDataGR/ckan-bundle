# -*- coding: utf-8 -*-
'''
Οι πόροι «capabilities document» των harvesters έχουν downloadall_exclude,
ώστε να μη μπαίνουν στο ZIP «Λήψη όλων» (OD-857).
'''
from unittest import mock

from ckanext.data_gov_gr.harvesters import wms_harvester
from ckanext.data_gov_gr.logic import harvest_mapping


def test_configured_capabilities_resource_is_excluded_from_downloadall():
    resource = harvest_mapping._configured_capabilities_resource(
        url='https://example.test/wms?service=WMS&request=GetCapabilities',
        layer_name='roads', service_name='WMS', protocol='OGC:WMS')
    assert resource['downloadall_exclude'] is True
    assert resource['format'] == 'XML'


def test_wms_harvester_capabilities_resources_are_excluded_from_downloadall():
    harvester = wms_harvester.WmsCapabilitiesHarvester()
    config = {wms_harvester.WFS_CAPABILITIES_URL_CONFIG_KEY:
              'https://example.test/wfs?service=WFS&request=GetCapabilities'}
    payload = {'source_url': 'https://example.test/wms?service=WMS&request=GetCapabilities'}
    with mock.patch.object(harvester, '_wms_getmap_resources', return_value=[]), \
            mock.patch.object(harvester, '_wfs_download_resources', return_value=[]), \
            mock.patch.object(harvester, '_skip_wfs_capabilities_resource', return_value=False):
        resources = harvester._resources({'name': 'roads'}, payload, config)

    capabilities = [r for r in resources if r.get('resource_locator_protocol') in ('OGC:WMS', 'OGC:WFS')
                    and r.get('format') == 'XML']
    assert len(capabilities) == 2
    assert all(r['downloadall_exclude'] is True for r in capabilities)
