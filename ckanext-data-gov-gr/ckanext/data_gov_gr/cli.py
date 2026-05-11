from __future__ import annotations

import click

from ckanext.data_gov_gr import commands


def get_commands():
    return [data_gov_gr]


@click.group('data-gov-gr', short_help='data.gov.gr maintenance commands')
def data_gov_gr():
    pass


@data_gov_gr.command(
    'refresh-home-dataset-resources',
    help='Ανανεώνει το αποθηκευμένο πλήθος πόρων της αρχικής σελίδας.'
)
def refresh_home_dataset_resources():
    try:
        payload = commands.refresh_home_dataset_resources_snapshot()
    except Exception as e:
        raise click.ClickException(str(e))

    click.secho(
        'Stored homepage dataset resources snapshot: {count} ({computed_at})'.format(
            count=payload['count'],
            computed_at=payload['computed_at'],
        ),
        fg='green',
        bold=True,
    )


@data_gov_gr.command(
    'backfill-hvd-applicable-legislation',
    help='Συγχρονίζει την HVD εφαρμοστέα νομοθεσία σε υπάρχοντα HVD σύνολα.'
)
@click.option(
    '--apply',
    'apply_changes',
    is_flag=True,
    help='Εφαρμόζει τις αλλαγές. Χωρίς αυτό γίνεται μόνο dry-run.',
)
@click.option(
    '--package-id',
    'package_ids',
    multiple=True,
    help='Συγκεκριμένο package id/name. Μπορεί να δοθεί πολλές φορές.',
)
@click.option(
    '--limit',
    type=int,
    default=0,
    show_default=True,
    help='Μέγιστος αριθμός HVD packages για επεξεργασία. 0 σημαίνει χωρίς όριο.',
)
@click.option(
    '--rows',
    type=int,
    default=100,
    show_default=True,
    help='Μέγεθος batch για package_search όταν δεν δίνεται --package-id.',
)
@click.option(
    '--verbose',
    is_flag=True,
    help='Εμφανίζει αναλυτικά τα packages που θα αλλάξουν ή άλλαξαν.',
)
def backfill_hvd_applicable_legislation(
    apply_changes,
    package_ids,
    limit,
    rows,
    verbose,
):
    try:
        stats = commands.backfill_hvd_applicable_legislation(
            apply_changes=apply_changes,
            package_ids=package_ids,
            limit=limit or None,
            rows=rows,
        )
    except Exception as e:
        raise click.ClickException(str(e))

    mode = 'apply' if apply_changes else 'dry-run'
    if apply_changes:
        summary = (
            'HVD applicable legislation backfill ({mode}): '
            'checked={checked}, hvd={hvd}, changed={changed}, '
            'updated={updated}, unchanged={unchanged}, skipped={skipped}, '
            'failed={failed}'
        )
    else:
        summary = (
            'HVD applicable legislation backfill ({mode}): '
            'checked={checked}, hvd={hvd}, would_change={changed}, '
            'updated=0, unchanged={unchanged}, skipped={skipped}, '
            'failed={failed}'
        )

    click.secho(
        summary.format(mode=mode, **stats),
        fg='green' if apply_changes else 'yellow',
        bold=True,
    )

    if not apply_changes:
        click.echo('Dry-run only. No packages were written.')

    if verbose:
        for change in stats['changes']:
            click.echo('- {name} ({id})'.format(**change))
        for error in stats['errors']:
            click.secho(
                '- ERROR {package}: {error}'.format(**error),
                fg='red',
            )
