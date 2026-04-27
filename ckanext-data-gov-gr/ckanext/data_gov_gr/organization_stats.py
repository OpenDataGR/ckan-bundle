from __future__ import annotations

import logging
from typing import Any, Iterable, Sequence

import ckan.plugins.toolkit as toolkit


log = logging.getLogger(__name__)


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
