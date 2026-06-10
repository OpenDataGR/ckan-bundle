from ckan.plugins import toolkit


ENABLED_CONFIG = "ckanext.enrich_search_capabilities.enabled"
HEADER_SEARCH_ENABLED_CONFIG = (
    "ckanext.enrich_search_capabilities.header_search_enabled"
)


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
