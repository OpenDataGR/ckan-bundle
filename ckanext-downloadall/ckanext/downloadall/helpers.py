def _get_pkg_value(pkg, key):
    """Safely get attribute or dict value from a package-like object."""
    if isinstance(pkg, dict):
        return pkg.get(key)
    return getattr(pkg, key, None)


def _get_dataset_type(pkg):
    """Return the dataset type if available, otherwise None."""
    for key in ('type', 'dataset_type', 'package_type'):
        value = _get_pkg_value(pkg, key)
        if value:
            return value
    return None


def is_data_service(pkg):
    """Return True when the given package is a data-service dataset."""
    dataset_type = _get_dataset_type(pkg)
    if dataset_type in ('data-service', 'data_service'):
        return True

    # Some scheming datasets store the type as an extra key/value pair
    extras = _get_pkg_value(pkg, 'extras')
    if isinstance(extras, dict):
        for key, value in extras.items():
            if key in ('dataset_type', 'package_type') and value in ('data-service', 'data_service'):
                return True
    elif isinstance(extras, list):
        for extra in extras:
            if isinstance(extra, dict):
                key = extra.get('key')
                value = extra.get('value')
            else:
                key = getattr(extra, 'key', None)
                value = getattr(extra, 'value', None)
            if key in ('dataset_type', 'package_type') and value in ('data-service', 'data_service'):
                return True
    return False


def pop_zip_resource(pkg):
    '''Finds the zip resource in a package's resources, removes it from the
    package and returns it. NB the package doesn't have the zip resource in it
    any more.

    OD-857: αφαιρούνται όλα τα ZIP, και επιστρέφεται αυτό που ενημερώνει το
    job (freshness.zip_resource).
    '''
    from . import eligibility, freshness
    zip_res = freshness.zip_resource(pkg)
    pkg['resources'] = [res for res in pkg.get('resources', [])
                        if not eligibility.is_zip_resource(res)]
    if is_data_service(pkg):
        return None
    return zip_res


def zip_state(pkg, zip_res=None):
    '''Κατάσταση του κουμπιού «Λήψη όλων»: ready, stale, none ή hidden
    (βλ. freshness.zip_state).'''
    from . import freshness
    return freshness.zip_state(pkg, zip_res)


def zip_missing_count(zip_res):
    '''Πόσοι πόροι του dataset δεν περιλαμβάνονται στο ZIP (αποκλεισμένοι ή
    αποτυχημένοι), σύμφωνα με τα στοιχεία του τελευταίου build.'''
    from . import freshness
    return freshness.build_count(zip_res, 'downloadall_excluded') + \
        freshness.build_count(zip_res, 'downloadall_failed')
