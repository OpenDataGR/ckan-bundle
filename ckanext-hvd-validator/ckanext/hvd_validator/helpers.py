import json
from urllib.parse import urlencode

from ckan.common import config, current_user
from ckan.plugins import toolkit

from ckanext.hvd_validator.auth import user_can_access_hvd_validator


DATASET_ACTION_ENABLED_CONFIG = "ckanext.hvd_validator.dataset_action.enabled"
HVD_CATEGORY_FIELD_CONFIG = "ckanext.hvd_validator.dataset_action.hvd_category_field"
PACKAGE_TYPES_CONFIG = "ckanext.hvd_validator.dataset_action.package_types"

DEFAULT_HVD_CATEGORY_FIELD = "hvd_category"
DEFAULT_PACKAGE_TYPES = ["dataset"]


def _has_value(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_value(item) for item in value)
    return bool(value)


def _has_hvd_category(value):
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return False
        try:
            decoded = json.loads(stripped)
        except ValueError:
            return True
        return _has_value(decoded)
    return _has_value(value)


def hvd_validator_dataset_action_enabled():
    return toolkit.asbool(config.get(DATASET_ACTION_ENABLED_CONFIG, True))


def hvd_validator_hvd_category_field():
    return config.get(HVD_CATEGORY_FIELD_CONFIG, DEFAULT_HVD_CATEGORY_FIELD)


def hvd_validator_dataset_action_package_types():
    return toolkit.aslist(config.get(PACKAGE_TYPES_CONFIG, DEFAULT_PACKAGE_TYPES))


def hvd_validator_package_has_hvd_category(pkg):
    if not pkg:
        return False
    return _has_hvd_category(pkg.get(hvd_validator_hvd_category_field()))


def hvd_validator_show_dataset_action(pkg):
    if not pkg or not hvd_validator_dataset_action_enabled():
        return False

    package_type = pkg.get("type") or "dataset"
    if package_type not in hvd_validator_dataset_action_package_types():
        return False

    if not hvd_validator_package_has_hvd_category(pkg):
        return False

    try:
        return user_can_access_hvd_validator(current_user)
    except Exception:
        return False


def hvd_validator_dataset_action_url(pkg):
    dataset_ref = (pkg or {}).get("name") or (pkg or {}).get("id")
    if not dataset_ref:
        return ""
    return "/hvd-validator?{params}".format(
        params=urlencode(
            {
                "input_mode": "name",
                "dataset_name": dataset_ref,
            }
        )
    )


def get_helpers():
    return {
        "hvd_validator_dataset_action_enabled": hvd_validator_dataset_action_enabled,
        "hvd_validator_hvd_category_field": hvd_validator_hvd_category_field,
        "hvd_validator_dataset_action_package_types": (
            hvd_validator_dataset_action_package_types
        ),
        "hvd_validator_package_has_hvd_category": hvd_validator_package_has_hvd_category,
        "hvd_validator_show_dataset_action": hvd_validator_show_dataset_action,
        "hvd_validator_dataset_action_url": hvd_validator_dataset_action_url,
    }
