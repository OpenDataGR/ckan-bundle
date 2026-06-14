[![Tests](https://github.com/apostolosvadrachanis/ckanext-enrich-search-capabilities/workflows/Tests/badge.svg?branch=main)](https://github.com/apostolosvadrachanis/ckanext-enrich-search-capabilities/actions)

# ckanext-enrich-search-capabilities

Adds database-backed keyword filtering to the public `ckanext-pages` indexes:

- `/pages?q=keyword`
- `/blog?q=keyword`

It can also show live search suggestions (the first matching datasets in a
dropdown) while typing in the `/dataset` search field.

The search covers titles, slugs, and content. Anonymous and regular users only
see public results. Users with `ckanext_pages_update` access can also see
private results, which are clearly labelled. Organization/group pages remain
excluded.

Page and blog search is insensitive to letter case, Greek accents, and the
final sigma (`ΠΟΛΗ`, `πολη`, and `πόλη` all match), and queries of three or
more characters also tolerate small typos through trigram word similarity.
When a search term is given, results are ordered by relevance (title matches
rank above slug matches above content matches) before the usual date ordering.

## Requirements

- CKAN 2.11
- ckanext-pages 0.5.2
- PostgreSQL `unaccent` and `pg_trgm` extensions, created in the CKAN
  database (`CREATE EXTENSION IF NOT EXISTS unaccent; CREATE EXTENSION IF
  NOT EXISTS pg_trgm;`). Both are trusted extensions, so the database owner
  can create them without superuser rights.


## Installation

To install ckanext-enrich-search-capabilities:

1. Activate your CKAN virtual environment, for example:

     . /usr/lib/ckan/default/bin/activate

2. Clone the source and install it on the virtualenv

    git clone https://github.com/apostolosvadrachanis/ckanext-enrich-search-capabilities.git
    cd ckanext-enrich-search-capabilities
    pip install -e .
	pip install -r requirements.txt

3. Enable the plugin after `pages` and the site theme plugin:

       ckan.plugins = ... pages data_gov_gr enrich_search_capabilities ...

4. Restart CKAN. For example if you've deployed CKAN with Apache on Ubuntu:

     sudo service apache2 reload


## Config settings

Search is disabled by default. To enable it, either:

- Toggle it on from the CKAN admin config page (`/ckan-admin/config`), or
- Set it in the INI file:

```ini
ckanext.enrich_search_capabilities.enabled = true
```

When disabled, the original `ckanext-pages` `/pages` and `/blog` indexes are
used unchanged.

The header search destination dropdown is disabled by default. It can be
enabled independently:

```ini
ckanext.enrich_search_capabilities.header_search_enabled = true
```

When enabled, the header search offers the available dataset, data service,
showcase, organization, page, and blog search destinations. Page and blog
destinations are shown only when page search is enabled.

The external guides search option is disabled by default. When enabled, a
"Guides" entry appears in the header search dropdown and opens results in a
new tab on the GitBook guides site:

```ini
ckanext.enrich_search_capabilities.guides_search_enabled = true
```

The dataset live search is disabled by default and can also be enabled
independently:

```ini
ckanext.enrich_search_capabilities.dataset_live_search_enabled = true
```

When enabled, typing two or more characters in the `/dataset` search field
shows the first matching datasets in a dropdown, using the same query the
search button runs (`package_search` with the plain `q` text and no extra
filters). Results link straight to the dataset page, and a final entry
submits the regular search. The action behind it is also available over the
API:

    /api/3/action/enrich_dataset_live_search?q=keyword&limit=10

How many suggestions are shown is configurable from the admin config page or
the INI file, with a hard maximum of 10. The value also caps the `limit`
parameter of API callers:

```ini
ckanext.enrich_search_capabilities.dataset_live_search_limit = 10
```

The regular search form keeps working unchanged when the option is disabled
or JavaScript is unavailable.


## Developer installation

To install ckanext-enrich-search-capabilities for development, activate your CKAN virtualenv and
do:

    git clone https://github.com/apostolosvadrachanis/ckanext-enrich-search-capabilities.git
    cd ckanext-enrich-search-capabilities
    pip install -e .
    pip install -r dev-requirements.txt


## Tests

To run the tests, do:

    pytest --ckan-ini=test.ini

## Translations

The extension includes Greek translations. After adding or changing
translatable strings, update and compile the catalogs with:

    python setup.py extract_messages
    python setup.py update_catalog -l el
    python setup.py compile_catalog


## Releasing a new version of ckanext-enrich-search-capabilities

If ckanext-enrich-search-capabilities should be available on PyPI you can follow these steps to publish a new version:

1. Update the version number in the `pyproject.toml` file. See [PEP 440](http://legacy.python.org/dev/peps/pep-0440/#public-version-identifiers) for how to choose version numbers.

2. Make sure you have the latest version of necessary packages:

    pip install --upgrade setuptools wheel twine

3. Create a source and binary distributions of the new version:

       python -m build && twine check dist/*

   Fix any errors you get.

4. Upload the source distribution to PyPI:

       twine upload dist/*

5. Commit any outstanding changes:

       git commit -a
       git push

6. Tag the new release of the project on GitHub with the version number from
   the `setup.py` file. For example if the version number in `setup.py` is
   0.0.1 then do:

       git tag 0.0.1
       git push --tags

## License

[AGPL](https://www.gnu.org/licenses/agpl-3.0.en.html)
