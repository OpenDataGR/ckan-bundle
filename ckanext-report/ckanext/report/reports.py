'''
Working examples - simple tag report.
'''

from ckan import model

try:
    from collections import OrderedDict  # from python 2.7
except ImportError:
    from sqlalchemy.util import OrderedDict

from ckanext.report import lib

YES_LABEL = u'Ναι'
NO_LABEL = u'Όχι'


def _organization_title(pkg, cache):
    owner_org = getattr(pkg, 'owner_org', None)
    if not owner_org:
        return u'(κενό)'
    if owner_org not in cache:
        org = model.Group.get(owner_org)
        cache[owner_org] = (org.title or org.name) if org else u'(κενό)'
    return cache[owner_org]


def tagless_report(organization):
    '''
    Produces a report on packages without tags.
    Returns something like this:
        {
         'table': [
            {'name': 'river-levels', 'title': 'River levels', 'notes': 'Harvested',
             'user': 'bob', 'created': '2008-06-13T10:24:59.435631'},
            {'name': 'co2-monthly', 'title' 'CO2 monthly', 'notes': '',
             'user': 'bob', 'created': '2009-12-14T08:42:45.473827'},
            ],
         'num_packages': 56,
         'packages_without_tags_percent': 4,
         'average_tags_per_package': 3.5,
        }
    '''
    # Find the packages without tags (excluding showcases)
    q = model.Session.query(model.Package) \
             .outerjoin(model.PackageTag) \
             .filter(model.PackageTag.id == None)  # noqa: E711

    # Filter to include only active datasets (excluding harvest sources)
    q = q.filter(model.Package.state == 'active')
    q = lib.filter_datasets_only(q)

    if organization:
        q = lib.filter_by_organizations(q, organization, False)

    tagless_names = set(pkg.name for pkg in q.all())

    # Average number of tags per package
    q = model.Session.query(model.Package)
    q = q.filter(model.Package.state == 'active')
    q = lib.filter_datasets_only(q)
    if organization:
        q = lib.filter_by_organizations(q, organization, False)
    packages = q.all()
    num_packages = len(packages)
    organization_cache = {}

    all_pkgs = [OrderedDict((
        ('name', pkg.name),
        ('title', lib.resolve_dataset_title(pkg)),
        ('has_tags', YES_LABEL if pkg.name not in tagless_names else NO_LABEL),
        ('organization', _organization_title(pkg, organization_cache)),
        ('notes', lib.dataset_notes(pkg) or u'(κενό)'),
        ('created', pkg.metadata_created.isoformat()),
    )) for pkg in packages]

    all_pkgs.sort(key=lambda row: (0 if row['has_tags'] == NO_LABEL else 1,
                                   (row['title'] or '').lower(),
                                   row['name']))

    q = model.Session.query(model.Package)
    q = q.filter(model.Package.state == 'active')
    q = lib.filter_datasets_only(q)
    if organization:
        q = lib.filter_by_organizations(q, organization, False)
    q = q.join(model.PackageTag)
    num_taggings = q.count()
    if num_packages:
        average_tags_per_package = round(float(num_taggings) / num_packages, 1)
    else:
        average_tags_per_package = None
    tagless_count = len(tagless_names)
    packages_without_tags_percent = lib.percent(tagless_count, num_packages)

    return {
        'table': all_pkgs,
        'num_packages': num_packages,
        'tagless_count': tagless_count,
        'tagged_count': num_packages - tagless_count,
        'packages_without_tags_percent': packages_without_tags_percent,
        'average_tags_per_package': average_tags_per_package,
    }


def tagless_report_option_combinations():
    for organization in lib.all_organizations(include_none=True):
        yield {'organization': organization}


def tagless_post_access_filter(data, context):
    table = data.get('table', [])
    num_packages = len(table)
    tagless_count = sum(1 for row in table if row.get('has_tags') == NO_LABEL)
    data['num_packages'] = num_packages
    data['tagless_count'] = tagless_count
    data['tagged_count'] = num_packages - tagless_count
    data['packages_without_tags_percent'] = (
        lib.percent(tagless_count, num_packages) if num_packages else None
    )
    data['average_tags_per_package'] = None
    return data


from ckan.plugins import toolkit

tagless_report_info = {
    'name': 'tagless-datasets',
    'title': u'Κάλυψη ετικετών συνόλων δεδομένων',
    'description': u'Σύνοψη ανά σύνολο δεδομένων για την ύπαρξη ετικετών.',
    'option_defaults': OrderedDict((('organization', None),
                                    )),
    'option_combinations': tagless_report_option_combinations,
    'generate': tagless_report,
    'post_access_filter': tagless_post_access_filter,
    'template': 'report/tagless-datasets.html',
}
