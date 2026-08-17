import logging

import pytest

import ckan.lib.api_token as api_token
from ckan.lib.api_token import _get_secret


@pytest.mark.ckan_config("SECRET_KEY", "super_secret")
@pytest.mark.ckan_config("api_token.jwt.encode.secret", None)
@pytest.mark.ckan_config("api_token.jwt.decode.secret", None)
def test_secrets_default_to_SECRET_KEY():
    assert _get_secret(True) == "super_secret"  # Encode
    assert _get_secret(False) == "super_secret"  # Decode


def _api_token_log_records(caplog):
    return [
        record for record in caplog.records
        if record.name == "ckan.lib.api_token"
    ]


def test_invalid_token_is_logged_as_warning_without_token_value(caplog):
    token = "not-a-jwt-token"
    caplog.set_level(logging.WARNING, logger="ckan.lib.api_token")

    assert api_token.decode(token) is None

    records = _api_token_log_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "Rejected invalid API token" in records[0].message
    assert "reason=Not enough segments" in records[0].message
    assert "dot_count=0" in records[0].message
    assert "auth_scheme=raw" in records[0].message
    assert token not in records[0].message


def test_invalid_token_request_log_includes_safe_request_context(
        test_request_context, caplog):
    token = "Bearer not-a-jwt-token"
    caplog.set_level(logging.WARNING, logger="ckan.lib.api_token")

    with test_request_context(
        "/",
        headers={
            "X-Forwarded-For": "203.0.113.10",
        },
    ):
        assert api_token.decode(token) is None

    records = _api_token_log_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "Rejected invalid API token" in records[0].message
    assert "reason=Not enough segments" in records[0].message
    assert "auth_scheme=bearer" in records[0].message
    assert "method=GET" in records[0].message
    assert "path=/" in records[0].message
    assert "remote_addr=" in records[0].message
    assert "x_forwarded_for='203.0.113.10'" in records[0].message
    assert token not in records[0].message


def test_invalid_token_context_logging_failure_does_not_raise(
        monkeypatch, caplog):
    token = "not-a-jwt-token"
    caplog.set_level(logging.WARNING, logger="ckan.lib.api_token")

    def raise_error():
        raise RuntimeError("broken request context")

    monkeypatch.setattr(api_token, "has_request_context", raise_error)

    assert api_token.decode(token) is None

    records = _api_token_log_records(caplog)
    assert len(records) == 1
    assert "Rejected invalid API token" in records[0].message
    assert "context_error=RuntimeError" in records[0].message
    assert token not in records[0].message
