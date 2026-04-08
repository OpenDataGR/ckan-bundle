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
