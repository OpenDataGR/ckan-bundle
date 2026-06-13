import datetime

import pytest

from ckan.plugins import plugin_loaded, toolkit
from ckan.tests import factories, helpers

from ckanext.enrich_search_capabilities.config import (
    ENABLED_CONFIG,
    HEADER_SEARCH_ENABLED_CONFIG,
)
from ckanext.enrich_search_capabilities.helpers import header_search_targets


pytestmark = [
    pytest.mark.ckan_config(
        "ckan.plugins", "pages enrich_search_capabilities"
    ),
    pytest.mark.ckan_config(ENABLED_CONFIG, True),
    pytest.mark.ckan_config(HEADER_SEARCH_ENABLED_CONFIG, True),
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


def test_plugin_is_loaded():
    assert plugin_loaded("enrich_search_capabilities")


def test_header_search_targets_include_available_routes(monkeypatch):
    routes = {
        "dataset.search": "/dataset",
        "data-service.search": "/data-service",
        "showcase_blueprint.index": "/showcase",
        "organization.index": "/organization",
        "pages.pages_index": "/pages",
        "pages.blog_index": "/blog",
    }
    monkeypatch.setattr(
        toolkit,
        "url_for",
        lambda endpoint: routes[endpoint],
    )

    targets = header_search_targets()

    assert [target["url"] for target in targets] == list(routes.values())


def test_header_search_renders_destination_menu(app):
    response = app.get(
        toolkit.url_for("pages.pages_index"),
        status=200,
    )
    body = response.get_data(as_text=True)

    assert 'data-module="enrich-header-search"' in body
    assert 'name="q"' in body
    assert 'data-search-target="dataset.search"' in body
    assert 'data-search-target="organization.index"' in body
    assert 'data-search-target="pages.pages_index"' in body
    assert 'data-search-target="pages.blog_index"' in body


def test_searches_title_name_and_content_ordered_by_relevance(add_page):
    add_page(title="Open data guide", name="first", content="Other content")
    add_page(title="Second", name="open-data-policy", content="Other content")
    add_page(title="Third", name="third", content="<p>Open data content</p>")
    add_page(title="Unrelated", name="unrelated", content="Nothing relevant")

    text_result = _search(q="open data")
    name_result = _search(q="open-data")

    # Hyphens and spaces are equivalent word separators, so both queries
    # match all three pages; title matches rank above name above content.
    expected = ["first", "open-data-policy", "third"]
    assert text_result["count"] == 3
    assert [item["name"] for item in text_result["items"]] == expected
    assert [item["name"] for item in name_result["items"]] == expected


def test_search_ignores_case_accents_and_final_sigma(add_page):
    add_page(name="city-page", title="Η πόλη μας")
    add_page(name="reports-page", title="Νέες εκθέσεις")

    uppercase = _search(q="ΠΟΛΗ")
    unaccented = _search(q="πολη")
    final_sigma = _search(q="ΕΚΘΕΣΕΙΣ")

    assert [item["name"] for item in uppercase["items"]] == ["city-page"]
    assert [item["name"] for item in unaccented["items"]] == ["city-page"]
    assert [item["name"] for item in final_sigma["items"]] == [
        "reports-page"
    ]


def test_search_tolerates_small_typos(add_page):
    add_page(name="environment-page", title="Περιβαλλοντικά δεδομένα")
    add_page(name="finance-page", title="Οικονομικός απολογισμός")

    result = _search(q="περιβαλοντικα")

    assert [item["name"] for item in result["items"]] == ["environment-page"]


def test_search_ranks_title_matches_above_content_matches(add_page):
    add_page(name="title-match", title="Η πόλη μας")
    add_page(
        name="content-match",
        title="Άσχετος τίτλος",
        content="Η πόλη αναφέρεται μόνο στο περιεχόμενο",
    )

    result = _search(q="πόλη")

    # Without relevance ordering the newest page (content-match) would be
    # first.
    assert [item["name"] for item in result["items"]] == [
        "title-match",
        "content-match",
    ]


def test_only_returns_public_global_pages(add_page):
    add_page(name="public-page", title="Needle")
    add_page(name="private-page", title="Needle", private=True)
    add_page(name="organization-page", title="Needle", group_id="group-id")

    result = _search(q="Needle")

    assert [item["name"] for item in result["items"]] == ["public-page"]


def test_regular_authenticated_user_only_sees_public_pages(add_page):
    user = factories.User()
    add_page(name="public-page", title="Needle")
    add_page(name="private-page", title="Needle", private=True)

    result = _search({"user": user["name"]}, q="Needle")

    assert [item["name"] for item in result["items"]] == ["public-page"]


def test_sysadmin_sees_public_and_private_pages(add_page):
    sysadmin = factories.Sysadmin()
    add_page(name="public-page", title="Needle")
    add_page(name="private-page", title="Needle", private=True)

    result = _search({"user": sysadmin["name"]}, q="Needle")

    assert {item["name"] for item in result["items"]} == {
        "public-page",
        "private-page",
    }
    private_page = next(
        item for item in result["items"] if item["name"] == "private-page"
    )
    assert private_page["private"] is True


def test_separates_pages_and_blog_and_supports_legacy_page_type(add_page):
    add_page(name="page", title="Shared term", page_type="page")
    add_page(name="legacy-page", title="Shared term", page_type=None)
    add_page(
        name="blog",
        title="Shared term",
        page_type="blog",
        publish_date=datetime.datetime(2026, 1, 1),
    )

    pages = _search(q="Shared term", page_type="page")
    blog = _search(q="Shared term", page_type="blog")

    assert {item["name"] for item in pages["items"]} == {
        "page",
        "legacy-page",
    }
    assert [item["name"] for item in blog["items"]] == ["blog"]


def test_like_wildcards_are_literal(add_page):
    add_page(name="literal-percent", title="Discount 10%")
    add_page(name="without-percent", title="Discount ten percent")
    add_page(name="literal-underscore", title="Code A_B")

    percent = _search(q="%")
    underscore = _search(q="_")

    assert [item["name"] for item in percent["items"]] == ["literal-percent"]
    assert [item["name"] for item in underscore["items"]] == [
        "literal-underscore"
    ]


def test_sql_injection_payload_is_treated_as_text(add_page):
    add_page(name="still-present", title="Normal page")

    result = _search(q="' OR 1=1; DROP TABLE ckanext_pages; --")

    assert result["count"] == 0
    assert helpers.call_action(
        "enrich_pages_search", {}, page_type="page"
    )["count"] == 1


def test_rejects_invalid_inputs():
    with pytest.raises(toolkit.ValidationError):
        _search(q="x" * 201)

    with pytest.raises(toolkit.ValidationError):
        _search(page_type="invalid")


def test_database_pagination(add_page):
    for number in range(25):
        add_page(name=f"page-{number}", title="Paginated")

    first_page = _search(q="Paginated", page=1)
    second_page = _search(q="Paginated", page=2)

    assert first_page["count"] == 25
    assert len(first_page["items"]) == 21
    assert len(second_page["items"]) == 4


def test_pages_route_renders_search_results(app, add_page):
    add_page(name="visible-result", title="Unique public result")
    add_page(name="hidden-result", title="Unique public result", private=True)

    response = app.get(
        toolkit.url_for("pages.pages_index"),
        params={"q": "Unique public result"},
        status=200,
    )
    body = response.get_data(as_text=True)

    assert 'name="q"' in body
    assert "visible-result" in body
    assert "hidden-result" not in body
    assert "1 result found" in body


def test_sysadmin_route_renders_private_result_badge(app, add_page):
    sysadmin = factories.Sysadmin()
    add_page(name="private-result", title="Private searchable", private=True)

    response = app.get(
        toolkit.url_for("pages.pages_index"),
        params={"q": "Private searchable"},
        extra_environ={"REMOTE_USER": sysadmin["name"]},
        status=200,
    )
    body = response.get_data(as_text=True)

    assert "private-result" in body
    assert "label label-danger" in body
    assert "fa fa-lock" in body
    assert "Private" in body


def test_blog_route_only_renders_blog_results(app, add_page):
    add_page(name="ordinary-page", title="Shared route term")
    add_page(
        name="blog-result",
        title="Shared route term",
        page_type="blog",
        publish_date=datetime.datetime(2026, 1, 1),
    )

    response = app.get(
        toolkit.url_for("pages.blog_index"),
        params={"q": "Shared route term"},
        status=200,
    )
    body = response.get_data(as_text=True)

    assert "blog-result" in body
    assert "ordinary-page" not in body


def test_detail_routes_remain_owned_by_ckanext_pages(app, add_page):
    add_page(name="detail-page", title="Detail page")

    response = app.get(
        toolkit.url_for("pages.show", page="detail-page"),
        status=200,
    )

    assert "Detail page" in response.get_data(as_text=True)
