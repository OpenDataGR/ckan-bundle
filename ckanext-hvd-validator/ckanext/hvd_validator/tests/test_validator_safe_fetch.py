from types import SimpleNamespace

import pytest

from ckanext.hvd_validator import validator


class FakeResponse:
    def __init__(self, chunks=(), headers=None, error=None):
        self._chunks = chunks
        self.headers = headers or {}
        self.encoding = "utf-8"
        self.error = error
        self.closed = False

    def raise_for_status(self):
        if self.error:
            raise self.error

    def iter_content(self, **kwargs):
        yield from self._chunks

    def close(self):
        self.closed = True


def test_validator_safe_get_uses_pinned_fetcher(monkeypatch):
    expected = object()
    calls = []

    def fake_safe_get(url, **kwargs):
        calls.append((url, kwargs))
        return expected

    monkeypatch.setattr(validator, "safe_get", fake_safe_get)

    result = validator._safe_get(
        "https://example.test/data",
        timeout=7,
        headers={"Accept": "application/rdf+xml"},
        stream=True,
    )

    assert result is expected
    assert calls == [
        (
            "https://example.test/data",
            {
                "timeout": 7,
                "headers": {"Accept": "application/rdf+xml"},
                "stream": True,
                "max_redirects": validator._MAX_REDIRECTS,
            },
        )
    ]


def test_safe_get_text_closes_response_after_success(monkeypatch):
    response = FakeResponse(chunks=[b"valid ", b"rdf"])
    monkeypatch.setattr(
        validator, "_safe_get", lambda *args, **kwargs: response
    )

    text, headers = validator._safe_get_text(
        "https://example.test/data", timeout=5, headers={}
    )

    assert text == "valid rdf"
    assert headers == {}
    assert response.closed is True


def test_safe_get_text_closes_response_after_http_error(monkeypatch):
    response = FakeResponse(error=RuntimeError("HTTP error"))
    monkeypatch.setattr(
        validator, "_safe_get", lambda *args, **kwargs: response
    )

    with pytest.raises(RuntimeError, match="HTTP error"):
        validator._safe_get_text(
            "https://example.test/data", timeout=5, headers={}
        )

    assert response.closed is True


def test_content_length_limit_is_preserved(monkeypatch):
    response = FakeResponse(
        chunks=[b"small"],
        headers={"Content-Length": str(validator._MAX_FETCH_BYTES + 1)},
    )
    monkeypatch.setattr(
        validator, "_safe_get", lambda *args, **kwargs: response
    )

    with pytest.raises(validator.FetchResponseTooLarge):
        validator._safe_get_text(
            "https://example.test/data", timeout=5, headers={}
        )

    assert response.closed is True


def test_streaming_body_limit_is_preserved(monkeypatch):
    response = FakeResponse(
        chunks=[b"x" * validator._MAX_FETCH_BYTES, b"x"]
    )
    monkeypatch.setattr(
        validator, "_safe_get", lambda *args, **kwargs: response
    )

    with pytest.raises(validator.FetchResponseTooLarge):
        validator._safe_get_text(
            "https://example.test/data", timeout=5, headers={}
        )

    assert response.closed is True


def test_vocabulary_fetch_keeps_short_timeout(monkeypatch):
    calls = []
    url = "https://vocabulary.example.test/item"
    empty_rdf = (
        "<rdf:RDF "
        "xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'/>"
    )
    monkeypatch.setattr(
        validator,
        "_safe_get_text",
        lambda target_url, **kwargs: calls.append((target_url, kwargs))
        or (empty_rdf, {}),
    )
    validator._hvd_vocab_cache.pop(url, None)

    graph = validator._get_vocab_graph(url)

    assert graph is not None
    assert calls[0][1]["timeout"] == validator._VOCAB_FETCH_TIMEOUT


def test_explicit_url_fetch_keeps_long_timeout(monkeypatch):
    calls = []
    graph = SimpleNamespace()
    monkeypatch.setattr(
        validator,
        "_safe_get_text",
        lambda target_url, **kwargs: calls.append((target_url, kwargs))
        or ("rdf", {"Content-Type": "application/rdf+xml"}),
    )
    monkeypatch.setattr(
        validator, "_parse_graph", lambda *args, **kwargs: graph
    )
    monkeypatch.setattr(
        validator,
        "validate_hvd_graph",
        lambda value: {"conforms": value is graph},
    )

    result = validator.validate_from_url("https://example.test/dataset.rdf")

    assert result["conforms"] is True
    assert calls[0][1]["timeout"] == validator._URL_FETCH_TIMEOUT
