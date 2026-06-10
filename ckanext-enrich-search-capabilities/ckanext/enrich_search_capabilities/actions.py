import json
import math
from html.parser import HTMLParser

import sqlalchemy as sa

from ckan import model
from ckan.plugins import toolkit
from ckanext.pages.db import Page

from ckanext.enrich_search_capabilities.config import search_enabled


DEFAULT_ITEMS_PER_PAGE = 21
MAX_ITEMS_PER_PAGE = 100
MAX_QUERY_LENGTH = 200


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
        query = query.order_by(Page.publish_date.desc(), Page.created.desc())
    else:
        query = query.filter(
            sa.or_(Page.page_type == "page", Page.page_type.is_(None))
        )
        query = query.order_by(Page.created.desc())

    if search_term:
        pattern = f"%{_escape_like(search_term)}%"
        query = query.filter(
            sa.or_(
                Page.title.ilike(pattern, escape="\\"),
                Page.name.ilike(pattern, escape="\\"),
                Page.content.ilike(pattern, escape="\\"),
            )
        )

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
