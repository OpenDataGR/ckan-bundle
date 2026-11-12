import pytest

from rdflib import Graph, Literal, URIRef

from ckanext.dcat.processors import RDFSerializer
from ckanext.dcat.profiles import DCAT, DCT, RDF
from ckanext.dcat.profiles import euro_dcat_ap_base
from ckanext.dcat.profiles.euro_dcat_ap_base import (
    BaseEuropeanDCATAPProfile,
    _media_type_key,
    _media_type_key_from_iana_uri,
)


IANA_MEDIA_TYPE_BASE_URI = "https://www.iana.org/assignments/media-types/"


def _media_type_tag(
    media_type,
    *,
    value_uri=None,
    label_en=None,
    is_active=True,
):
    return {
        "name": media_type.replace("/", " "),
        "label_en": media_type if label_en is None else label_en,
        "value_uri": (
            IANA_MEDIA_TYPE_BASE_URI + media_type
            if value_uri is None
            else value_uri
        ),
        "is_active": is_active,
    }


def _profile(monkeypatch, *tags, calls=None):
    def vocabulary_show(context, data_dict):
        assert context == {"ignore_auth": True}
        assert data_dict == {"id": "Media types"}
        if calls is not None:
            calls.append(data_dict)
        return {"tags": list(tags)}

    def get_action(action):
        assert action == "vocabularyadmin_vocabulary_show"
        return vocabulary_show

    monkeypatch.setattr(euro_dcat_ap_base.toolkit, "get_action", get_action)
    return BaseEuropeanDCATAPProfile(Graph())


@pytest.mark.parametrize(
    "value, expected",
    [
        ("application/json", "application/json"),
        (" Application/JSON ", "application/json"),
        ("application/json; charset=utf-8", "application/json"),
        ("text/markdown; charset=UTF-8", "text/markdown"),
    ],
)
def test_media_type_key_normalizes_bare_values_and_parameters(value, expected):
    assert _media_type_key(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "not a media type",
        "xlsx/csv/shape file/GeoJson",
        "https://www.iana.org/assignments/media-types/application/json",
        None,
    ],
)
def test_media_type_key_rejects_non_bare_values(value):
    assert _media_type_key(value) is None


def test_iana_uri_media_type_key_requires_iana_hostname():
    assert (
        _media_type_key_from_iana_uri(
            "https://www.iana.org/assignments/media-types/application/json"
        )
        == "application/json"
    )
    assert (
        _media_type_key_from_iana_uri(
            "https://example.com/assignments/media-types/application/json"
        )
        is None
    )


@pytest.mark.parametrize(
    "value",
    [
        "application/json",
        " Application/JSON ",
        "application/json; charset=utf-8",
    ],
)
def test_resolver_maps_bare_media_type_to_vocabulary_uri(monkeypatch, value):
    profile = _profile(monkeypatch, _media_type_tag("application/json"))

    assert (
        profile._media_type_uri_for_value(value)
        == IANA_MEDIA_TYPE_BASE_URI + "application/json"
    )


def test_resolver_uses_uri_path_when_label_is_missing(monkeypatch):
    tag = _media_type_tag("application/json")
    tag.pop("label_en")
    profile = _profile(monkeypatch, tag)

    assert (
        profile._media_type_uri_for_value("application/json")
        == IANA_MEDIA_TYPE_BASE_URI + "application/json"
    )


def test_resolver_ignores_inactive_and_invalid_vocabulary_entries(monkeypatch):
    profile = _profile(
        monkeypatch,
        _media_type_tag("application/json", is_active=False),
        _media_type_tag("application/xml", is_active="false"),
        _media_type_tag("text/markdown", value_uri="not-a-uri"),
    )

    assert profile._media_type_uri_for_value("application/json") is None
    assert profile._media_type_uri_for_value("application/xml") is None
    assert profile._media_type_uri_for_value("text/markdown") is None


def test_resolver_keeps_existing_non_iana_http_uri(monkeypatch):
    profile = _profile(monkeypatch)
    value = "https://example.com/media-types/custom"

    assert profile._media_type_uri_for_value(value) == value
    assert (
        profile._media_type_uri_for_value(value, allow_non_iana_uri=False)
        is None
    )


def test_resolver_canonicalizes_existing_iana_uri(monkeypatch):
    canonical_uri = IANA_MEDIA_TYPE_BASE_URI + "application/json"
    profile = _profile(monkeypatch, _media_type_tag("application/json"))

    assert (
        profile._media_type_uri_for_value(
            "http://www.iana.org/assignments/media-types/Application/JSON"
        )
        == canonical_uri
    )


def test_vocabulary_is_loaded_once_per_graph(monkeypatch):
    calls = []
    profile = _profile(
        monkeypatch,
        _media_type_tag("application/json"),
        calls=calls,
    )

    assert profile._media_type_uri_for_value("application/json")
    assert profile._media_type_uri_for_value("Application/JSON")
    assert len(calls) == 1


def test_vocabulary_failure_returns_no_match_and_is_cached(monkeypatch, caplog):
    calls = []

    def get_action(action):
        calls.append(action)
        raise RuntimeError("vocabulary unavailable")

    monkeypatch.setattr(euro_dcat_ap_base.toolkit, "get_action", get_action)
    profile = BaseEuropeanDCATAPProfile(Graph())

    assert profile._media_type_uri_for_value("application/json") is None
    assert profile._media_type_uri_for_value("application/json") is None
    assert calls == ["vocabularyadmin_vocabulary_show"]
    assert "Could not load Media types vocabulary" in caplog.text


def _serialized_format_and_media_type(
    monkeypatch,
    *,
    format_value=None,
    mimetype_value=None,
    tags=(),
    profile_name="euro_dcat_ap",
):
    _profile(monkeypatch, *tags)
    resource = {
        "id": "c041c635-054f-4431-b647-f9186926d021",
        "package_id": "4b6fe9ca-dc77-4cec-92a4-55c6624a5bd6",
        "name": "Test resource",
    }
    if format_value is not None:
        resource["format"] = format_value
    if mimetype_value is not None:
        resource["mimetype"] = mimetype_value

    dataset = {
        "id": "4b6fe9ca-dc77-4cec-92a4-55c6624a5bd6",
        "name": "test-dataset",
        "title": "Test DCAT dataset",
        "resources": [resource],
    }
    serializer = RDFSerializer(profiles=[profile_name])
    dataset_ref = serializer.graph_from_dataset(dataset)
    distribution = next(serializer.g.objects(dataset_ref, DCAT.distribution))
    return serializer.g, distribution


@pytest.mark.parametrize(
    "profile_name",
    ["euro_dcat_ap", "euro_dcat_ap_2", "euro_dcat_ap_3"],
)
def test_bare_format_media_type_is_serialized_as_uri_for_all_european_profiles(
    monkeypatch,
    profile_name,
):
    tag = _media_type_tag("application/json")
    graph, distribution = _serialized_format_and_media_type(
        monkeypatch,
        format_value="application/json",
        tags=(tag,),
        profile_name=profile_name,
    )
    media_type_uri = URIRef(IANA_MEDIA_TYPE_BASE_URI + "application/json")

    assert list(graph.objects(distribution, DCT["format"])) == []
    assert list(graph.objects(distribution, DCAT.mediaType)) == [media_type_uri]
    assert (media_type_uri, RDF.type, DCT.MediaType) in graph


def test_explicit_bare_mimetype_is_serialized_as_uri(monkeypatch):
    tag = _media_type_tag("text/markdown")
    graph, distribution = _serialized_format_and_media_type(
        monkeypatch,
        mimetype_value="text/markdown",
        tags=(tag,),
    )

    assert list(graph.objects(distribution, DCAT.mediaType)) == [
        URIRef(IANA_MEDIA_TYPE_BASE_URI + "text/markdown")
    ]


def test_unknown_format_media_type_remains_dct_format_literal(monkeypatch):
    value = "chemical/x-cif"
    graph, distribution = _serialized_format_and_media_type(
        monkeypatch,
        format_value=value,
    )

    assert list(graph.objects(distribution, DCT["format"])) == [Literal(value)]
    assert list(graph.objects(distribution, DCAT.mediaType)) == []


def test_unknown_explicit_mimetype_is_omitted(monkeypatch, caplog):
    value = "chemical/x-cif"
    graph, distribution = _serialized_format_and_media_type(
        monkeypatch,
        mimetype_value=value,
    )

    assert list(graph.objects(distribution, DCAT.mediaType)) == []
    assert value in caplog.text


def test_same_unknown_format_and_mimetype_preserves_format(monkeypatch):
    value = "chemical/x-cif"
    graph, distribution = _serialized_format_and_media_type(
        monkeypatch,
        format_value=value,
        mimetype_value=value,
    )

    assert list(graph.objects(distribution, DCT["format"])) == [Literal(value)]
    assert list(graph.objects(distribution, DCAT.mediaType)) == []


def test_explicit_custom_media_type_uri_is_serialized_as_uri(monkeypatch):
    value = "https://example.com/media-types/custom"
    graph, distribution = _serialized_format_and_media_type(
        monkeypatch,
        mimetype_value=value,
    )

    assert list(graph.objects(distribution, DCAT.mediaType)) == [URIRef(value)]


def test_different_format_and_mimetype_are_serialized_independently(monkeypatch):
    tag = _media_type_tag("application/json")
    graph, distribution = _serialized_format_and_media_type(
        monkeypatch,
        format_value="CSV",
        mimetype_value="application/json",
        tags=(tag,),
    )

    assert list(graph.objects(distribution, DCT["format"])) == [Literal("CSV")]
    assert list(graph.objects(distribution, DCAT.mediaType)) == [
        URIRef(IANA_MEDIA_TYPE_BASE_URI + "application/json")
    ]


def test_non_iana_format_uri_remains_dct_format_uri(monkeypatch):
    value = "https://example.com/my/format"
    graph, distribution = _serialized_format_and_media_type(
        monkeypatch,
        format_value=value,
    )

    assert list(graph.objects(distribution, DCT["format"])) == [URIRef(value)]
    assert list(graph.objects(distribution, DCAT.mediaType)) == []


def test_all_serialized_media_types_are_uris(monkeypatch):
    tag = _media_type_tag("application/json")
    graph, _ = _serialized_format_and_media_type(
        monkeypatch,
        format_value="application/json",
        tags=(tag,),
    )

    assert all(
        isinstance(value, URIRef)
        for value in graph.objects(None, DCAT.mediaType)
    )
