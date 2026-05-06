from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Sequence

import sqlalchemy
from sqlalchemy import func

from ckan import model
import ckan.plugins.toolkit as toolkit


log = logging.getLogger(__name__)

ORGANIZATION_VISITS_SORT_ENABLED_CONFIG = (
    "ckanext.data_gov_gr.organization_index.visits_sort.enabled"
)
ORGANIZATION_VISITS_SORT_DEFAULT_CONFIG = (
    "ckanext.data_gov_gr.organization_index.visits_sort.default"
)

_ORGANIZATION_PROFILE_URL_FILTERS = (
    r"^/organization/[^/]+$",
    r"^/[a-z]{2}/organization/[^/]+$",
    r"^/organization/about/[^/]+$",
    r"^/[a-z]{2}/organization/about/[^/]+$",
)
_RESERVED_ORGANIZATION_NAMES = {
    "new",
    "edit",
    "activity",
    "about",
    "manage_members",
    "members",
    "member_new",
    "delete",
    "bulk_process",
}


def organization_profile_visit_sort_enabled() -> bool:
    return _config_as_bool(ORGANIZATION_VISITS_SORT_ENABLED_CONFIG, False)


def organization_profile_visit_sort_default_enabled() -> bool:
    return (
        organization_profile_visit_sort_enabled()
        and _config_as_bool(ORGANIZATION_VISITS_SORT_DEFAULT_CONFIG, False)
    )


def _config_as_bool(key: str, default: bool = False) -> bool:
    value = toolkit.config.get(key, default)
    if isinstance(value, list):
        value = value[-1] if value else default
    try:
        return toolkit.asbool(value)
    except Exception:
        log.warning("Invalid boolean config %s=%r, using default=%r", key, value, default)
        return default


class CountOnlySequence(Sequence[None]):
    def __init__(self, total_count: int):
        self.total_count = max(0, int(total_count or 0))

    def __len__(self) -> int:
        return self.total_count

    def __getitem__(self, index: int | slice) -> None | list[None]:
        if isinstance(index, slice):
            start, stop, step = index.indices(self.total_count)
            return [None] * len(range(start, stop, step))

        if index < 0:
            index += self.total_count
        if index < 0 or index >= self.total_count:
            raise IndexError(index)
        return None


def normalize_org_ids(org_ids: Iterable[object] | None) -> list[str]:
    normalized_org_ids: list[str] = []
    seen: set[str] = set()

    for org_id in org_ids or []:
        normalized = str(org_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_org_ids.append(normalized)

    return normalized_org_ids


def _build_public_owner_org_fq(org_ids: Iterable[object] | None,
                               dataset_type: str) -> str:
    normalized_org_ids = normalize_org_ids(org_ids)
    owner_org_filter = ""
    if normalized_org_ids:
        owner_filter = " OR ".join([f'"{org_id}"' for org_id in normalized_org_ids])
        owner_org_filter = f" +owner_org:({owner_filter})"

    return (
        f"+dataset_type:{dataset_type} "
        "+state:active +private:false"
        f"{owner_org_filter}"
    )


def get_public_owner_org_facet_items(
        dataset_type: str,
        org_ids: Iterable[object] | None = None,
        facet_limit: int = -1) -> list[dict[str, Any]]:
    fq = _build_public_owner_org_fq(org_ids, dataset_type)
    try:
        response = toolkit.get_action("package_search")(
            {"ignore_auth": True},
            {
                "q": "*:*",
                "fq": fq,
                "rows": 0,
                "facet": True,
                "facet.field": ["owner_org"],
                "facet.limit": facet_limit,
                "facet.mincount": 1,
            },
        )
        return (
            (((response.get("search_facets") or {}).get("owner_org") or {}).get("items"))
            or []
        )
    except Exception as exc:
        log.error(
            "Error loading %s owner_org facets for organization index: %s",
            dataset_type,
            exc,
        )
        return []


def get_public_owner_org_counts(org_ids: Iterable[object] | None,
                                dataset_type: str) -> dict[str, int]:
    normalized_org_ids = normalize_org_ids(org_ids)
    counts = {org_id: 0 for org_id in normalized_org_ids}
    if not normalized_org_ids:
        return counts

    for item in get_public_owner_org_facet_items(dataset_type, normalized_org_ids):
        item = item or {}
        org_id = item.get("name")
        if org_id in counts:
            counts[org_id] = int(item.get("count") or 0)
    return counts


def get_public_dataset_counts_for_orgs(
        org_ids: Iterable[object] | None) -> dict[str, int]:
    return get_public_owner_org_counts(org_ids, "dataset")


def get_public_dataset_facet_items(
        facet_limit: int = -1) -> list[dict[str, Any]]:
    return get_public_owner_org_facet_items(
        "dataset",
        facet_limit=facet_limit,
    )


def get_public_data_service_counts_for_orgs(
        org_ids: Iterable[object] | None) -> dict[str, int]:
    return get_public_owner_org_counts(org_ids, "data-service")


def _tracking_raw_model():
    try:
        from ckanext.tracking.model import TrackingRaw
    except Exception as exc:
        log.warning("CKAN tracking is unavailable for organization visits: %s", exc)
        return None
    return TrackingRaw


def _tracking_locales() -> list[str]:
    locales: list[str] = []
    for config_key in (
        "ckan.locales_offered",
        "ckan.locale_default",
        "locale_default",
        "default_locale",
    ):
        for locale in toolkit.aslist(toolkit.config.get(config_key)):
            locale = str(locale or "").strip().lower()
            if locale and "/" not in locale and locale not in locales:
                locales.append(locale)
    return locales


def _tracking_root_path_prefixes() -> list[str]:
    root_path = str(toolkit.config.get("ckan.root_path", "") or "").strip()
    if not root_path:
        return []

    prefixes: list[str] = []

    default_prefix = re.sub(r"/\{\{LANG\}\}", "", root_path)
    prefixes.append(default_prefix)

    for locale in _tracking_locales():
        prefixes.append(root_path.replace("{{LANG}}", locale))

    normalized_prefixes: list[str] = []
    for prefix in prefixes:
        prefix = prefix.rstrip("/")
        if prefix and prefix != "/" and prefix not in normalized_prefixes:
            normalized_prefixes.append(prefix)

    return sorted(normalized_prefixes, key=len, reverse=True)


def _tracking_root_path_prefix_pattern() -> str:
    prefixes = _tracking_root_path_prefixes()
    if not prefixes:
        return ""
    # PostgreSQL uses POSIX-style regexes (no non-capturing groups), so avoid
    # constructs like (?:...).
    return "^({})".format("|".join(re.escape(prefix) for prefix in prefixes))


def _tracking_url_without_root_path(url_column: Any) -> Any:
    root_path_pattern = _tracking_root_path_prefix_pattern()
    if not root_path_pattern:
        return url_column
    return func.regexp_replace(url_column, root_path_pattern, "")


def _organization_profile_tracking_urls(org_names: Iterable[object]) -> set[str]:
    urls: set[str] = set()
    prefixes = [""] + _tracking_root_path_prefixes()
    locales = _tracking_locales()

    for org_name in normalize_org_ids(org_names):
        paths = [
            f"/organization/{org_name}",
            f"/organization/about/{org_name}",
        ]
        for locale in locales:
            paths.extend([
                f"/{locale}/organization/{org_name}",
                f"/{locale}/organization/about/{org_name}",
            ])

        for prefix in prefixes:
            urls.update(f"{prefix}{path}" for path in paths)

    return urls


def _organization_name_from_tracking_url(url_column: Any) -> Any:
    without_locale_about = func.regexp_replace(
        url_column,
        r"^/[a-z]{2}/organization/about/",
        "",
    )
    without_about = func.regexp_replace(
        without_locale_about,
        r"^/organization/about/",
        "",
    )
    without_locale = func.regexp_replace(
        without_about,
        r"^/[a-z]{2}/organization/",
        "",
    )
    return func.regexp_replace(
        without_locale,
        r"^/organization/",
        "",
    )


def get_organization_profile_visit_counts_for_org_names(
        org_names: Iterable[object] | None = None) -> dict[str, int]:
    """Return public organization profile visits from CKAN tracking_raw.

    Counts follow CKAN tracking's summary semantics: one view per
    URL/user/day. Only public organization profile URLs are included.
    """
    scoped_to_org_names = org_names is not None
    normalized_org_names = normalize_org_ids(org_names)
    if scoped_to_org_names and not normalized_org_names:
        return {}

    TrackingRaw = _tracking_raw_model()
    if TrackingRaw is None:
        return {}

    tracking_url_expr = _tracking_url_without_root_path(TrackingRaw.url)
    org_name_expr = _organization_name_from_tracking_url(tracking_url_expr)
    visit_date_expr = sqlalchemy.cast(
        TrackingRaw.access_timestamp,
        sqlalchemy.Date,
    ).label("visit_date")

    try:
        distinct_visits = (
            model.Session.query(
                org_name_expr.label("org_name"),
                tracking_url_expr.label("url"),
                TrackingRaw.user_key.label("user_key"),
                visit_date_expr,
            )
            .filter(TrackingRaw.tracking_type == "page")
            .filter(~org_name_expr.in_(_RESERVED_ORGANIZATION_NAMES))
        )
        if scoped_to_org_names:
            distinct_visits = distinct_visits.filter(
                TrackingRaw.url.in_(
                    _organization_profile_tracking_urls(normalized_org_names)
                )
            )
            distinct_visits = distinct_visits.filter(
                org_name_expr.in_(normalized_org_names)
            )
        else:
            url_filters = [
                tracking_url_expr.op("~")(pattern)
                for pattern in _ORGANIZATION_PROFILE_URL_FILTERS
            ]
            distinct_visits = distinct_visits.filter(sqlalchemy.or_(*url_filters))

        distinct_visits = distinct_visits.distinct().subquery()
        rows = (
            model.Session.query(
                distinct_visits.c.org_name,
                func.count().label("visit_count"),
            )
            .group_by(distinct_visits.c.org_name)
            .all()
        )
    except Exception as exc:
        model.Session.rollback()
        log.error("Error loading organization profile visit counts: %s", exc)
        return {}

    counts = {
        str(row.org_name): int(row.visit_count or 0)
        for row in rows
        if row.org_name
    }

    if normalized_org_names:
        return {
            org_name: counts.get(org_name, 0)
            for org_name in normalized_org_names
        }
    return counts


def organization_profile_visit_sort_available() -> bool:
    TrackingRaw = _tracking_raw_model()
    if TrackingRaw is None:
        return False

    tracking_url_expr = _tracking_url_without_root_path(TrackingRaw.url)
    org_name_expr = _organization_name_from_tracking_url(tracking_url_expr)
    try:
        url_filters = [
            tracking_url_expr.op("~")(pattern)
            for pattern in _ORGANIZATION_PROFILE_URL_FILTERS
        ]
        row = (
            model.Session.query(TrackingRaw.url)
            .join(
                model.Group,
                sqlalchemy.and_(
                    model.Group.name == org_name_expr,
                    model.Group.is_organization.is_(True),
                    model.Group.state == "active",
                ),
            )
            .filter(TrackingRaw.tracking_type == "page")
            .filter(sqlalchemy.or_(*url_filters))
            .filter(~org_name_expr.in_(_RESERVED_ORGANIZATION_NAMES))
            .first()
        )
        return row is not None
    except Exception as exc:
        model.Session.rollback()
        log.error("Error checking organization profile visits: %s", exc)
        return False
