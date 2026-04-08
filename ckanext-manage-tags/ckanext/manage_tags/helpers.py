from __future__ import annotations

from typing import Any

import ckan.model as model
from ckan.common import _
import sqlalchemy as sa


_TYPE_LABELS = {
    'dataset': _('Dataset'),
    'data-service': _('Data Service'),
    'decision': _('Decision'),
}


def type_label(package_type: str | None) -> str:
    normalized_type = package_type or 'dataset'
    return _TYPE_LABELS.get(normalized_type, normalized_type)


def _package_data(package) -> dict[str, str]:
    package_type = package.type or 'dataset'
    return {
        'id': package.id,
        'name': package.name,
        'title': package.title or package.name,
        'type': package_type,
        'type_label': type_label(package_type),
    }


def _active_packages_query(tag_id: str):
    return (
        model.Session.query(model.Package)
        .join(model.PackageTag, model.PackageTag.package_id == model.Package.id)
        .filter(model.PackageTag.tag_id == tag_id)
        .filter(model.PackageTag.state == 'active')
        .filter(model.Package.state == 'active')
        .order_by(model.Package.name.asc())
    )


def _tag_data(
    tag,
    package_limit: int | None = None,
    package_offset: int = 0,
) -> dict[str, Any]:
    packages_query = _active_packages_query(tag.id)
    usage_count = packages_query.count()

    package_rows = packages_query.offset(package_offset)
    if package_limit is not None:
        package_rows = package_rows.limit(package_limit)
    packages = [_package_data(package) for package in package_rows.all()]

    package_type_rows = (
        model.Session.query(model.Package.type)
        .join(model.PackageTag, model.PackageTag.package_id == model.Package.id)
        .filter(model.PackageTag.tag_id == tag.id)
        .filter(model.PackageTag.state == 'active')
        .filter(model.Package.state == 'active')
        .distinct()
        .all()
    )
    package_types = sorted({(package_type or 'dataset') for package_type, in package_type_rows})
    return {
        'id': tag.id,
        'name': tag.name,
        'usage_count': usage_count,
        'package_types': package_types,
        'package_type_labels': [type_label(package_type) for package_type in package_types],
        'package_types_display': ', '.join(
            type_label(package_type) for package_type in package_types
        ),
        'packages': packages,
    }


def get_free_tags(
    query: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    usage_count = sa.func.count(sa.distinct(model.Package.id))
    tag_query = (
        model.Session.query(
            model.Tag.id,
            model.Tag.name,
            usage_count.label('usage_count'),
        )
        .join(model.PackageTag, model.PackageTag.tag_id == model.Tag.id)
        .join(model.Package, model.Package.id == model.PackageTag.package_id)
        .filter(model.Tag.vocabulary_id.is_(None))
        .filter(model.PackageTag.state == 'active')
        .filter(model.Package.state == 'active')
        .group_by(model.Tag.id, model.Tag.name)
    )

    if query:
        tag_query = tag_query.filter(model.Tag.name.ilike(u'%{}%'.format(query)))

    total_count = model.Session.query(sa.func.count()).select_from(
        tag_query.subquery()
    ).scalar() or 0

    tag_rows = (
        tag_query
        .order_by(usage_count.desc(), model.Tag.name.asc())
        .offset(offset)
    )
    if limit is not None:
        tag_rows = tag_rows.limit(limit)

    rows = tag_rows.all()
    if not rows:
        return [], total_count

    tag_ids = [row.id for row in rows]
    package_type_rows = (
        model.Session.query(
            model.PackageTag.tag_id,
            model.Package.type,
        )
        .join(model.Package, model.Package.id == model.PackageTag.package_id)
        .filter(model.PackageTag.tag_id.in_(tag_ids))
        .filter(model.PackageTag.state == 'active')
        .filter(model.Package.state == 'active')
        .distinct()
        .all()
    )

    package_types_by_tag: dict[str, set[str]] = {tag_id: set() for tag_id in tag_ids}
    for tag_id, package_type in package_type_rows:
        package_types_by_tag.setdefault(tag_id, set()).add(package_type or 'dataset')

    result = []
    for row in rows:
        package_types = sorted(package_types_by_tag.get(row.id, set()))
        result.append({
            'id': row.id,
            'name': row.name,
            'usage_count': row.usage_count,
            'package_types': package_types,
            'package_type_labels': [
                type_label(package_type) for package_type in package_types
            ],
            'package_types_display': ', '.join(
                type_label(package_type) for package_type in package_types
            ),
        })

    return result, total_count


def get_manageable_tag_data(
    tag_id: str,
    package_limit: int | None = None,
    package_offset: int = 0,
) -> dict[str, Any] | None:
    tag = model.Tag.by_id(tag_id, autoflush=False)
    if not tag or tag.vocabulary_id is not None:
        return None
    return _tag_data(tag, package_limit=package_limit, package_offset=package_offset)
