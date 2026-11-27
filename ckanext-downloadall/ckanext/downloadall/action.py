import ckan.lib.dictization.model_dictize as model_dictize
import ckan.lib.plugins as lib_plugins
import ckan.plugins as p
from ckan import model

from . import eligibility
from . import lib


def _active_zip_resources(pkg_model, session, package_id):
    '''Οι ενεργοί πόροι ZIP του dataset, με τη σειρά τους.'''
    resources = session.query(pkg_model.Resource) \
        .filter(pkg_model.Resource.package_id == package_id) \
        .filter(pkg_model.Resource.state == 'active') \
        .order_by(pkg_model.Resource.position) \
        .all()
    return [res for res in resources if eligibility.is_zip_model_resource(res)]


def _dictize_zip_resources(pkg, resources, pkg_model, session):
    '''Μετατροπή των model.Resource σε dicts κατάλληλα για package_update.

    Χρησιμοποιεί:
      - model_dictize.package_dictize(..., for_edit=True) ώστε να μην καλείται
        url_for, το url του upload να μένει καθαρό filename (το cloudstorage
        δεν ξανακάνει upload ή clear) και το dict να έχει όλα τα πεδία του
        dataset που τυχόν διαβάζουν οι output validators (π.χ. if_empty_same_as)·
      - το show_package_schema του package plugin (π.χ. ckanext-scheming,
        ckanext-fluent) ώστε πεδία αποθηκευμένα ως JSON strings στα extras
        (π.χ. language_options='[]', applicable_legislation='[]',
        name_translated) να μετατραπούν στις τιμές που περιμένει το
        package_update validation·
      - απομονωμένο context χωρίς after_dataset_show, ώστε να μην μπαίνουν
        πεδία qa/archiver στα extras του ZIP και να μη μολύνεται το context
        του caller.
    '''
    wanted_ids = [res.id for res in resources]
    wanted_set = set(wanted_ids)
    show_context = {
        'model': pkg_model,
        'session': session,
        'package': pkg,
        'for_edit': True,
    }
    package_dict = model_dictize.package_dictize(pkg, show_context)
    package_plugin = lib_plugins.lookup_package_plugin(pkg.type)
    schema = package_plugin.show_package_schema()
    if schema:
        package_dict, _errors = lib_plugins.plugin_validate(
            package_plugin,
            show_context,
            package_dict,
            schema,
            'package_show',
        )
    by_id = {
        res['id']: res
        for res in package_dict.get('resources') or []
        if res.get('id') in wanted_set
    }
    return [by_id[res_id] for res_id in wanted_ids if res_id in by_id]


@p.toolkit.chained_action
def resource_delete(original_action, context, data_dict):
    '''Σημειώνει το id που διαγράφεται ρητά με resource_delete, ώστε το
    chained package_update να αφήσει τη διαγραφή του ZIP να ολοκληρωθεί.'''
    resource_id = data_dict.get('id') if isinstance(data_dict, dict) else None
    with lib.deleting_resource(resource_id):
        return original_action(context, data_dict)


@p.toolkit.chained_action
def package_update(original_action, context, data_dict):
    '''Διατηρεί τους υπάρχοντες πόρους ZIP «Λήψη όλων» όταν το package_update
    στέλνει νέα λίστα πόρων χωρίς αυτούς (π.χ. harvesters WMS/CSW/DCAT/CKAN ή
    API scripts).

    Έτσι το ZIP κρατά το ίδιο id, δεν εξαφανίζεται το κουμπί και δεν μένουν
    ορφανά αρχεία στο cloud storage. Μετά το commit μπαίνει πάντα αναγκαστικό
    ξαναχτίσιμο στον ίδιο πόρο ZIP (χωρίς αύξηση του downloadall_retries), ώστε
    να ανανεώνονται και τα δεδομένα πίσω από URLs που δεν άλλαξαν.

    Όταν λείπει το κλειδί resources (π.χ. επεξεργασία μεταδεδομένων από το UI
    με allow_partial_update) ή όταν ο πόρος διαγράφεται ρητά μέσω
    resource_delete, δεν γίνεται καμία παρέμβαση.
    '''
    if not isinstance(data_dict, dict):
        return original_action(context, data_dict)

    incoming = data_dict.get('resources')
    if not isinstance(incoming, list):
        return original_action(context, data_dict)

    name_or_id = data_dict.get('id') or data_dict.get('name')
    if not name_or_id:
        return original_action(context, data_dict)

    pkg_model = context.get('model') or model
    pkg = pkg_model.Package.get(name_or_id)
    if pkg is None:
        return original_action(context, data_dict)

    session = context.get('session') or pkg_model.Session
    existing_zips = _active_zip_resources(pkg_model, session, pkg.id)
    if not existing_zips:
        return original_action(context, data_dict)

    incoming_ids = {
        res.get('id')
        for res in incoming
        if isinstance(res, dict) and res.get('id')
    }
    missing_models = [
        res for res in existing_zips
        if res.id not in incoming_ids and not lib.is_deleting_resource(res.id)
    ]
    if not missing_models:
        return original_action(context, data_dict)

    missing_zips = _dictize_zip_resources(pkg, missing_models, pkg_model, session)

    updated_data_dict = dict(data_dict)
    updated_data_dict['resources'] = list(incoming) + missing_zips
    # Ζητείται αναγκαστικό ξαναχτίσιμο μετά το commit (χωρίς αύξηση του
    # downloadall_retries), ώστε να ανανεωθεί το ZIP ακόμα κι όταν ο harvester
    # διατήρησε τα ίδια resource ids/URLs (π.χ. WMS/CSW με
    # preserve_resource_ids_by_url) και άλλαξαν μόνο τα δεδομένα πίσω από το URL.
    # Η κατάσταση μετά την ενημέρωση: ένα dataset που γίνεται deleted/draft δεν
    # χρειάζεται νέο ZIP
    added_force = False
    new_state = data_dict.get('state') or pkg.state
    if new_state == 'active' and not lib.in_own_update():
        added_force = lib.mark_forced_rebuild_after_commit(pkg.id)
    try:
        return original_action(context, updated_data_dict)
    except Exception:
        if added_force:
            lib.unmark_forced_rebuild_after_commit(pkg.id)
        raise


@p.toolkit.chained_action  # requires CKAN 2.7+
def datastore_create(original_action, context, data_dict):
    # This gets called when xloader or datapusher loads a new resource or
    # data dictionary is changed. We need to regenerate the zip when the latter
    # happens, and it's ok if it happens at the other times too.
    result = original_action(context, data_dict)

    # Η αλλαγή αφορά τη βάση του datastore, που έχει ήδη γίνει commit· το job
    # μπαίνει αμέσως στην ουρά (όχι μετά το commit του CKAN session)
    if 'resource_id' in data_dict:
        res = model.Resource.get(data_dict['resource_id'])
        packages = res.related_packages() if res else []
        if packages and eligibility.package_needs_job(packages[0]):
            lib.enqueue_zip(packages[0].id)

    return result
