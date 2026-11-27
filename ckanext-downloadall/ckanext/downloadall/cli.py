# encoding: utf-8

import json
import os

import click

# Define our own load_config function
def load_config(config_path=None):
    if config_path is None:
        # Try to get the config path from the environment variable
        config_path = os.environ.get('CKAN_INI')

    if config_path is None:
        # Default config path
        config_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', 'ckan.ini')

    # Load the config
    from ckan.cli import load_config

    conf = load_config(config_path)
    return conf

# Define our own click_config_option
click_config_option = click.option(
    '-c', '--config',
    default=None,
    metavar='CONFIG',
    help='Config file to use (default: development.ini)')

from ckan.config.middleware import make_app
from ckan import model
from ckan.plugins import toolkit

from . import eligibility
from . import freshness
from . import lib
from . import storage
from . import tasks


class CkanCommand(object):

    def __init__(self, conf=None):
        self.config = load_config(conf)
        self.app = make_app(self.config)

    def request_context(self):
        return self.app._wsgi_app.test_request_context()


@click.group()
@click.help_option(u'-h', u'--help')
@click_config_option
@click.pass_context
def cli(ctx, config, *args, **kwargs):
    ctx.obj = CkanCommand(config)


def _sync_timeout():
    '''Χρονικό όριο ανά dataset στο --synchronous, όσο και του job στον worker
    (ckanext.downloadall.job_timeout ή ckan.jobs.timeout).'''
    from . import dedup
    return dedup._job_timeout()


def _active_package_ids():
    '''Μόνο τα ids: τα datasets διαβάζονται ένα-ένα, με νέα ανάγνωση, ώστε
    ένα πέρασμα ωρών να μην κρατά (και να μην ξαναγράφει) την εικόνα τους από
    την αρχή του.'''
    return [row.id for row in model.Session.query(model.Package.id)
            .filter(model.Package.state == 'active')
            .order_by(model.Package.name)]


@cli.command(u'update-zip', short_help=u'Update zip file for a dataset')
@click.argument('dataset_ref')
@click.option(u'--synchronous', u'-s',
              help=u'Do it in the same process (not the worker)',
              is_flag=True)
@click.pass_obj
def update_zip(cmd, dataset_ref, synchronous):
    u''' update-zip <package-name>

    Generates zip file for a dataset, downloading its resources.'''
    with cmd.request_context():
        package = model.Package.get(dataset_ref)
        if not package:
            raise click.ClickException(u'Dataset not found: %s' % dataset_ref)
        if synchronous:
            tasks.update_zip(package.id, timeout=_sync_timeout())
        else:
            click.echo(u'%s: %s' % (package.name, lib.enqueue_zip(package.id)))
    click.secho(u'update-zip: SUCCESS', fg=u'green', bold=True)


@cli.command(u'update-all-zips',
             short_help=u'Update zip files for all datasets')
@click.option(u'--synchronous', u'-s',
              help=u'Do it in the same process (not the worker)',
              is_flag=True)
@click.option(u'--dry-run', is_flag=True,
              help=u'Only count the datasets that would be queued')
@click.option(u'--retry-failed', is_flag=True,
              help=u'Only datasets whose zip is missing, out of date or has '
                   u'resources that failed temporarily (for a daily cron)')
@click.pass_obj
def update_all_zips(cmd, synchronous, dry_run, retry_failed):
    u''' update-all-zips

    Βάζει στην ουρά ckanext.downloadall.queue ένα job για κάθε ενεργό, δημόσιο
    dataset που δικαιούται ZIP. Με hvd_only, μόνο για τα HVD. Τα ZIP των
    datasets που δεν το δικαιούνται σβήνονται μόνο με την εντολή cleanup.

    Με --retry-failed, μόνο όσα datasets δεν έχουν ZIP, έχουν ZIP που δεν
    αντιστοιχεί στην τρέχουσα εκδοχή τους (π.χ. μετά από αποτυχημένο build ή
    αλλαγή των ρυθμίσεων αποκλεισμού) ή έχουν πόρους με προσωρινή αποτυχία
    (βλ. freshness.needs_retry). Αυτά ξαναχτίζονται ακόμη κι αν το dataset δεν
    άλλαξε, το πολύ retry_failed_limit φορές για την ίδια εκδοχή.'''
    with cmd.request_context():
        counts = _update_all(synchronous, dry_run, retry_failed)
    verb = u'would queue' if dry_run else u'queued'
    click.echo(u'{} {} datasets, skipped {} not eligible'.format(
        verb, counts['queued'], counts['skipped'])
        + (u', {} up to date'.format(counts['current']) if retry_failed else u'')
        + u', {} errors'.format(counts['errors']))
    if counts['errors']:
        raise click.ClickException(
            u'update-all-zips: {} datasets failed'.format(counts['errors']))
    click.secho(u'update-all-zips: SUCCESS', fg=u'green', bold=True)


def _update_all(synchronous, dry_run, retry_failed):
    '''Ο βρόχος του update-all-zips. Επιστρέφει τους μετρητές.'''
    counts = {'queued': 0, 'skipped': 0, 'current': 0, 'errors': 0}
    for package_id in _active_package_ids():
        try:
            _update_one(package_id, counts, synchronous, dry_run, retry_failed)
        except Exception as e:
            # Ένα dataset με σφάλμα δεν σταματά το πέρασμα (π.χ. το cron)
            model.Session.rollback()
            counts['errors'] += 1
            click.echo(u'Error in dataset {}: {}: {}'.format(
                package_id, type(e).__name__, e), err=True)
    return counts


def _update_one(package_id, counts, synchronous, dry_run, retry_failed):
    # Νέα ανάγνωση του dataset· όχι η εικόνα του από την αρχή του περάσματος
    model.Session.expire_all()
    package = model.Package.get(package_id)
    if package is None or package.state != 'active':
        return
    if eligibility.dataset_exclusion_reason(eligibility.model_view(package)):
        counts['skipped'] += 1
        return
    if retry_failed and not freshness.needs_retry(
            toolkit.get_action('package_show')(
                {'ignore_auth': True}, {'id': package_id})):
        counts['current'] += 1
        return
    counts['queued'] += 1
    if dry_run:
        return
    if synchronous:
        click.echo(u'Processing dataset {}: {}'.format(counts['queued'], package.name))
        tasks.update_zip(package_id, None, not retry_failed, timeout=_sync_timeout())
    else:
        lib.enqueue_zip(package_id, skip_if_no_changes=not retry_failed)


def _zip_resources():
    import sqlalchemy as sa
    return model.Session.query(model.Resource, model.Package) \
        .join(model.Package, model.Package.id == model.Resource.package_id) \
        .filter(model.Resource.state == 'active') \
        .filter(model.Package.state == 'active') \
        .filter(sa.cast(model.Resource.extras, sa.UnicodeText)
                .like('%downloadall_metadata_modified%')) \
        .order_by(model.Package.name, model.Resource.position)


def _cleanup_plan():
    '''Τι θα σβηνόταν: ZIP datasets που δεν το δικαιούνται, διπλά ZIP του ίδιου
    dataset και blobs παλιών ZIP κάτω από resources/<id του ZIP>/ που δεν είναι
    το τρέχον αρχείο. Από τα διπλά ZIP κρατιέται το πρώτο με τη σειρά των
    πόρων, αυτό που ενημερώνει το job και δείχνει η σελίδα
    (freshness.zip_resource).'''
    zip_resources, blobs = [], []
    current_files, seen_packages = {}, set()
    for resource, package in _zip_resources():
        if not eligibility.is_zip_model_resource(resource):
            continue
        reason = eligibility.dataset_exclusion_reason(eligibility.model_view(package))
        if not reason and package.id in seen_packages:
            reason = 'duplicate zip'
        seen_packages.add(package.id)
        if reason:
            zip_resources.append({'resource_id': resource.id,
                                  'dataset': package.name, 'reason': reason})
        elif resource.url_type == 'upload':
            current_files[resource.id] = resource.url
    if storage.cloudstorage_enabled() and current_files:
        for resource_id, filename in storage.iterate_zip_blobs(set(current_files)):
            if filename != current_files[resource_id]:
                blobs.append({'resource_id': resource_id, 'filename': filename})
    return zip_resources, blobs


@cli.command(u'cleanup', short_help=u'Remove obsolete DownloadAll zips (dry-run by default)')
@click.option(u'--apply', 'apply_', is_flag=True,
              help=u'Actually delete (default: only report)')
@click.option(u'--limit', type=int, default=0,
              help=u'Maximum number of deletions (0 = no limit)')
@click.option(u'--output', type=click.Path(dir_okay=False),
              help=u'Write the inventory as JSON to this file')
@click.pass_obj
def cleanup(cmd, apply_, limit, output):
    u''' cleanup [--apply] [--limit N] [--output FILE]

    Χωρίς --apply μόνο καταγράφει. Σβήνει: τα ZIP datasets που δεν τα
    δικαιούνται (π.χ. μη HVD με hvd_only), τα διπλά ZIP ενός dataset, και τα
    blobs παλιών ZIP κάτω από resources/<id του ZIP>/. Δεν αγγίζει τίποτα άλλο
    στο storage.'''
    with cmd.request_context():
        zip_resources, blobs = _cleanup_plan()
        report = {'zip_resources': zip_resources, 'superseded_blobs': blobs,
                  'applied': bool(apply_)}
        click.echo(u'ZIP resources to delete: {}, superseded blobs: {}'.format(
            len(zip_resources), len(blobs)))
        try:
            if apply_:
                deleted, failed = _apply_cleanup(zip_resources, blobs, limit)
                report.update(deleted=deleted, failed=failed)
                click.echo(u'Deleted: {}, failed: {}'.format(deleted, failed))
        finally:
            # Η αναφορά γράφεται και αν η εκτέλεση διακοπεί
            if output:
                with open(output, 'w') as fp:
                    json.dump(report, fp, indent=2, ensure_ascii=False)
                click.echo(u'Inventory written to {}'.format(output))
    click.secho(u'cleanup: SUCCESS', fg=u'green', bold=True)


def _current_upload(resource_id):
    '''Το τρέχον όνομα αρχείου και το μέγεθος του πόρου, διαβασμένα τώρα από
    τη βάση (όχι από το σχέδιο, που μπορεί να είναι λεπτών).'''
    row = model.Session.query(model.Resource.url, model.Resource.url_type,
                              model.Resource.size) \
        .filter(model.Resource.id == resource_id).first()
    if row is None:
        return None, None
    return storage.upload_filename({'url': row.url, 'url_type': row.url_type}), \
        row.size


def _apply_cleanup(zip_resources, blobs, limit):
    '''Σβήνει τα στοιχεία του σχεδίου, ένα-ένα: σφάλμα σε ένα στοιχείο
    καταγράφεται σε αυτό και η εκτέλεση συνεχίζει. Το --limit μετρά μόνο τις
    επιτυχημένες διαγραφές. Επιστρέφει (σβήστηκαν, απέτυχαν).'''
    import ckanapi
    local_ckan = ckanapi.LocalCKAN()
    deleted = failed = 0
    for item in zip_resources:
        if limit and deleted >= limit:
            return deleted, failed
        try:
            with lib.own_update():
                local_ckan.action.resource_delete(id=item['resource_id'])
        except Exception as e:
            model.Session.rollback()
            error = u'{}: {}'.format(type(e).__name__, e)
            item.update(deleted=False, error=error)
            click.echo(u'Could not delete resource {}: {}'.format(
                item['resource_id'], error), err=True)
            failed += 1
        else:
            item['deleted'] = True
            deleted += 1
    for item in blobs:
        if limit and deleted >= limit:
            break
        current_file, current_size = _current_upload(item['resource_id'])
        if current_file == item['filename']:
            # Το ZIP ξαναχτίστηκε όσο γινόταν η λίστα των blobs και αυτό είναι
            # πλέον το τρέχον αρχείο του
            item.update(deleted=False, skipped='current file of the zip')
            continue
        if not storage.blob_verified(item['resource_id'], current_file,
                                     current_size):
            # Το παλιό blob σβήνεται μόνο αν το τρέχον ZIP υπάρχει στο storage
            item.update(deleted=False, skipped='current zip not verified')
            click.echo(u'Kept {}/{}: the current zip of the resource could not '
                       u'be verified in the storage'.format(
                           item['resource_id'], item['filename']), err=True)
            continue
        item['deleted'] = storage.delete_upload_blob(
            item['resource_id'], item['filename'])
        if item['deleted']:
            deleted += 1
        else:
            failed += 1
    return deleted, failed
