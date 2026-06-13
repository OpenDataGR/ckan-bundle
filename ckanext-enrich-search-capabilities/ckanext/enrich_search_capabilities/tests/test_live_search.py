import pytest

from ckan.plugins import toolkit
from ckan.tests import factories, helpers

from ckanext.enrich_search_capabilities.config import (
    DATASET_LIVE_SEARCH_ENABLED_CONFIG,
)


pytestmark = [
    pytest.mark.ckan_config(
        "ckan.plugins", "pages enrich_search_capabilities"
    ),
    pytest.mark.ckan_config(DATASET_LIVE_SEARCH_ENABLED_CONFIG, True),
    pytest.mark.usefixtures("with_plugins", "clean_db", "clean_index"),
]


def _live_search(context=None, **data):
    context = dict(context or {})
    context["ignore_auth"] = False
    return helpers.call_action("enrich_dataset_live_search", context, **data)


def test_returns_matching_datasets_with_trimmed_payload():
    organization = factories.Organization(title="Data Org")
    factories.Dataset(
        name="energy-prices",
        title="Energy prices",
        notes="Monthly energy prices",
        owner_org=organization["id"],
    )
    factories.Dataset(name="unrelated", title="Forests", notes="Trees")

    result = _live_search(q="energy")

    assert result["count"] == 1
    assert result["q"] == "energy"
    assert result["items"] == [
        {
            "name": "energy-prices",
            "title": "Energy prices",
            "notes": "Monthly energy prices",
            "organization": "Data Org",
        }
    ]


def test_only_returns_datasets_not_other_package_types():
    factories.Dataset(name="plain-dataset", title="Typed needle")
    factories.Dataset(
        name="data-service-result",
        title="Typed needle",
        type="data-service",
    )

    result = _live_search(q="typed needle")

    assert [item["name"] for item in result["items"]] == ["plain-dataset"]


def test_long_notes_are_excerpted():
    factories.Dataset(
        name="verbose",
        title="Verbose dataset",
        notes="word " * 100,
    )

    result = _live_search(q="verbose")

    notes = result["items"][0]["notes"]
    assert len(notes) <= 161
    assert notes.endswith("…")


def test_results_are_capped_at_ten():
    for number in range(12):
        factories.Dataset(name=f"capped-{number}", title=f"Capped {number}")

    result = _live_search(q="capped")
    explicit = _live_search(q="capped", limit=50)

    assert result["count"] == 12
    assert len(result["items"]) == 10
    assert len(explicit["items"]) == 10


def test_anonymous_users_do_not_see_private_datasets():
    user = factories.User()
    organization = factories.Organization(
        users=[{"name": user["name"], "capacity": "editor"}]
    )
    factories.Dataset(
        name="private-needle",
        title="Needle",
        owner_org=organization["id"],
        private=True,
    )
    factories.Dataset(name="public-needle", title="Needle")

    anonymous = _live_search(q="Needle")
    member = _live_search({"user": user["name"]}, q="Needle")

    assert [item["name"] for item in anonymous["items"]] == ["public-needle"]
    assert {item["name"] for item in member["items"]} == {
        "public-needle",
        "private-needle",
    }


def test_rejects_short_and_oversized_queries():
    with pytest.raises(toolkit.ValidationError):
        _live_search()

    with pytest.raises(toolkit.ValidationError):
        _live_search(q="x")

    with pytest.raises(toolkit.ValidationError):
        _live_search(q="x" * 201)


def test_action_is_available_over_get_api(app):
    factories.Dataset(name="api-dataset", title="Api dataset")

    response = app.get(
        "/api/3/action/enrich_dataset_live_search",
        params={"q": "api dataset"},
        status=200,
    )
    body = response.json

    assert body["success"] is True
    assert [item["name"] for item in body["result"]["items"]] == [
        "api-dataset"
    ]


def test_search_page_includes_live_search_module(app):
    response = app.get(toolkit.url_for("dataset.search"), status=200)
    body = response.get_data(as_text=True)

    assert 'data-module="enrich-dataset-live-search"' in body
    assert "dataset-live-search" in body
