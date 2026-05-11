from __future__ import annotations

import copy
import json
import logging
from datetime import datetime
from typing import Any, Iterable

import ckan.plugins.toolkit as toolkit
from ckan.model.system_info import set_system_info

from ckanext.data_gov_gr import helpers
from ckanext.data_gov_gr.logic import hvd_legislation

log = logging.getLogger(__name__)


def refresh_home_dataset_resources_snapshot() -> dict[str, object]:
    """
    Υπολογίζει και αποθηκεύει το snapshot του πλήθους των πόρων για την αρχική σελίδα.
    """
    count = helpers.count_home_dataset_resources()
    computed_at = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    payload = {
        'count': count,
        'computed_at': computed_at,
    }
    set_system_info(
        helpers.HOME_DATASET_RESOURCES_SNAPSHOT_KEY,
        json.dumps(payload, ensure_ascii=False),
    )
    log.info(
        'Stored homepage dataset resources snapshot: count=%s computed_at=%s',
        count,
        computed_at,
    )
    return payload


def _action_context() -> dict[str, Any]:
    context = {'ignore_auth': True}
    try:
        site_user = toolkit.get_action('get_site_user')(
            {'ignore_auth': True},
            {},
        )
        if site_user and site_user.get('name'):
            context['user'] = site_user['name']
    except Exception:
        pass
    return context


def _iter_package_refs(context: dict[str, Any], rows: int) -> Iterable[str]:
    start = 0
    rows = max(int(rows or 100), 1)
    package_search = toolkit.get_action('package_search')

    while True:
        result = package_search(toolkit.fresh_context(context), {
            'q': '*:*',
            'fq': 'is_hvd:Yes',
            'start': start,
            'rows': rows,
            'include_private': True,
        })
        results = result.get('results') or []
        if not results:
            return

        for package in results:
            package_ref = package.get('id') or package.get('name')
            if package_ref:
                yield package_ref

        start += len(results)
        if start >= result.get('count', 0):
            return


def _legislation_state(package_dict: dict[str, Any]) -> dict[str, Any]:
    resources = []
    for resource in package_dict.get('resources') or []:
        if not isinstance(resource, dict):
            continue
        resources.append((
            resource.get('id') or resource.get('name'),
            hvd_legislation.normalize_value_list(
                resource.get(hvd_legislation.APPLICABLE_LEGISLATION_FIELD)
            ),
        ))

    return {
        'package': hvd_legislation.normalize_value_list(
            package_dict.get(hvd_legislation.APPLICABLE_LEGISLATION_FIELD)
        ),
        'resources': resources,
    }


def _package_label(package_dict: dict[str, Any]) -> str:
    return (
        package_dict.get('name')
        or package_dict.get('title')
        or package_dict.get('id')
        or '<unknown>'
    )


def backfill_hvd_applicable_legislation(
    *,
    apply_changes: bool = False,
    package_ids: Iterable[str] | None = None,
    limit: int | None = None,
    rows: int = 100,
) -> dict[str, Any]:
    """
    Συγχρονίζει την HVD εφαρμοστέα νομοθεσία σε υπάρχοντα HVD datasets/services.

    Από προεπιλογή εκτελεί dry-run. Με ``apply_changes=True`` γράφει μέσω
    ``package_update`` ώστε να χρησιμοποιηθεί το ίδιο validation/action flow
    με τις φόρμες, το API και τους harvesters.
    """
    context = _action_context()
    package_refs = list(package_ids or []) or _iter_package_refs(context, rows)
    package_show = toolkit.get_action('package_show')
    package_update = toolkit.get_action('package_update')

    stats: dict[str, Any] = {
        'dry_run': not apply_changes,
        'checked': 0,
        'hvd': 0,
        'changed': 0,
        'updated': 0,
        'unchanged': 0,
        'skipped': 0,
        'failed': 0,
        'changes': [],
        'errors': [],
    }

    processed_hvd = 0
    for package_ref in package_refs:
        try:
            package_dict = package_show(
                toolkit.fresh_context(context),
                {'id': package_ref},
            )
            stats['checked'] += 1

            if package_dict.get('type') not in hvd_legislation.HVD_PACKAGE_TYPES:
                stats['skipped'] += 1
                continue
            if not hvd_legislation.has_hvd_category(
                package_dict.get(hvd_legislation.HVD_CATEGORY_FIELD)
            ):
                stats['skipped'] += 1
                continue

            stats['hvd'] += 1
            processed_hvd += 1
            before = _legislation_state(package_dict)
            updated_dict = copy.deepcopy(package_dict)
            hvd_legislation.sync_package_hvd_applicable_legislation(updated_dict)
            after = _legislation_state(updated_dict)

            if before == after:
                stats['unchanged'] += 1
            else:
                stats['changed'] += 1
                stats['changes'].append({
                    'id': updated_dict.get('id'),
                    'name': _package_label(updated_dict),
                    'before': before,
                    'after': after,
                })
                if apply_changes:
                    package_update(toolkit.fresh_context(context), package_dict)
                    stats['updated'] += 1

            if limit and processed_hvd >= limit:
                break
        except Exception as e:
            stats['failed'] += 1
            stats['errors'].append({
                'package': package_ref,
                'error': str(e),
            })
            log.exception(
                'Failed to backfill HVD applicable legislation for %s',
                package_ref,
            )

    return stats
