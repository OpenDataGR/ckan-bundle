import json
from types import SimpleNamespace

import pytest

from ckanext.data_gov_gr import helpers


_DASHBOARD_ACTIVITY_COUNT_CONFIG = (
    "ckanext.data_gov_gr.header.dashboard_activity_count.enabled"
)
_HARVEST_FREQUENCY_EXCLUDE_CONFIG = (
    "ckanext.data_gov_gr.harvest.frequency_exclude"
)


def _spatial_extent(pkg):
    value = helpers.data_gov_gr_dataset_spatial_extent(pkg)
    return json.loads(value) if value else None


@pytest.mark.parametrize("config_value", [None, "false"])
def test_new_activities_skips_original_helper_when_disabled(
    monkeypatch, config_value
):
    if config_value is None:
        monkeypatch.delitem(
            helpers.toolkit.config,
            _DASHBOARD_ACTIVITY_COUNT_CONFIG,
            raising=False,
        )
    else:
        monkeypatch.setitem(
            helpers.toolkit.config,
            _DASHBOARD_ACTIVITY_COUNT_CONFIG,
            config_value,
        )

    calls = []

    def next_helper():
        calls.append(True)
        return 7

    assert helpers.data_gov_gr_new_activities(next_helper) == 0
    assert calls == []


def test_new_activities_delegates_to_original_helper_when_enabled(monkeypatch):
    monkeypatch.setitem(
        helpers.toolkit.config,
        _DASHBOARD_ACTIVITY_COUNT_CONFIG,
        "true",
    )
    calls = []

    def next_helper():
        calls.append(True)
        return 7

    assert helpers.data_gov_gr_new_activities(next_helper) == 7
    assert calls == [True]


def test_new_activities_helper_is_registered_as_chained_helper(monkeypatch):
    monkeypatch.setattr(
        helpers.plugins,
        "plugin_loaded",
        lambda plugin_name: plugin_name == "activity",
    )
    registered_helpers = helpers.get_helpers()

    assert (
        registered_helpers["new_activities"]
        is helpers.data_gov_gr_new_activities
    )
    assert helpers.data_gov_gr_new_activities.chained_helper is True


def test_new_activities_helper_is_not_registered_without_activity(monkeypatch):
    monkeypatch.setattr(
        helpers.plugins,
        "plugin_loaded",
        lambda plugin_name: False,
    )

    assert "new_activities" not in helpers.get_helpers()


@pytest.mark.ckan_config("ckan.plugins", "activity data_gov_gr")
@pytest.mark.usefixtures("with_plugins")
def test_new_activities_wraps_activity_helper_with_staging_plugin_order(
    monkeypatch,
):
    from ckan.lib.helpers import helper_functions

    monkeypatch.setitem(
        helpers.toolkit.config,
        _DASHBOARD_ACTIVITY_COUNT_CONFIG,
        "false",
    )

    assert helper_functions["new_activities"]() == 0


def test_harvest_frequencies_returns_upstream_options_without_exclusions(
    monkeypatch,
):
    monkeypatch.delitem(
        helpers.toolkit.config,
        _HARVEST_FREQUENCY_EXCLUDE_CONFIG,
        raising=False,
    )
    upstream_options = [
        {"text": "Manual", "value": "MANUAL"},
        {"text": "Always", "value": "ALWAYS"},
    ]
    calls = []

    def next_helper():
        calls.append(True)
        return upstream_options

    assert helpers.harvest_frequencies(next_helper) == upstream_options
    assert calls == [True]


def test_harvest_frequencies_filters_configured_values(monkeypatch):
    monkeypatch.setitem(
        helpers.toolkit.config,
        _HARVEST_FREQUENCY_EXCLUDE_CONFIG,
        " always, weekly ",
    )
    upstream_options = [
        {"text": "Manual", "value": "MANUAL"},
        {"text": "Weekly", "value": "WEEKLY"},
        {"text": "Always", "value": "ALWAYS"},
    ]

    assert helpers.harvest_frequencies(lambda: upstream_options) == [
        {"text": "Manual", "value": "MANUAL"},
    ]


def test_harvest_frequencies_helper_is_registered_as_chained_helper(monkeypatch):
    monkeypatch.setattr(
        helpers.plugins,
        "plugin_loaded",
        lambda plugin_name: plugin_name == "harvest",
    )
    registered_helpers = helpers.get_helpers()

    assert (
        registered_helpers["harvest_frequencies"]
        is helpers.harvest_frequencies
    )
    assert helpers.harvest_frequencies.chained_helper is True


def test_harvest_frequencies_helper_is_not_registered_without_harvest(
    monkeypatch,
):
    monkeypatch.setattr(
        helpers.plugins,
        "plugin_loaded",
        lambda plugin_name: False,
    )

    assert "harvest_frequencies" not in helpers.get_helpers()


@pytest.mark.ckan_config("ckan.plugins", "harvest data_gov_gr")
@pytest.mark.usefixtures("with_plugins")
def test_harvest_frequencies_wraps_harvest_helper_with_staging_plugin_order(
    monkeypatch,
):
    from ckan.lib.helpers import helper_functions

    monkeypatch.setitem(
        helpers.toolkit.config,
        _HARVEST_FREQUENCY_EXCLUDE_CONFIG,
        "ALWAYS",
    )

    values = [
        option["value"]
        for option in helper_functions["harvest_frequencies"]()
    ]

    assert "ALWAYS" not in values
    assert values == ["MANUAL", "MONTHLY", "WEEKLY", "BIWEEKLY", "DAILY"]


def test_map_search_carto_api_key_defaults_to_empty(monkeypatch):
    config_key = "ckanext.data_gov_gr.map_search.carto_api_key"
    monkeypatch.delitem(helpers.toolkit.config, config_key, raising=False)

    assert helpers.map_search_carto_api_key() == ""


def test_map_search_carto_api_key_is_trimmed(monkeypatch):
    config_key = "ckanext.data_gov_gr.map_search.carto_api_key"
    monkeypatch.setitem(helpers.toolkit.config, config_key, "  test-key  ")

    assert helpers.map_search_carto_api_key() == "test-key"


def test_map_search_carto_api_key_helper_is_registered():
    registered_helpers = helpers.get_helpers()

    assert (
        registered_helpers["data_gov_gr_map_search_carto_api_key"]
        is helpers.map_search_carto_api_key
    )


def test_map_search_vector_style_url_defaults_to_carto_style(monkeypatch):
    config_key = "ckanext.data_gov_gr.map_search.vector_style_url"
    monkeypatch.delitem(helpers.toolkit.config, config_key, raising=False)

    assert helpers.map_search_vector_style_url() == (
        "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
    )


def test_map_search_vector_settings_are_trimmed(monkeypatch):
    monkeypatch.setitem(
        helpers.toolkit.config,
        "ckanext.data_gov_gr.map_search.vector_style_url",
        "  /custom/vector-style.json  ",
    )
    monkeypatch.setitem(
        helpers.toolkit.config,
        "ckanext.data_gov_gr.map_search.vector_fallback_basemap",
        "  eox_osm  ",
    )

    assert helpers.map_search_vector_style_url() == "/custom/vector-style.json"
    assert helpers.map_search_vector_fallback_basemap() == "eox_osm"


def test_map_search_vector_helpers_are_registered():
    registered_helpers = helpers.get_helpers()

    assert (
        registered_helpers["data_gov_gr_map_search_vector_style_url"]
        is helpers.map_search_vector_style_url
    )
    assert (
        registered_helpers["data_gov_gr_map_search_vector_fallback_basemap"]
        is helpers.map_search_vector_fallback_basemap
    )


def test_dataset_spatial_extent_uses_irregular_geom_polygon():
    polygon = {
        "type": "Polygon",
        "coordinates": [[
            [23.1, 38.0],
            [23.4, 38.2],
            [23.8, 37.9],
            [23.5, 37.6],
            [23.1, 38.0],
        ]],
    }

    extent = _spatial_extent({
        "spatial_coverage": [{
            "geom": json.dumps(polygon),
        }],
    })

    assert extent["type"] == "Feature"
    assert extent["geometry"] == polygon


def test_dataset_spatial_extent_prefers_bbox_area_over_geom_point():
    point = {"type": "Point", "coordinates": [23.7, 38.0]}
    bbox = {
        "type": "Polygon",
        "coordinates": [[
            [23.0, 37.5],
            [24.0, 37.5],
            [24.0, 38.5],
            [23.0, 38.5],
            [23.0, 37.5],
        ]],
    }

    extent = _spatial_extent({
        "spatial_coverage": [{
            "geom": point,
            "bbox": json.dumps(bbox),
            "centroid": point,
        }],
    })

    assert extent["geometry"] == bbox


def test_dataset_spatial_extent_combines_multiple_coverages():
    first = {"type": "Point", "coordinates": [23.7, 38.0]}
    second = {
        "type": "Polygon",
        "coordinates": [[
            [20.0, 35.0],
            [21.0, 35.0],
            [21.0, 36.0],
            [20.0, 36.0],
            [20.0, 35.0],
        ]],
    }

    extent = _spatial_extent({
        "spatial_coverage": [
            {"centroid": first},
            {"geom": second},
        ],
    })

    assert extent["type"] == "FeatureCollection"
    assert [feature["geometry"] for feature in extent["features"]] == [first, second]


def test_dataset_spatial_extent_ignores_invalid_values():
    valid = {"type": "Point", "coordinates": [23.7, 38.0]}

    extent = _spatial_extent({
        "spatial_coverage": [
            {"geom": '{"type": "Polygon"}'},
            {"bbox": "not-json"},
            {"centroid": valid},
        ],
    })

    assert extent["geometry"] == valid


def test_dataset_spatial_extent_returns_empty_for_unusable_coverage():
    assert helpers.data_gov_gr_dataset_spatial_extent({
        "spatial_coverage": [{"geom": "not-json"}],
    }) == ""


def test_dataset_spatial_extent_parses_wkt_polygon_in_text():
    extent = _spatial_extent({
        "spatial_coverage": [{
            "text": "POLYGON ((23.466796875 34.627482633877, "
                    "23.466796875 35.731947151481, "
                    "26.4990234375 35.731947151481, "
                    "26.4990234375 34.627482633877, "
                    "23.466796875 34.627482633877))",
        }],
    })

    assert extent["type"] == "Feature"
    assert extent["geometry"]["type"] == "Polygon"
    coords = extent["geometry"]["coordinates"][0]
    assert len(coords) == 5
    assert coords[0][0] == 23.466796875


def test_dataset_spatial_extent_parses_unclosed_wkt_polygon():
    extent = _spatial_extent({
        "spatial_coverage": [{
            "text": "POLYGON ((23.466796875 34.627482633877, "
                    "23.466796875 35.731947151481, "
                    "26.4990234375 35.731947151481, "
                    "26.4990234375 34.627482633877))",
        }],
    })

    assert extent["type"] == "Feature"
    assert extent["geometry"]["type"] == "Polygon"
    coords = extent["geometry"]["coordinates"][0]
    assert coords[0] == coords[-1]


def test_dataset_spatial_extent_parses_wkt_polygon_in_geom():
    extent = _spatial_extent({
        "spatial_coverage": [{
            "geom": "POLYGON ((23.5 34.7, 23.5 35.7, 26.5 35.7, 26.5 34.7, 23.5 34.7))",
        }],
    })

    assert extent["type"] == "Feature"
    assert extent["geometry"]["type"] == "Polygon"


def test_dataset_spatial_extent_wkt_geom_wins_over_bbox():
    extent = _spatial_extent({
        "spatial_coverage": [{
            "geom": "POLYGON ((20.0 35.0, 20.0 36.0, 21.0 36.0, 21.0 35.0, 20.0 35.0))",
            "bbox": json.dumps({
                "type": "Polygon",
                "coordinates": [[
                    [23.0, 37.5], [24.0, 37.5],
                    [24.0, 38.5], [23.0, 38.5],
                    [23.0, 37.5],
                ]],
            }),
        }],
    })

    assert extent["geometry"]["coordinates"][0][0] == [20.0, 35.0]


def test_dataset_spatial_extent_parses_wkt_point_in_text():
    extent = _spatial_extent({
        "spatial_coverage": [{
            "text": "POINT (23.7 38.0)",
        }],
    })

    assert extent["type"] == "Feature"
    assert extent["geometry"]["type"] == "Point"


def test_dataset_spatial_extent_geojson_wins_over_wkt_text():
    bbox = {
        "type": "Polygon",
        "coordinates": [[
            [23.0, 37.5], [24.0, 37.5],
            [24.0, 38.5], [23.0, 38.5],
            [23.0, 37.5],
        ]],
    }

    extent = _spatial_extent({
        "spatial_coverage": [{
            "bbox": json.dumps(bbox),
            "text": "POINT (23.7 38.0)",
        }],
    })

    assert extent["geometry"] == bbox


def test_dataset_spatial_extent_ignores_invalid_wkt():
    assert helpers.data_gov_gr_dataset_spatial_extent({
        "spatial_coverage": [{"text": "POLYGON ((not valid))"}],
    }) == ""


def test_dataset_spatial_extent_ignores_non_wkt_text():
    assert helpers.data_gov_gr_dataset_spatial_extent({
        "spatial_coverage": [{"text": "Περιφέρεια Αττικής"}],
    }) == ""


def test_dataset_spatial_coverage_map_position_uses_safe_default(monkeypatch):
    config_key = "ckanext.data_gov_gr.dataset.spatial_coverage.map.position"

    monkeypatch.setitem(helpers.toolkit.config, config_key, "after_additional_info")
    assert helpers.data_gov_gr_dataset_spatial_coverage_map_position() == "after_additional_info"

    monkeypatch.setitem(helpers.toolkit.config, config_key, ["after_tags", "after_additional_info"])
    assert helpers.data_gov_gr_dataset_spatial_coverage_map_position() == "after_additional_info"

    monkeypatch.setitem(helpers.toolkit.config, config_key, "invalid")
    assert helpers.data_gov_gr_dataset_spatial_coverage_map_position() == "after_additional_info"


def _clear_mqa_visibility_config(monkeypatch):
    monkeypatch.delitem(helpers.toolkit.config, helpers.MQA_VISIBILITY_CONFIG, raising=False)
    monkeypatch.delitem(
        helpers.toolkit.config,
        helpers.MQA_VISIBILITY_ADMIN_CONFIG_ENABLED,
        raising=False,
    )
    monkeypatch.delitem(
        helpers.toolkit.config,
        helpers.MQA_VISIBILITY_ALLOWED_VALUES_CONFIG,
        raising=False,
    )
    monkeypatch.delitem(helpers.toolkit.config, helpers.MQA_HIDE_TAB_CONFIG, raising=False)


def _user(name="user", user_id="user-id", authenticated=True, sysadmin=False):
    return SimpleNamespace(
        id=user_id,
        name=name,
        is_authenticated=authenticated,
        sysadmin=sysadmin,
    )


def test_mqa_visibility_defaults_to_hidden(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)

    assert helpers.get_mqa_visibility() == helpers.MQA_VISIBILITY_HIDDEN
    assert helpers.should_hide_mqa_tab() is True


def test_mqa_visibility_uses_legacy_hide_tab_when_new_option_missing(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)

    monkeypatch.setitem(helpers.toolkit.config, helpers.MQA_HIDE_TAB_CONFIG, "no")
    assert helpers.get_mqa_visibility() == helpers.MQA_VISIBILITY_PUBLIC

    monkeypatch.setitem(helpers.toolkit.config, helpers.MQA_HIDE_TAB_CONFIG, "yes")
    assert helpers.get_mqa_visibility() == helpers.MQA_VISIBILITY_HIDDEN


def test_mqa_visibility_prefers_new_option(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)
    monkeypatch.setitem(helpers.toolkit.config, helpers.MQA_HIDE_TAB_CONFIG, "yes")
    monkeypatch.setitem(
        helpers.toolkit.config,
        helpers.MQA_VISIBILITY_CONFIG,
        helpers.MQA_VISIBILITY_ORGANIZATION_MEMBERS,
    )

    assert helpers.get_mqa_visibility() == helpers.MQA_VISIBILITY_ORGANIZATION_MEMBERS


def test_mqa_visibility_admin_config_is_hidden_by_default(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)

    assert helpers.mqa_visibility_admin_config_enabled() is False


def test_mqa_visibility_admin_config_can_be_enabled_from_ini(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)
    monkeypatch.setitem(
        helpers.toolkit.config,
        helpers.MQA_VISIBILITY_ADMIN_CONFIG_ENABLED,
        "yes",
    )

    assert helpers.mqa_visibility_admin_config_enabled() is True


def test_mqa_visibility_allowed_values_default_to_hidden_and_org_members(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)

    assert helpers.get_mqa_visibility_allowed_values() == (
        helpers.MQA_VISIBILITY_HIDDEN,
        helpers.MQA_VISIBILITY_ORGANIZATION_MEMBERS,
    )
    assert helpers.get_mqa_visibility_options() == [
        {'value': helpers.MQA_VISIBILITY_HIDDEN, 'text': 'Κρυφό'},
        {
            'value': helpers.MQA_VISIBILITY_ORGANIZATION_MEMBERS,
            'text': 'Μέλη οργανισμών',
        },
    ]


def test_mqa_visibility_allowed_values_are_comma_separated(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)
    monkeypatch.setitem(
        helpers.toolkit.config,
        helpers.MQA_VISIBILITY_ALLOWED_VALUES_CONFIG,
        "hidden,public",
    )

    assert helpers.get_mqa_visibility_allowed_values() == (
        helpers.MQA_VISIBILITY_HIDDEN,
        helpers.MQA_VISIBILITY_PUBLIC,
    )


def test_mqa_visibility_allowed_values_normalize_aliases(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)
    monkeypatch.setitem(
        helpers.toolkit.config,
        helpers.MQA_VISIBILITY_ALLOWED_VALUES_CONFIG,
        "hidden,org_members",
    )

    assert helpers.get_mqa_visibility_allowed_values() == (
        helpers.MQA_VISIBILITY_HIDDEN,
        helpers.MQA_VISIBILITY_ORGANIZATION_MEMBERS,
    )


def test_mqa_visibility_allowed_values_ignore_invalid_entries(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)
    monkeypatch.setitem(
        helpers.toolkit.config,
        helpers.MQA_VISIBILITY_ALLOWED_VALUES_CONFIG,
        "invalid,public",
    )

    assert helpers.get_mqa_visibility_allowed_values() == (
        helpers.MQA_VISIBILITY_PUBLIC,
    )


def test_mqa_visibility_validator_rejects_disallowed_values(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)

    with pytest.raises(helpers.toolkit.Invalid):
        helpers.mqa_visibility_allowed_value_validator(
            helpers.MQA_VISIBILITY_PUBLIC,
            {},
        )

    assert helpers.mqa_visibility_allowed_value_validator(
        helpers.MQA_VISIBILITY_ORGANIZATION_MEMBERS,
        {},
    ) == helpers.MQA_VISIBILITY_ORGANIZATION_MEMBERS


def test_mqa_visibility_validator_accepts_allowed_values_from_ini(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)
    monkeypatch.setitem(
        helpers.toolkit.config,
        helpers.MQA_VISIBILITY_ALLOWED_VALUES_CONFIG,
        "hidden,public",
    )

    assert helpers.mqa_visibility_allowed_value_validator(
        helpers.MQA_VISIBILITY_PUBLIC,
        {},
    ) == helpers.MQA_VISIBILITY_PUBLIC


def test_can_view_mqa_public_for_dataset_only(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)
    monkeypatch.setitem(
        helpers.toolkit.config,
        helpers.MQA_VISIBILITY_CONFIG,
        helpers.MQA_VISIBILITY_PUBLIC,
    )

    assert helpers.can_view_mqa({"type": "dataset"}) is True
    assert helpers.can_view_mqa({"type": "data-service"}) is False


def test_can_view_mqa_organization_members(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)
    monkeypatch.setitem(
        helpers.toolkit.config,
        helpers.MQA_VISIBILITY_CONFIG,
        helpers.MQA_VISIBILITY_ORGANIZATION_MEMBERS,
    )

    def deny_sysadmin(action, context, data_dict):
        raise helpers.toolkit.NotAuthorized()

    def fake_get_action(action):
        assert action == "organization_list_for_user"
        return lambda context, data_dict: [{"name": "org"}]

    monkeypatch.setattr(helpers.toolkit, "check_access", deny_sysadmin)
    monkeypatch.setattr(helpers.toolkit, "get_action", fake_get_action)

    assert helpers.can_view_mqa({"type": "dataset"}, user=_user()) is True
    assert helpers.can_view_mqa_facet(user=_user()) is True
    assert helpers.can_view_mqa({"type": "dataset"}, user=_user(authenticated=False)) is False


def test_can_view_mqa_report_is_public_when_mqa_visibility_is_public(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)
    monkeypatch.setitem(
        helpers.toolkit.config,
        helpers.MQA_VISIBILITY_CONFIG,
        helpers.MQA_VISIBILITY_PUBLIC,
    )

    assert helpers.can_view_mqa_report(user=_user(sysadmin=True)) is True
    assert helpers.can_view_mqa_report(user=_user()) is True
    assert helpers.can_view_mqa_report(user=_user(authenticated=False)) is True


def test_can_view_mqa_report_requires_sysadmin_for_organization_members(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)
    monkeypatch.setitem(
        helpers.toolkit.config,
        helpers.MQA_VISIBILITY_CONFIG,
        helpers.MQA_VISIBILITY_ORGANIZATION_MEMBERS,
    )

    def deny_sysadmin(action, context, data_dict):
        raise helpers.toolkit.NotAuthorized()

    monkeypatch.setattr(helpers.toolkit, "check_access", deny_sysadmin)

    assert helpers.can_view_mqa_report(user=_user(sysadmin=True)) is True
    assert helpers.can_view_mqa_report(user=_user()) is False
    assert helpers.can_view_mqa_report(user=_user(authenticated=False)) is False


def test_can_view_mqa_report_is_hidden_when_mqa_visibility_is_hidden(monkeypatch):
    _clear_mqa_visibility_config(monkeypatch)

    monkeypatch.setitem(
        helpers.toolkit.config,
        helpers.MQA_VISIBILITY_CONFIG,
        helpers.MQA_VISIBILITY_HIDDEN,
    )
    assert helpers.can_view_mqa_report(user=_user(sysadmin=True)) is False
