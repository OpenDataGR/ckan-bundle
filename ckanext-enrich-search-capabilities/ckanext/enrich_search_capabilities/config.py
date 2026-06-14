from ckan.plugins import toolkit


ENABLED_CONFIG = "ckanext.enrich_search_capabilities.enabled"
HEADER_SEARCH_ENABLED_CONFIG = (
    "ckanext.enrich_search_capabilities.header_search_enabled"
)
GUIDES_SEARCH_ENABLED_CONFIG = (
    "ckanext.enrich_search_capabilities.guides_search_enabled"
)
DATASET_LIVE_SEARCH_ENABLED_CONFIG = (
    "ckanext.enrich_search_capabilities.dataset_live_search_enabled"
)
DATASET_LIVE_SEARCH_LIMIT_CONFIG = (
    "ckanext.enrich_search_capabilities.dataset_live_search_limit"
)

LIVE_SEARCH_MAX_LIMIT = 10


def search_enabled():
    value = toolkit.config.get(ENABLED_CONFIG, False)
    if value == "":
        return False
    return toolkit.asbool(value)


def header_search_enabled():
    value = toolkit.config.get(HEADER_SEARCH_ENABLED_CONFIG, False)
    if value == "":
        return False
    return toolkit.asbool(value)


def guides_search_enabled():
    value = toolkit.config.get(GUIDES_SEARCH_ENABLED_CONFIG, False)
    if value == "":
        return False
    return toolkit.asbool(value)


def dataset_live_search_enabled():
    value = toolkit.config.get(DATASET_LIVE_SEARCH_ENABLED_CONFIG, False)
    if value == "":
        return False
    return toolkit.asbool(value)


def dataset_live_search_limit():
    value = toolkit.config.get(DATASET_LIVE_SEARCH_LIMIT_CONFIG)
    try:
        value = int(value)
    except (TypeError, ValueError):
        return LIVE_SEARCH_MAX_LIMIT
    if value < 1:
        return LIVE_SEARCH_MAX_LIMIT
    return min(value, LIVE_SEARCH_MAX_LIMIT)
