import pytest

from rdflib import Graph, Literal, URIRef

from ckanext.dcat.processors import RDFSerializer
from ckanext.dcat.profiles import DCAT, DCT
from ckanext.dcat.profiles import euro_dcat_ap_base
from ckanext.dcat.profiles.euro_dcat_ap_base import (
    BaseEuropeanDCATAPProfile,
    OUTPUT_RESOURCE_FORMAT_AS_FILE_TYPE_URI_CONFIG,
    _looks_like_media_type,
)


FILE_TYPE_BASE_URI = "http://publications.europa.eu/resource/authority/file-type/"


def _vocabulary(*codes):
    return {
        "tags": [
            {
                "name": code,
                "value_uri": FILE_TYPE_BASE_URI + code,
            }
            for code in codes
        ]
    }


def _profile(monkeypatch, *codes, calls=None):
    def vocabulary_show(context, data_dict):
        assert context == {"ignore_auth": True}
        assert data_dict == {"id": "File Type"}
        if calls is not None:
            calls.append(data_dict)
        return _vocabulary(*codes)

    monkeypatch.setattr(
        euro_dcat_ap_base.toolkit,
        "get_action",
        lambda action: vocabulary_show,
    )
    return BaseEuropeanDCATAPProfile(Graph())


@pytest.mark.ckan_config(OUTPUT_RESOURCE_FORMAT_AS_FILE_TYPE_URI_CONFIG, "true")
@pytest.mark.parametrize(
    "value, expected_code",
    [
        ("CSV", "CSV"),
        (" csv ", "CSV"),
        (".csv", "CSV"),
        (".PDF", "PDF"),
        ("WMS", "WMS_SRVC"),
        ("wfs", "WFS_SRVC"),
        ("WCS", "WCS_SRVC"),
        ("WMTS", "WMTS_SRVC"),
        ("GeoPackage", "GPKG"),
        ("TIF", "TIFF"),
        ("GZ", "GZIP"),
        ("MP4", "MPEG4"),
        ("MD", "MARKDOWN"),
        ("TTL", "RDF_TURTLE"),
        ("dBase", "DBF"),
        ("SHAPE-ZIP", "SHP"),
        ("shape zip", "SHP"),
        ("SHP-ZIP", "SHP"),
        ("shp zip", "SHP"),
        ("csv.zip", "CSV"),
        ("rar.", "RAR"),
    ],
)
def test_file_type_format_matching(monkeypatch, value, expected_code):
    codes = {
        "CSV",
        "DBF",
        "GPKG",
        "GZIP",
        "MARKDOWN",
        "MPEG4",
        "PDF",
        "RAR",
        "RDF_TURTLE",
        "SHP",
        "TIFF",
        "WCS_SRVC",
        "WFS_SRVC",
        "WMS_SRVC",
        "WMTS_SRVC",
    }
    profile = _profile(monkeypatch, *codes)

    assert profile._file_type_uri_for_format(value) == FILE_TYPE_BASE_URI + expected_code


@pytest.mark.ckan_config(OUTPUT_RESOURCE_FORMAT_AS_FILE_TYPE_URI_CONFIG, "true")
def test_exact_code_takes_priority_over_alias(monkeypatch):
    profile = _profile(monkeypatch, "WMS", "WMS_SRVC")

    assert profile._file_type_uri_for_format("WMS") == FILE_TYPE_BASE_URI + "WMS"


@pytest.mark.ckan_config(OUTPUT_RESOURCE_FORMAT_AS_FILE_TYPE_URI_CONFIG, "true")
@pytest.mark.parametrize(
    "value",
    [
        "Unknown",
        "Esri REST",
        "XLXS",
        "xlsx/csv/shape file/GeoJson",
    ],
)
def test_ambiguous_values_are_not_matched(monkeypatch, value):
    profile = _profile(monkeypatch, "XLSX", "REST")

    assert profile._file_type_uri_for_format(value) is None


@pytest.mark.ckan_config(OUTPUT_RESOURCE_FORMAT_AS_FILE_TYPE_URI_CONFIG, "true")
def test_alias_requires_target_in_live_vocabulary(monkeypatch):
    profile = _profile(monkeypatch, "CSV")

    assert profile._file_type_uri_for_format("WMS") is None


@pytest.mark.ckan_config(OUTPUT_RESOURCE_FORMAT_AS_FILE_TYPE_URI_CONFIG, "false")
def test_matching_can_be_disabled(monkeypatch):
    profile = _profile(monkeypatch, "CSV")

    assert profile._file_type_uri_for_format("CSV") is None


@pytest.mark.ckan_config(OUTPUT_RESOURCE_FORMAT_AS_FILE_TYPE_URI_CONFIG, "true")
@pytest.mark.parametrize(
    "value",
    [
        "http://publications.europa.eu/resource/authority/file-type/CSV",
        "https://publications.europa.eu/resource/authority/file-type/CSV",
    ],
)
def test_existing_uri_bypasses_matching(monkeypatch, value):
    profile = _profile(monkeypatch, "CSV")

    assert profile._file_type_uri_for_format(value) is None


@pytest.mark.ckan_config(OUTPUT_RESOURCE_FORMAT_AS_FILE_TYPE_URI_CONFIG, "true")
def test_vocabulary_is_loaded_once_per_graph(monkeypatch):
    calls = []
    profile = _profile(monkeypatch, "CSV", calls=calls)

    assert profile._file_type_uri_for_format("CSV") == FILE_TYPE_BASE_URI + "CSV"
    assert profile._file_type_uri_for_format("csv") == FILE_TYPE_BASE_URI + "CSV"
    assert len(calls) == 1


@pytest.mark.ckan_config(OUTPUT_RESOURCE_FORMAT_AS_FILE_TYPE_URI_CONFIG, "true")
def test_vocabulary_failure_returns_no_match_and_is_cached(monkeypatch, caplog):
    calls = []

    def get_action(action):
        calls.append(action)
        raise RuntimeError("vocabulary unavailable")

    monkeypatch.setattr(euro_dcat_ap_base.toolkit, "get_action", get_action)
    profile = BaseEuropeanDCATAPProfile(Graph())

    assert profile._file_type_uri_for_format("CSV") is None
    assert profile._file_type_uri_for_format("CSV") is None
    assert calls == ["vocabularyadmin_vocabulary_show"]
    assert "Could not load File Type vocabulary" in caplog.text


@pytest.mark.parametrize(
    "value",
    [
        "application/vnd.rar",
        "application/xhtml+xml",
        "chemical/x-cif",
        "text/markdown",
    ],
)
def test_valid_media_types_are_detected(value):
    assert _looks_like_media_type(value)


@pytest.mark.parametrize(
    "value",
    [
        "xlsx/csv/shape file/GeoJson",
        "SHAPE/ZIP WITH SPACES",
        "not a media type",
        "CSV",
    ],
)
def test_arbitrary_composite_values_are_not_media_types(value):
    assert not _looks_like_media_type(value)


def _serialized_format_and_media_type(format_value, profile_name="euro_dcat_ap"):
    dataset = {
        "id": "4b6fe9ca-dc77-4cec-92a4-55c6624a5bd6",
        "name": "test-dataset",
        "title": "Test DCAT dataset",
        "resources": [
            {
                "id": "c041c635-054f-4431-b647-f9186926d021",
                "package_id": "4b6fe9ca-dc77-4cec-92a4-55c6624a5bd6",
                "name": "Test resource",
                "format": format_value,
            }
        ],
    }
    serializer = RDFSerializer(profiles=[profile_name])
    dataset_ref = serializer.graph_from_dataset(dataset)
    distribution = next(serializer.g.objects(dataset_ref, DCAT.distribution))
    return (
        list(serializer.g.objects(distribution, DCT["format"])),
        list(serializer.g.objects(distribution, DCAT.mediaType)),
    )


def test_composite_value_with_slash_remains_format_literal():
    value = "xlsx/csv/shape file/GeoJson"

    formats, media_types = _serialized_format_and_media_type(value)

    assert formats == [Literal(value)]
    assert media_types == []


def test_unresolved_media_type_remains_format_literal(monkeypatch):
    value = "application/vnd.rar"

    def get_action(action):
        raise RuntimeError("vocabulary unavailable")

    monkeypatch.setattr(
        euro_dcat_ap_base.toolkit,
        "get_action",
        get_action,
    )

    formats, media_types = _serialized_format_and_media_type(value)

    assert formats == [Literal(value)]
    assert media_types == []


@pytest.mark.ckan_config(OUTPUT_RESOURCE_FORMAT_AS_FILE_TYPE_URI_CONFIG, "true")
@pytest.mark.parametrize(
    "profile_name",
    ["euro_dcat_ap", "euro_dcat_ap_2", "euro_dcat_ap_3"],
)
def test_alias_is_serialized_as_uri_for_all_european_profiles(
    monkeypatch, profile_name
):
    # Set up the action mock used by the profile during graph serialization.
    _profile(monkeypatch, "WMS_SRVC")

    formats, media_types = _serialized_format_and_media_type("WMS", profile_name)

    assert formats == [URIRef(FILE_TYPE_BASE_URI + "WMS_SRVC")]
    assert media_types == []
