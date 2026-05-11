from __future__ import annotations

import copy
import json
from typing import Any

import ckan.plugins.toolkit as toolkit


HVD_APPLICABLE_LEGISLATION_CONFIG = (
    'ckanext.data_gov_gr.hvd.applicable_legislation.default'
)
HVD_CATEGORY_NOTICE_URL_CONFIG = (
    'ckanext.data_gov_gr.hvd.category_notice.url'
)
DEFAULT_HVD_APPLICABLE_LEGISLATION = (
    'http://data.europa.eu/eli/reg_impl/2023/138/oj'
)

APPLICABLE_LEGISLATION_FIELD = 'applicable_legislation'
HVD_CATEGORY_FIELD = 'hvd_category'
HVD_CATEGORY_FORM_PRESENT_FIELD = '_data_gov_gr_hvd_category_form_present'
HVD_PACKAGE_TYPES = {'dataset', 'data-service'}


def _normalize_string(value: Any, default: str = '') -> str:
    if value is None:
        return default
    if isinstance(value, list):
        if not value:
            return default
        value = value[-1]
    try:
        value = str(value).strip()
    except Exception:
        return default
    return value if value else default


def get_hvd_applicable_legislation_default() -> str:
    value = toolkit.config.get(HVD_APPLICABLE_LEGISLATION_CONFIG)
    return _normalize_string(value, DEFAULT_HVD_APPLICABLE_LEGISLATION)


def get_hvd_category_notice_url() -> str:
    value = toolkit.config.get(HVD_CATEGORY_NOTICE_URL_CONFIG)
    return _normalize_string(value, get_hvd_applicable_legislation_default())


def _list_from_value(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            return _list_from_value(parsed)
        if parsed in (None, '') and value in {'null', '[]'}:
            return []
        return [value]

    if not isinstance(value, (list, tuple, set)):
        return []

    values: list[str] = []
    for item in value:
        normalized = _normalize_string(item)
        if normalized:
            values.append(normalized)
    return _dedupe(values)


def normalize_value_list(value: Any) -> list[str]:
    return _list_from_value(value)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def has_hvd_category(value: Any) -> bool:
    return bool(_list_from_value(value))


def _effective_value(
    target: dict[str, Any],
    current: dict[str, Any] | None,
    key: str,
) -> Any:
    if key in target:
        return target.get(key)
    if current and key in current:
        return current.get(key)
    return None


def _sync_applicable_legislation(
    target: dict[str, Any],
    *,
    has_hvd: bool,
    legislation_value: str,
    current: dict[str, Any] | None = None,
) -> None:
    existing_value = _effective_value(target, current, APPLICABLE_LEGISLATION_FIELD)
    values = _list_from_value(existing_value)
    values = [value for value in values if value != legislation_value]

    if has_hvd:
        values.insert(0, legislation_value)

    target[APPLICABLE_LEGISLATION_FIELD] = _dedupe(values)


def _resources_by_id(package_dict: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    resources_by_id: dict[str, dict[str, Any]] = {}
    if not package_dict:
        return resources_by_id

    for resource in package_dict.get('resources') or []:
        if not isinstance(resource, dict):
            continue
        resource_id = resource.get('id')
        if resource_id:
            resources_by_id[str(resource_id)] = resource
    return resources_by_id


def sync_package_hvd_applicable_legislation(
    package_dict: dict[str, Any],
    *,
    current_package: dict[str, Any] | None = None,
    legislation_value: str | None = None,
    missing_hvd_category_means_removed: bool = False,
) -> None:
    """
    Κρατά την παραμετρική HVD εφαρμοστέα νομοθεσία υπό έλεγχο συστήματος.

    Αν το package έχει HVD categories, προσθέτει το παραμετρικό URL στο
    ``applicable_legislation`` του package/resource χωρίς να αφαιρεί άλλες
    τιμές του χρήστη. Αν αφαιρεθούν οι HVD categories, αφαιρείται ξανά το
    παραμετρικό HVD URL.
    """
    if not isinstance(package_dict, dict):
        return

    package_type = _effective_value(package_dict, current_package, 'type')
    if not package_type and current_package is None:
        package_type = 'dataset'
    if package_type not in HVD_PACKAGE_TYPES:
        return

    if legislation_value is None:
        legislation_value = get_hvd_applicable_legislation_default()
    legislation_value = _normalize_string(legislation_value)
    if not legislation_value:
        return

    had_hvd = False
    if current_package:
        had_hvd = has_hvd_category(current_package.get(HVD_CATEGORY_FIELD))

    # Μόνο η φόρμα δίνει ρητό marker ότι το HVD category select υπήρχε αλλά
    # άδειασε.
    if (
        missing_hvd_category_means_removed
        and current_package
        and had_hvd
        and HVD_CATEGORY_FIELD not in package_dict
    ):
        package_dict[HVD_CATEGORY_FIELD] = []

    has_hvd = has_hvd_category(
        _effective_value(package_dict, current_package, HVD_CATEGORY_FIELD)
    )

    if not has_hvd and not had_hvd:
        return

    _sync_applicable_legislation(
        package_dict,
        has_hvd=has_hvd,
        legislation_value=legislation_value,
        current=current_package,
    )

    # Το resource-level applicable_legislation υπάρχει στο κανονικό dataset
    # schema. Τα data-service resources έχουν ελάχιστο schema και δεν τα
    # πειράζουμε.
    if package_type != 'dataset':
        return

    resources = package_dict.get('resources')
    if resources is None and current_package and HVD_CATEGORY_FIELD in package_dict:
        resources = copy.deepcopy(current_package.get('resources') or [])
        package_dict['resources'] = resources

    if not isinstance(resources, list):
        return

    current_resources = _resources_by_id(current_package)
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        current_resource = None
        resource_id = resource.get('id')
        if resource_id:
            current_resource = current_resources.get(str(resource_id))
        _sync_applicable_legislation(
            resource,
            has_hvd=has_hvd,
            legislation_value=legislation_value,
            current=current_resource,
        )
