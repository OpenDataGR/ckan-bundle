from unittest.mock import Mock

import pytest
import requests

import ckanext.azure_translator.plugin as plugin


@pytest.fixture
def translator_config(monkeypatch):
    monkeypatch.setitem(
        plugin.toolkit.config,
        "azure.translate.subscription_key",
        "test-subscription-key",
    )
    monkeypatch.setitem(
        plugin.toolkit.config,
        "azure.translate.endpoint",
        "https://api.cognitive.microsofttranslator.com",
    )
    monkeypatch.setitem(
        plugin.toolkit.config,
        "azure.translate.region",
        "westeurope",
    )


def test_translation_uses_tls_verification(monkeypatch, translator_config):
    response = Mock()
    response.json.return_value = [
        {"translations": [{"text": "Open data", "to": "en"}]}
    ]
    post = Mock(return_value=response)
    monkeypatch.setattr(plugin.requests, "post", post)

    result = plugin.AzureTranslatorPlugin.azure_translate("Ανοικτά δεδομένα")

    assert result == [{"translations": [{"text": "Open data", "to": "en"}]}]
    post.assert_called_once()
    url = post.call_args.args[0]
    kwargs = post.call_args.kwargs
    assert url == (
        "https://api.cognitive.microsofttranslator.com/translate"
        "?api-version=3.0&to=en"
    )
    assert kwargs["verify"] is True
    assert kwargs["timeout"] == (5, 30)
    assert (
        kwargs["headers"]["Ocp-Apim-Subscription-Key"]
        == "test-subscription-key"
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api.cognitive.microsofttranslator.com",
        "api.cognitive.microsofttranslator.com",
        "https://user:password@example.com",
        "https://example.com?insecure=value",
        "https://example.com#fragment",
        "",
        None,
    ],
)
def test_translation_rejects_invalid_or_insecure_endpoint(
    monkeypatch, translator_config, endpoint
):
    monkeypatch.setitem(plugin.toolkit.config, "azure.translate.endpoint", endpoint)
    post = Mock()
    monkeypatch.setattr(plugin.requests, "post", post)

    with pytest.raises(RuntimeError, match="Azure Translator endpoint"):
        plugin.AzureTranslatorPlugin.azure_translate("Ανοικτά δεδομένα")

    post.assert_not_called()


def test_trailing_slash_is_normalized(monkeypatch, translator_config):
    monkeypatch.setitem(
        plugin.toolkit.config,
        "azure.translate.endpoint",
        "https://api.cognitive.microsofttranslator.com/",
    )
    response = Mock()
    response.json.return_value = []
    post = Mock(return_value=response)
    monkeypatch.setattr(plugin.requests, "post", post)

    plugin.AzureTranslatorPlugin.azure_translate("Ανοικτά δεδομένα")

    assert post.call_args.args[0].startswith(
        "https://api.cognitive.microsofttranslator.com/translate?"
    )


def test_certificate_error_fails_closed(monkeypatch, translator_config):
    post = Mock(
        side_effect=requests.exceptions.SSLError("certificate verify failed")
    )
    monkeypatch.setattr(plugin.requests, "post", post)

    with pytest.raises(RuntimeError, match="certificate verify failed"):
        plugin.AzureTranslatorPlugin.azure_translate("Ανοικτά δεδομένα")

    post.assert_called_once()
    assert post.call_args.kwargs["verify"] is True
