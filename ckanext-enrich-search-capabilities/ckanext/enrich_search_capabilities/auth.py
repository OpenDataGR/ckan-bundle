from ckan.plugins import toolkit


@toolkit.auth_allow_anonymous_access
def enrich_pages_search(context, data_dict):
    return {"success": True}
