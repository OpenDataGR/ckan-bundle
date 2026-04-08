from __future__ import annotations

import ckan.model as model
import ckan.plugins.toolkit as toolkit
import ckan.lib.jobs as bg_jobs
from ckan.lib.helpers import Page
from ckan.lib.helpers import helper_functions as h
from ckan.common import _, g, request
from flask import flash, redirect, render_template, url_for

from ckanext.manage_tags import helpers, jobs


def _sysadmin_context():
    context = {
        'model': model,
        'session': model.Session,
        'user': g.user,
    }
    try:
        toolkit.check_access('sysadmin', context, {})
    except toolkit.NotAuthorized:
        toolkit.abort(403, _('Need to be system administrator to administer'))
    return context


def _load_tag_or_404(tag_id: str):
    package_page_number = h.get_page_number(request.args) or 1
    packages_per_page = 25
    package_offset = packages_per_page * (package_page_number - 1)
    tag = helpers.get_manageable_tag_data(
        tag_id,
        package_limit=packages_per_page,
        package_offset=package_offset,
    )
    if not tag:
        toolkit.abort(404, _('Tag not found.'))

    def packages_pager_url(page: int, partial: str | None = None, **kwargs):
        params = request.args.to_dict(flat=True)
        params.update(kwargs)
        params['page'] = page
        return url_for('manage_tags.edit', tag_id=tag_id, **params)

    tag['packages_page'] = Page(
        collection=tag['packages'],
        page=package_page_number,
        presliced_list=True,
        url=packages_pager_url,
        item_count=tag['usage_count'],
        items_per_page=packages_per_page,
    )
    return tag


def _validation_message(error: toolkit.ValidationError) -> str:
    messages = []
    for field, errors in sorted((error.error_dict or {}).items()):
        if isinstance(errors, (list, tuple)):
            for item in errors:
                messages.append(u'{}: {}'.format(field, item))
        else:
            messages.append(u'{}: {}'.format(field, errors))
    return '; '.join(messages) or str(error)


def index():
    _sysadmin_context()

    q = request.args.get('q', u'').strip()
    page_number = h.get_page_number(request.args) or 1
    items_per_page = 25
    offset = items_per_page * (page_number - 1)
    tags, total_count = helpers.get_free_tags(
        q,
        limit=items_per_page,
        offset=offset,
    )
    page = Page(
        collection=tags,
        page=page_number,
        presliced_list=True,
        url=h.pager_url,
        item_count=total_count,
        items_per_page=items_per_page,
    )
    return render_template(
        'admin/manage_tags_index.html',
        q=q,
        page=page,
    )


def rebuild_index():
    _sysadmin_context()

    if request.method == 'POST':
        try:
            job = bg_jobs.enqueue(
                jobs.rebuild_search_index,
                kwargs={'clear': False},
                title=u"Manage tags Rebuild Index",
                queue=bg_jobs.DEFAULT_QUEUE_NAME,
                rq_kwargs={u'timeout': 12 * 60 * 60},
            )
        except Exception as error:
            toolkit.h.flash_error(
                _('The Rebuild Index job could not be queued: {0}').format(error)
            )
        else:
            flash(
                _('Rebuild Index job was queued (job id: {0}).').format(job.id),
                'alert-info',
            )
        return redirect(url_for('manage_tags.rebuild_index'))

    return render_template('admin/manage_tags_rebuild_index.html')


def edit(tag_id):
    context = _sysadmin_context()
    tag = _load_tag_or_404(tag_id)
    form_data = {'name': tag['name'], 'reindex': False}

    if request.method == 'POST':
        form_data['name'] = request.form.get('name', u'').strip()
        form_data['reindex'] = toolkit.asbool(request.form.get('reindex'))
        try:
            result = toolkit.get_action('manage_tags_tag_update')(
                context,
                {
                    'id': tag_id,
                    'name': form_data['name'],
                    'reindex': form_data['reindex'],
                },
            )
        except toolkit.ValidationError as error:
            toolkit.h.flash_error(
                _('Error updating tag: {0}').format(_validation_message(error))
            )
            tag = _load_tag_or_404(tag_id)
            return render_template(
                'admin/manage_tags_edit.html',
                tag=tag,
                form_data=form_data,
            )

        if result.get('changed'):
            flash(_('Tag updated successfully.'), 'alert-success')
        else:
            flash(_('Tag name was unchanged.'), 'alert-success')

        reindex_enqueue_error = result.get('reindex_enqueue_error')
        if not result.get('changed'):
            if result.get('reindex_requested'):
                flash(
                    _('Tag name was unchanged, so no reindex job was queued.'),
                    'alert-info',
                )
        elif reindex_enqueue_error:
            flash(
                _('The tag was renamed, but the background reindex job could not be queued: {0}').format(
                    reindex_enqueue_error
                ),
                'warning',
            )
        elif result.get('reindex_job_id'):
            flash(
                _('Background reindex was queued for {0} affected datasets (job id: {1}).').format(
                    len(result.get('affected_packages') or []),
                    result['reindex_job_id'],
                ),
                'alert-info',
            )
        elif not result.get('reindex_requested'):
            flash(
                _('The tag was renamed without reindex. Use the Rebuild Index tab if you want search results to be refreshed immediately.'),
                'alert-warning',
            )

        return redirect(url_for('manage_tags.edit', tag_id=tag_id))

    return render_template(
        'admin/manage_tags_edit.html',
        tag=tag,
        form_data=form_data,
    )
