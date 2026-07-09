import json

from ckanext.data_gov_gr import helpers


def _spatial_extent(pkg):
    value = helpers.data_gov_gr_dataset_spatial_extent(pkg)
    return json.loads(value) if value else None


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
