'''
Working examples - simple tag report.
'''

from sqlalchemy import and_, func

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


def _active_package_tag_join():
    # Όταν αφαιρείται ετικέτα, το CKAN κρατά την εγγραφή package_tag με
    # state='deleted', οπότε μετρώνται μόνο οι ενεργές
    return and_(model.PackageTag.package_id == model.Package.id,
                model.PackageTag.state == 'active')


def tagless_report(organization=None):
    '''
    Για όλους τους οργανισμούς επιστρέφει συγκεντρωτικά στοιχεία ανά
    οργανισμό· για συγκεκριμένο οργανισμό, μία γραμμή ανά σύνολο δεδομένων.
    '''
    if not organization:
        return tagless_index()
    return tagless_for_organization(organization)


def tagless_index():
    '''
    Συγκεντρωτικά στοιχεία ετικετών ανά οργανισμό, με ένα μόνο ερώτημα στη
    βάση αντί να φορτώνονται όλα τα σύνολα δεδομένων στον πίνακα.
    '''
    # Ίδιο κριτήριο με την προβολή οργανισμού: χωρίς ετικέτες είναι όσα δεν
    # έχουν καμία ενεργή εγγραφή package_tag
    num_tags = func.count(model.PackageTag.id)
    q = model.Session.query(model.Group.id, model.Group.name,
                            model.Group.title, num_tags) \
             .join(model.Package, model.Package.owner_org == model.Group.id) \
             .outerjoin(model.PackageTag, _active_package_tag_join()) \
             .filter(model.Group.type == 'organization') \
             .filter(model.Group.state == 'active') \
             .filter(model.Package.state == 'active')
    q = lib.filter_datasets_only(q) \
        .group_by(model.Group.id, model.Package.id)

    rows_by_org = OrderedDict()
    for org_id, org_name, org_title, pkg_num_tags in q:
        row = rows_by_org.get(org_id)
        if row is None:
            row = rows_by_org[org_id] = OrderedDict((
                ('organization_name', org_name),
                ('organization_title', org_title or org_name),
                ('num_packages', 0),
                ('tagless_count', 0),
            ))
        row['num_packages'] += 1
        if not pkg_num_tags:
            row['tagless_count'] += 1

    table = list(rows_by_org.values())
    for row in table:
        row['tagged_count'] = row['num_packages'] - row['tagless_count']
        row['packages_without_tags_percent'] = lib.percent(
            row['tagless_count'], row['num_packages'])
    # Πρώτα οι οργανισμοί με τα περισσότερα σύνολα δεδομένων χωρίς ετικέτες
    table.sort(key=lambda row: (-row['tagless_count'],
                                row['organization_title'].lower()))

    num_packages = sum(row['num_packages'] for row in table)
    tagless_count = sum(row['tagless_count'] for row in table)
    return {
        'table': table,
        'total_organizations': len(table),
        'num_packages': num_packages,
        'tagless_count': tagless_count,
        'tagged_count': num_packages - tagless_count,
        'packages_without_tags_percent': lib.percent(tagless_count, num_packages),
    }


def tagless_for_organization(organization):
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
    # Ενεργά σύνολα δεδομένων του οργανισμού (χωρίς showcases, harvest sources κ.λπ.)
    datasets = model.Session.query(model.Package) \
                    .filter(model.Package.state == 'active')
    datasets = lib.filter_datasets_only(datasets)
    datasets = lib.filter_by_organizations(datasets, organization, False)

    # Find the packages without tags
    q = datasets.outerjoin(model.PackageTag, _active_package_tag_join()) \
                .filter(model.PackageTag.id == None)  # noqa: E711
    tagless_names = set(pkg.name for pkg in q.all())

    packages = datasets.all()
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

    # Average number of tags per package
    num_taggings = datasets.join(model.PackageTag, _active_package_tag_join()).count()
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
    'description': u'Σύνοψη ανά οργανισμό και ανά σύνολο δεδομένων για την ύπαρξη ετικετών.',
    'option_defaults': OrderedDict((('organization', None),
                                    )),
    'option_combinations': tagless_report_option_combinations,
    'generate': tagless_report,
    'post_access_filter': tagless_post_access_filter,
    'template': 'report/tagless-datasets.html',
}
