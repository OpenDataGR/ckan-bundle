import pytest

from ckan.logic.schema import update_configuration_schema
from ckan.plugins import toolkit
from ckan.tests import factories, helpers

from ckanext.enrich_search_capabilities.config import (
    DATASET_LIVE_SEARCH_ENABLED_CONFIG,
    DATASET_LIVE_SEARCH_LIMIT_CONFIG,
    dataset_live_search_limit,
)


pytestmark = [
    pytest.mark.ckan_config(
        "ckan.plugins", "pages enrich_search_capabilities"
    ),
    pytest.mark.ckan_config(DATASET_LIVE_SEARCH_ENABLED_CONFIG, True),
    pytest.mark.ckan_config(DATASET_LIVE_SEARCH_LIMIT_CONFIG, 4),
    pytest.mark.usefixtures("with_plugins", "clean_db", "clean_index"),
]


def _live_search(context=None, **data):
    context = dict(context or {})
    context["ignore_auth"] = False
    return helpers.call_action("enrich_dataset_live_search", context, **data)


def test_configured_limit_is_the_default():
    for number in range(6):
        factories.Dataset(name=f"limited-{number}", title=f"Limited {number}")

    result = _live_search(q="limited")

    assert result["count"] == 6
    assert result["limit"] == 4
    assert len(result["items"]) == 4


def test_explicit_limit_cannot_exceed_configured_limit():
    for number in range(6):
        factories.Dataset(name=f"capped-{number}", title=f"Capped {number}")

    result = _live_search(q="capped", limit=10)

    assert len(result["items"]) == 4


def test_explicit_limit_below_configured_limit_is_respected():
    for number in range(6):
        factories.Dataset(name=f"narrow-{number}", title=f"Narrow {number}")

    result = _live_search(q="narrow", limit=2)

    assert len(result["items"]) == 2


def test_search_page_passes_configured_limit_to_module(app):
    response = app.get(toolkit.url_for("dataset.search"), status=200)
    body = response.get_data(as_text=True)

    assert 'data-module-limit="4"' in body


@pytest.mark.parametrize(
    "value,valid",
    [
        ("", True),
        ("5", True),
        ("0", False),
        ("-3", False),
        ("abc", False),
    ],
)
def test_admin_schema_validates_limit_values(value, valid):
    schema = update_configuration_schema()

    data, errors = toolkit.navl_validate(
        {DATASET_LIVE_SEARCH_LIMIT_CONFIG: value}, schema, {}
    )

    assert bool(errors) is not valid
    if value == "":
        assert data[DATASET_LIVE_SEARCH_LIMIT_CONFIG] == ""


@pytest.mark.parametrize(
    "value,expected",
    [
        ("4", 4),
        ("10", 10),
        ("50", 10),
        ("0", 10),
        ("-3", 10),
        ("", 10),
        ("garbage", 10),
        (None, 10),
    ],
)
def test_configured_limit_is_clamped(ckan_config, monkeypatch, value, expected):
    if value is None:
        monkeypatch.delitem(
            ckan_config, DATASET_LIVE_SEARCH_LIMIT_CONFIG, raising=False
        )
    else:
        monkeypatch.setitem(
            ckan_config, DATASET_LIVE_SEARCH_LIMIT_CONFIG, value
        )

    assert dataset_live_search_limit() == expected
