from flask import Blueprint

import ckan.lib.helpers as helpers
from ckan.plugins import toolkit

from ckanext.enrich_search_capabilities.config import search_enabled


blueprint = Blueprint("enrich_search_capabilities", __name__)


def _render_index(page_type):
    search_term = toolkit.request.args.get("q", "")
    page_number = toolkit.request.args.get("page", 1)

    try:
        result = toolkit.get_action("enrich_pages_search")(
            {},
            {
                "q": search_term,
                "page": page_number,
                "page_type": page_type,
            },
        )
    except toolkit.ValidationError as error:
        toolkit.abort(400, error.error_summary)

    pagination = helpers.Page(
        collection=result["items"],
        page=result["page"],
        items_per_page=result["items_per_page"],
        item_count=result["count"],
        presliced_list=True,
        url=helpers.pager_url,
        q=result["q"],
    )

    template = (
        "enrich_search_capabilities/blog_list.html"
        if page_type == "blog"
        else "enrich_search_capabilities/pages_list.html"
    )
    return toolkit.render(
        template,
        extra_vars={
            "page": pagination,
            "q": result["q"],
            "result_count": result["count"],
        },
    )


@blueprint.before_app_request
def search_pages_indexes():
    if not search_enabled():
        return None

    if toolkit.request.endpoint == "pages.pages_index":
        return _render_index("page")
    if toolkit.request.endpoint == "pages.blog_index":
        return _render_index("blog")
    return None
