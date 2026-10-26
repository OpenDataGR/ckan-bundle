from six.moves.urllib.parse import parse_qsl, urlsplit

import pytest

from ckanext.geoview import safe_http
from ckanext.geoview import utils


class FakeRequest:
    def __init__(
        self,
        method="GET",
        query_string=b"",
        body=b"",
        content_type=None,
    ):
        self.environ = {"REQUEST_METHOD": method}
        if content_type:
            self.environ["CONTENT_TYPE"] = content_type
        self.query_string = query_string
        self._body = body

    def get_data(self):
        return self._body


def test_get_replaces_stored_ogc_params_and_preserves_viewer_query(
    monkeypatch,
):
    monkeypatch.setitem(
        utils.toolkit.config,
        "ckanext.geoview.forward_ogc_request_params",
        "False",
    )
    request = FakeRequest(
        query_string=(
            b"SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.3.0"
            b"&LAYERS=roads&BBOX=1%2C2%2C3%2C4&CRS=EPSG%3A4326"
            b"&FORMAT=image%2Fpng"
        )
    )

    method, url, headers, body = utils._prepare_service_proxy_request(
        request,
        "https://maps.example.test/wms?service=OLD&LAYERS=old"
        "&token=abc&filter=one&filter=two#ignored",
    )

    assert method == "GET"
    assert headers == {}
    assert body is None
    assert urlsplit(url).fragment == ""
    assert parse_qsl(urlsplit(url).query, keep_blank_values=True) == [
        ("token", "abc"),
        ("filter", "one"),
        ("filter", "two"),
        ("SERVICE", "WMS"),
        ("REQUEST", "GetCapabilities"),
        ("VERSION", "1.3.0"),
        ("LAYERS", "roads"),
        ("BBOX", "1,2,3,4"),
        ("CRS", "EPSG:4326"),
        ("FORMAT", "image/png"),
    ]


def test_forward_option_keeps_stored_ogc_params(monkeypatch):
    monkeypatch.setitem(
        utils.toolkit.config,
        "ckanext.geoview.forward_ogc_request_params",
        "True",
    )

    _, url, _, _ = utils._prepare_service_proxy_request(
        FakeRequest(query_string=b"REQUEST=GetMap"),
        "https://maps.example.test/wms?SERVICE=WMS&VERSION=1.1.1",
    )

    assert parse_qsl(urlsplit(url).query) == [
        ("SERVICE", "WMS"),
        ("VERSION", "1.1.1"),
        ("REQUEST", "GetMap"),
    ]


def test_force_http_is_an_exact_initial_hostname_match(monkeypatch):
    monkeypatch.setitem(
        utils.toolkit.config,
        "ckanext.geoview.force_http_hosts",
        "maps.example.test",
    )

    _, forced_url, _, _ = utils._prepare_service_proxy_request(
        FakeRequest(),
        "https://maps.example.test/wms",
    )
    _, untouched_url, _, _ = utils._prepare_service_proxy_request(
        FakeRequest(),
        "https://sub.maps.example.test/wms",
    )

    assert urlsplit(forced_url).scheme == "http"
    assert urlsplit(untouched_url).scheme == "https"


def test_legacy_post_preserves_body_content_type_and_resource_query(
    monkeypatch,
):
    monkeypatch.setitem(
        utils.toolkit.config,
        "ckanext.geoview.forward_ogc_request_params",
        "True",
    )
    request = FakeRequest(
        method="POST",
        query_string=b"ignored=viewer-query",
        body=b"<GetFeature />",
        content_type="application/xml",
    )

    method, url, headers, body = utils._prepare_service_proxy_request(
        request,
        "https://maps.example.test/wfs?SERVICE=WFS",
    )

    assert method == "POST"
    assert urlsplit(url).query == "SERVICE=WFS"
    assert headers == {"Content-Type": "application/xml"}
    assert body == b"<GetFeature />"


@pytest.mark.parametrize(
    "url",
    (
        "not-a-url",
        "//example.test/path",
        "https://example.test:99999/path",
        "https://[broken/path",
    ),
)
def test_missing_scheme_or_host_is_rejected_before_network(url):
    with pytest.raises(safe_http.UnsafeProxyUrl):
        utils._prepare_service_proxy_request(FakeRequest(), url)
