import logging

from ckan.common import current_user
from ckan.plugins import toolkit

log = logging.getLogger(__name__)


def user_can_access_hvd_validator(user=None):
    """Allow sysadmins and users with any role in at least one organization."""
    if user is None:
        user = current_user

    if not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "sysadmin", False):
        return True

    user_id = getattr(user, "id", None)
    user_name = getattr(user, "name", None)
    if not user_id and not user_name:
        return False

    context = {
        "user": user_name,
        "auth_user_obj": user,
    }
    data_dict = {
        "id": user_id or user_name,
        "permission": "read",
    }

    try:
        organizations = toolkit.get_action("organization_list_for_user")(
            context,
            data_dict,
        )
    except Exception as exc:
        log.warning("Could not check HVD validator organization access: %s", exc)
        return False

    return bool(organizations)
