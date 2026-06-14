import pytest

from ckan.plugins import toolkit
from ckan.tests import factories, helpers

from ckanext.enrich_search_capabilities.config import (
    ENABLED_CONFIG,
    HEADER_SEARCH_ENABLED_CONFIG,
    dataset_live_search_enabled,
    header_search_enabled,
    search_enabled,
)
from ckanext.enrich_search_capabilities.helpers import header_search_targets


pytestmark = [
    pytest.mark.ckan_config(
        "ckan.plugins", "pages enrich_search_capabilities"
    ),
    pytest.mark.usefixtures("with_plugins", "clean_db"),
]


def _search(context=None, **data):
    context = dict(context or {})
    context["ignore_auth"] = False
    return helpers.call_action(
        "enrich_pages_search",
        context,
        page_type=data.pop("page_type", "page"),
        **data,
    )


def test_search_is_disabled_by_default():
    assert search_enabled() is False


def test_header_search_is_disabled_by_default():
    assert header_search_enabled() is False


def test_dataset_live_search_is_disabled_by_default():
    assert dataset_live_search_enabled() is False


def test_disabled_live_search_action_is_unavailable():
    with pytest.raises(toolkit.ValidationError) as error:
        helpers.call_action(
            "enrich_dataset_live_search",
            {"ignore_auth": False},
            q="anything",
        )

    assert error.value.error_summary["Enabled"] == (
        "Dataset live search is disabled"
    )


def test_disabled_live_search_page_has_no_module(app):
    response = app.get(toolkit.url_for("dataset.search"), status=200)
    body = response.get_data(as_text=True)

    assert 'data-module="enrich-dataset-live-search"' not in body


@pytest.mark.ckan_config(HEADER_SEARCH_ENABLED_CONFIG, True)
def test_header_search_config_can_enable_feature():
    assert header_search_enabled() is True


@pytest.mark.ckan_config(HEADER_SEARCH_ENABLED_CONFIG, False)
def test_header_search_can_be_disabled(app):
    response = app.get(
        toolkit.url_for("pages.pages_index"),
        status=200,
    )
    body = response.get_data(as_text=True)

    assert 'data-module="enrich-header-search"' not in body
    assert 'id="field-sitewide-search"' in body


def test_disabled_page_search_hides_page_and_blog_targets(monkeypatch):
    routes = {
        "dataset.search": "/dataset",
        "data-service.search": "/data-service",
        "showcase_blueprint.index": "/showcase",
        "organization.index": "/organization",
    }
    monkeypatch.setattr(
        toolkit,
        "url_for",
        lambda endpoint: routes[endpoint],
    )

    targets = header_search_targets()

    internal = [t for t in targets if not t.get("external")]
    assert [t["endpoint"] for t in internal] == list(routes)


@pytest.mark.ckan_config(ENABLED_CONFIG, False)
def test_disabled_search_action_is_unavailable():
    with pytest.raises(toolkit.ValidationError) as error:
        _search(q="anything")

    assert error.value.error_summary["Enabled"] == (
        "Page and blog search is disabled"
    )


@pytest.mark.ckan_config(ENABLED_CONFIG, False)
def test_disabled_search_restores_ckanext_pages_index(app, add_page):
    sysadmin = factories.Sysadmin()
    add_page(name="matching-page", title="Needle")
    add_page(name="unrelated-page", title="Unrelated")
    add_page(name="private-page", title="Private page", private=True)

    response = app.get(
        toolkit.url_for("pages.pages_index"),
        params={"q": "Needle"},
        extra_environ={"REMOTE_USER": sysadmin["name"]},
        status=200,
    )
    body = response.get_data(as_text=True)

    assert 'id="field-pages-search"' not in body
    assert "matching-page" in body
    assert "unrelated-page" in body
    assert "private-page" in body
    assert "label label-danger" not in body
