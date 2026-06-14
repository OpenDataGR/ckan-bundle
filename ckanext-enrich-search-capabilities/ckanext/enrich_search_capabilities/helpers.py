from werkzeug.routing import BuildError

from ckan.plugins import toolkit

from ckanext.enrich_search_capabilities.config import (
    dataset_live_search_enabled,
    dataset_live_search_limit,
    guides_search_enabled,
    header_search_enabled,
    search_enabled,
)


def _search_target(endpoint, label):
    try:
        url = toolkit.url_for(endpoint)
    except (BuildError, RuntimeError):
        return None
    return {
        "endpoint": endpoint,
        "label": label,
        "url": url,
    }


def header_search_targets():
    targets = [
        _search_target("dataset.search", toolkit._("Datasets")),
        _search_target("data-service.search", toolkit._("Data Services")),
        _search_target(
            "showcase_blueprint.index",
            toolkit._("Showcases"),
        ),
        _search_target(
            "organization.index",
            toolkit._("Organizations"),
        ),
    ]

    if search_enabled():
        targets.extend(
            [
                _search_target("pages.pages_index", toolkit._("Pages")),
                _search_target("pages.blog_index", toolkit._("Blog")),
            ]
        )

    if guides_search_enabled():
        targets.append(
            {
                "endpoint": None,
                "label": toolkit._("Guides"),
                "url": "https://data-gov-gr.gitbook.io/guides",
                "external": True,
            }
        )

    return [target for target in targets if target]


def get_helpers():
    return {
        "enrich_header_search_enabled": header_search_enabled,
        "enrich_header_search_targets": header_search_targets,
        "enrich_dataset_live_search_enabled": dataset_live_search_enabled,
        "enrich_dataset_live_search_limit": dataset_live_search_limit,
    }
