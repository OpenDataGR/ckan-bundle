from __future__ import annotations

import logging
from typing import Any

import ckan.lib.dictization.model_dictize as model_dictize
import ckan.lib.jobs as bg_jobs
import ckan.logic.schema as schema_
import ckan.model as model
import ckan.plugins.toolkit as toolkit
from ckan.common import _
from ckan.logic import NotFound, ValidationError

from ckanext.manage_tags import jobs


log = logging.getLogger(__name__)


def _tag_not_found() -> NotFound:
    return NotFound(_('Tag not found.'))


def _get_manageable_tag(tag_id: str):
    tag = model.Tag.by_id(tag_id, autoflush=False)
    if not tag:
        raise _tag_not_found()
    if tag.vocabulary_id is not None:
        raise ValidationError({
            'id': [_('Only global free tags can be edited from this page.')]
        })
    return tag


def _validate_tag_name(context: dict[str, Any], name: str) -> str:
    schema = {'name': schema_.default_tags_schema()['name']}
    data, errors = toolkit.navl_validate({'name': name}, schema, context)
    if errors:
        raise ValidationError(errors)
    return data['name']


def _affected_packages(tag) -> list[dict[str, str]]:
    packages = (
        model.Session.query(model.Package)
        .join(model.PackageTag, model.PackageTag.package_id == model.Package.id)
        .filter(model.PackageTag.tag_id == tag.id)
        .filter(model.PackageTag.state == 'active')
        .order_by(model.Package.name.asc())
        .all()
    )
    return [
        {
            'id': package.id,
            'name': package.name,
            'title': package.title or package.name,
            'type': package.type or 'dataset',
            'state': package.state or 'active',
        }
        for package in packages
    ]


def manage_tags_tag_update(context, data_dict):
    toolkit.check_access('manage_tags_tag_update', context, data_dict)

    context.setdefault('model', model)
    context.setdefault('session', model.Session)

    tag_id = toolkit.get_or_bust(data_dict, 'id')
    tag = _get_manageable_tag(tag_id)
    validated_name = _validate_tag_name(context, data_dict.get('name', u'').strip())
    should_reindex = toolkit.asbool(data_dict.get('reindex'))
    affected_packages = _affected_packages(tag)

    if validated_name == tag.name:
        tag_dict = model_dictize.tag_dictize(tag, context)
        tag_dict.update({
            'changed': False,
            'affected_packages': affected_packages,
            'reindexed_packages': [],
            'failed_reindex': [],
            'reindex_requested': should_reindex,
            'reindex_job_id': None,
            'reindex_enqueue_error': None,
        })
        return tag_dict

    existing_tag = model.Tag.by_name(validated_name, autoflush=False)
    if existing_tag and existing_tag.id != tag.id:
        raise ValidationError({
            'name': [_('A free tag with this name already exists.')]
        })

    old_name = tag.name
    tag.name = validated_name

    try:
        model.repo.commit()
    except Exception:
        model.Session.rollback()
        raise

    reindex_job_id = None
    reindex_enqueue_error = None
    if should_reindex:
        package_ids = [package['id'] for package in affected_packages]

        try:
            job = bg_jobs.enqueue(
                jobs.reindex_packages_for_tag_rename,
                kwargs={
                    'package_ids': package_ids,
                    'old_name': old_name,
                    'new_name': validated_name,
                },
                title=u"Manage tags reindex '{old}' -> '{new}'".format(
                    old=old_name,
                    new=validated_name,
                ),
                queue=bg_jobs.DEFAULT_QUEUE_NAME,
                rq_kwargs={u'timeout': 6 * 60 * 60},
            )
            reindex_job_id = job.id
        except Exception as error:
            reindex_enqueue_error = str(error)
            log.exception(
                "Failed to enqueue manage_tags reindex job after tag rename '%s' -> '%s'",
                old_name,
                validated_name,
            )

    tag_dict = model_dictize.tag_dictize(tag, context)
    tag_dict.update({
        'changed': True,
        'affected_packages': affected_packages,
        'reindexed_packages': [],
        'failed_reindex': [],
        'reindex_requested': should_reindex,
        'reindex_job_id': reindex_job_id,
        'reindex_enqueue_error': reindex_enqueue_error,
    })
    return tag_dict


@toolkit.auth_allow_anonymous_access
def manage_tags_tag_update_auth(context, data_dict):
    return {'success': toolkit.check_access('sysadmin', context, data_dict)}
