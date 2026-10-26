from types import SimpleNamespace

import pytest
import requests

from ckanext.spatial.harvesters import csw as harvester_module
from ckanext.spatial.lib.csw_client import CswService


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


@pytest.mark.parametrize("verify", [True, False])
def test_csw_service_applies_tls_policy_to_owslib_and_session(monkeypatch, verify):
    class FakeCatalogueServiceWeb:
        def __init__(self, endpoint, **kwargs):
            self.url = endpoint
            self.kwargs = kwargs

    monkeypatch.setattr(CswService, "_Implementation", FakeCatalogueServiceWeb)

    client = CswService("https://example.test/csw", verify=verify)

    assert client.verify is verify
    assert client._session.verify is verify
    assert client._ows().kwargs["auth"].verify is verify


def test_csw_service_defaults_to_tls_verification(monkeypatch):
    class FakeCatalogueServiceWeb:
        def __init__(self, endpoint, **kwargs):
            self.url = endpoint
            self.kwargs = kwargs

    monkeypatch.setattr(CswService, "_Implementation", FakeCatalogueServiceWeb)

    client = CswService("https://example.test/csw")

    assert client.verify is True
    assert client._session.verify is True
    assert client._ows().kwargs["auth"].verify is True


def test_http_get_uses_configured_session(monkeypatch):
    client = CswService()
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return "response"

    monkeypatch.setattr(client._session, "get", fake_get)

    result = client.http_get("https://example.test/records", timeout=17)

    assert result == "response"
    assert calls == [("https://example.test/records", {"timeout": 17})]


def test_identifier_get_fallback_uses_configured_session(monkeypatch):
    response = FakeResponse(b"""
        <csw:GetRecordsResponse
            xmlns:csw="http://www.opengis.net/cat/csw/2.0.2"
            xmlns:dc="http://purl.org/dc/elements/1.1/">
          <csw:SearchResults>
            <csw:SummaryRecord><dc:identifier>record-1</dc:identifier></csw:SummaryRecord>
          </csw:SearchResults>
        </csw:GetRecordsResponse>
    """)
    calls = []
    client = CswService()
    monkeypatch.setattr(
        client,
        "_ows",
        lambda **kwargs: SimpleNamespace(url="https://example.test/csw"),
    )
    monkeypatch.setattr(
        client,
        "http_get",
        lambda url, **kwargs: calls.append((url, kwargs)) or response,
    )

    identifiers = list(client._getidentifiers_using_get())

    assert identifiers == ["record-1"]
    assert len(calls) == 1
    assert calls[0][1] == {"timeout": 30}


def test_hits_get_fallback_uses_configured_session(monkeypatch):
    response = FakeResponse(b"""
        <csw:GetRecordsResponse xmlns:csw="http://www.opengis.net/cat/csw/2.0.2">
          <csw:SearchResults numberOfRecordsMatched="1"/>
        </csw:GetRecordsResponse>
    """)
    calls = []
    client = CswService()
    csw = SimpleNamespace(url="https://example.test/csw")
    csw.getrecords2 = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("POST failed"))
    monkeypatch.setattr(client, "_ows", lambda **kwargs: csw)
    monkeypatch.setattr(
        client,
        "_getidentifiers_using_get",
        lambda *args, **kwargs: iter(["record-1"]),
    )
    monkeypatch.setattr(
        client,
        "http_get",
        lambda url, **kwargs: calls.append((url, kwargs)) or response,
    )

    identifiers = list(client.getidentifiers(page=10))

    assert identifiers == ["record-1"]
    assert len(calls) == 1
    assert calls[0][1] == {"timeout": 30}


def test_get_record_by_id_fallback_uses_csw_session():
    response = FakeResponse(b"""
        <csw:GetRecordByIdResponse
            xmlns:csw="http://www.opengis.net/cat/csw/2.0.2"
            xmlns:gmd="http://www.isotc211.org/2005/gmd">
          <gmd:MD_Metadata/>
        </csw:GetRecordByIdResponse>
    """)
    calls = []

    class FakeCsw:
        def _ows(self):
            return SimpleNamespace(url="https://example.test/csw")

        def http_get(self, url, **kwargs):
            calls.append((url, kwargs))
            return response

    harvester = SimpleNamespace(csw=FakeCsw())

    record = harvester_module.CSWHarvester._get_record_by_id_using_get(
        harvester,
        "record-1",
    )

    assert "MD_Metadata" in record["xml"]
    assert len(calls) == 1
    assert calls[0][1] == {"timeout": 30}


@pytest.mark.parametrize(
    "configured_value, expected_verify",
    [
        (None, True),
        (False, True),
        ("false", True),
        ("0", True),
        ("no", True),
        ("off", True),
        (True, False),
        ("true", False),
        ("1", False),
        ("yes", False),
        ("on", False),
    ],
)
def test_harvester_passes_source_tls_policy_to_csw_client(
    monkeypatch,
    configured_value,
    expected_verify,
):
    calls = []

    class FakeCswService:
        def __init__(self, url, verify=True):
            calls.append((url, verify))

    monkeypatch.setattr(harvester_module, "CswService", FakeCswService)
    original_request = requests.request
    source_config = {}
    if configured_value is not None:
        source_config["disable_ssl_verification"] = configured_value
    harvester = SimpleNamespace(source_config=source_config)

    harvester_module.CSWHarvester._setup_csw_client(
        harvester,
        "https://example.test/csw",
    )

    assert calls == [("https://example.test/csw", expected_verify)]
    assert requests.request is original_request
