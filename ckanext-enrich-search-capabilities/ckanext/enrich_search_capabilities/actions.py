import json
import math
from html.parser import HTMLParser

import sqlalchemy as sa

from ckan import model
from ckan.plugins import toolkit
from ckanext.pages.db import Page

from ckanext.enrich_search_capabilities.config import (
    dataset_live_search_enabled,
    dataset_live_search_limit,
    search_enabled,
)


DEFAULT_ITEMS_PER_PAGE = 21
MAX_ITEMS_PER_PAGE = 100
MAX_QUERY_LENGTH = 200

LIVE_SEARCH_MIN_QUERY_LENGTH = 2
LIVE_SEARCH_NOTES_LENGTH = 160

FUZZY_MIN_QUERY_LENGTH = 3
FUZZY_SIMILARITY_THRESHOLD = 0.5


class _FirstImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.first_image = None

    def handle_starttag(self, tag, attrs):
        if tag != "img" or self.first_image:
            return

        attributes = dict(attrs)
        self.first_image = attributes.get("src")


def _positive_integer(value, default, maximum=None):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default

    if value < 1:
        value = default
    if maximum is not None:
        value = min(value, maximum)
    return value


def _normalize_query(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise toolkit.ValidationError(
            {"q": [toolkit._("Search query must be text")]}
        )

    value = value.strip()
    if len(value) > MAX_QUERY_LENGTH:
        raise toolkit.ValidationError(
            {
                "q": [
                    toolkit._(
                        "Search query must not exceed {limit} characters"
                    ).format(limit=MAX_QUERY_LENGTH)
                ]
            }
        )
    return value


def _escape_like(value):
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _norm(expression):
    # Case-, accent- and final-sigma-insensitive comparison key; unaccent
    # does not fold ς to σ, hence the extra translate.
    return sa.func.translate(
        sa.func.unaccent(sa.func.lower(expression)), "ς", "σ"
    )


def _serialize_page(page):
    parser = _FirstImageParser()
    parser.feed(page.content or "")

    result = {
        "title": page.title,
        "content": page.content,
        "name": page.name,
        "publish_date": (
            page.publish_date.isoformat() if page.publish_date else None
        ),
        "group_id": page.group_id,
        "page_type": page.page_type,
        "private": page.private,
    }
    if parser.first_image:
        result["image"] = parser.first_image
    if page.extras:
        result.update(json.loads(page.extras))
    return result


@toolkit.side_effect_free
def enrich_pages_search(context, data_dict):
    if not search_enabled():
        raise toolkit.ValidationError(
            {"enabled": [toolkit._("Page and blog search is disabled")]}
        )

    toolkit.check_access("enrich_pages_search", context, data_dict)

    page_type = data_dict.get("page_type")
    if page_type not in ("page", "blog"):
        raise toolkit.ValidationError(
            {
                "page_type": [
                    toolkit._("Page type must be either page or blog")
                ]
            }
        )

    search_term = _normalize_query(data_dict.get("q"))
    page_number = _positive_integer(data_dict.get("page"), 1)
    items_per_page = _positive_integer(
        data_dict.get("items_per_page"),
        DEFAULT_ITEMS_PER_PAGE,
        MAX_ITEMS_PER_PAGE,
    )

    query = model.Session.query(Page).autoflush(False)
    query = query.filter(Page.group_id.is_(None))

    try:
        toolkit.check_access("ckanext_pages_update", context, {})
    except toolkit.NotAuthorized:
        query = query.filter(Page.private.is_(False))

    if page_type == "blog":
        query = query.filter(
            Page.page_type == "blog",
            Page.publish_date.isnot(None),
        )
        ordering = (Page.publish_date.desc(), Page.created.desc())
    else:
        query = query.filter(
            sa.or_(Page.page_type == "page", Page.page_type.is_(None))
        )
        ordering = (Page.created.desc(),)

    if search_term:
        pattern = _norm(f"%{_escape_like(search_term)}%")
        base_like = sa.or_(
            _norm(Page.title).like(pattern, escape="\\"),
            _norm(Page.name).like(pattern, escape="\\"),
            _norm(Page.content).like(pattern, escape="\\"),
        )

        if len(search_term) >= FUZZY_MIN_QUERY_LENGTH:
            # word_similarity(needle, haystack): the query term must be the
            # first argument, the column the second.
            normalized_term = _norm(search_term)
            score_title = sa.func.word_similarity(
                normalized_term, _norm(Page.title)
            )
            score_name = sa.func.word_similarity(
                normalized_term, _norm(Page.name)
            )
            score_content = sa.func.word_similarity(
                normalized_term, _norm(Page.content)
            )
            query = query.filter(
                sa.or_(
                    base_like,
                    score_title > FUZZY_SIMILARITY_THRESHOLD,
                    score_name > FUZZY_SIMILARITY_THRESHOLD,
                    score_content > FUZZY_SIMILARITY_THRESHOLD,
                )
            )
            ordering = (
                sa.desc(
                    sa.func.greatest(
                        score_title * 1.2,
                        score_name * 1.0,
                        score_content * 0.8,
                    )
                ),
            ) + ordering
        else:
            query = query.filter(base_like)

    query = query.order_by(*ordering)

    total = query.order_by(None).count()
    if total:
        last_page = int(math.ceil(total / float(items_per_page)))
        page_number = min(page_number, last_page)
    offset = (page_number - 1) * items_per_page
    rows = query.offset(offset).limit(items_per_page).all()

    return {
        "items": [_serialize_page(row) for row in rows],
        "count": total,
        "page": page_number,
        "items_per_page": items_per_page,
        "q": search_term,
        "page_type": page_type,
    }


def _excerpt(text, maximum):
    text = " ".join((text or "").split())
    if len(text) <= maximum:
        return text
    return text[:maximum].rsplit(" ", 1)[0] + "…"


def _serialize_dataset(package):
    organization = package.get("organization") or {}
    return {
        "name": package.get("name"),
        "title": package.get("title") or package.get("name"),
        "notes": _excerpt(package.get("notes"), LIVE_SEARCH_NOTES_LENGTH),
        "organization": organization.get("title") or "",
    }


@toolkit.side_effect_free
def enrich_dataset_live_search(context, data_dict):
    if not dataset_live_search_enabled():
        raise toolkit.ValidationError(
            {"enabled": [toolkit._("Dataset live search is disabled")]}
        )

    toolkit.check_access("enrich_dataset_live_search", context, data_dict)

    search_term = _normalize_query(data_dict.get("q"))
    if len(search_term) < LIVE_SEARCH_MIN_QUERY_LENGTH:
        raise toolkit.ValidationError(
            {
                "q": [
                    toolkit._(
                        "Search query must be at least {limit} characters"
                    ).format(limit=LIVE_SEARCH_MIN_QUERY_LENGTH)
                ]
            }
        )

    configured_limit = dataset_live_search_limit()
    limit = _positive_integer(
        data_dict.get("limit"),
        configured_limit,
        configured_limit,
    )

    # The same query the dataset search page runs on submit: plain q,
    # default relevance sort, datasets only, no facets or extra filters.
    result = toolkit.get_action("package_search")(
        context,
        {
            "q": search_term,
            "fq": "+dataset_type:dataset",
            "rows": limit,
            "start": 0,
            "include_private": True,
        },
    )

    return {
        "items": [
            _serialize_dataset(package) for package in result["results"]
        ],
        "count": result["count"],
        "q": search_term,
        "limit": limit,
    }
