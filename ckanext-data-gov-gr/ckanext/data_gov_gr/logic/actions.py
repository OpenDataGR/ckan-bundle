from __future__ import annotations

from typing import (Container, Optional)

from ckan.common import config, asbool, aslist
import sqlalchemy

import ckan
import ckan.lib.dictization
import ckan.logic as logic
import ckan.logic.action
import ckan.logic.schema
import ckan.lib.navl.dictization_functions

import ckan.plugins.toolkit as toolkit
from typing import Any, Dict
import logging
from ckan.types import Context, DataDict
from ckan.types.logic import ActionResult
import ckan.logic as logic
import ckan.lib.mailer as mailer
import ckan.lib.dictization.model_dictize as model_dictize
from socket import error as socket_error

import uuid
from ckan import model
from ckan import authz
from ckan.lib.api_token import get_user_from_token
from ckan.lib.mailer import mail_recipient
from ckan.common import _, request
import ckan.logic.schema
from ckan.logic import _validate
import ckan.lib.helpers as h
from ckanext.data_gov_gr import organization_stats
from ckanext.data_gov_gr.logic.hvd_legislation import (
    HVD_CATEGORY_FORM_PRESENT_FIELD,
    sync_package_hvd_applicable_legislation,
)

log = logging.getLogger(__name__)

@toolkit.chained_action
def user_delete(original_action, context, data_dict):
    """Αν ο χρήστης είναι pending, μετονομάζει το name σε
    <name>_deleted_<uuid> πριν τη διαγραφή, ώστε να ελευθερωθεί
    το αρχικό username."""

    try:
        user_id = data_dict.get("id")
        user_obj = model.User.get(user_id) if user_id else None

        if user_obj and user_obj.is_pending():
            old_name = user_obj.name or "user"
            suffix = f"_deleted_{uuid.uuid4()}"
            max_len = 255
            base = old_name
            if len(base) + len(suffix) > max_len:
                base = base[: max_len - len(suffix)]

            user_obj.name = f"{base}{suffix}"
            log.info(
                "Renamed pending user %s -> %s before delete",
                old_name, user_obj.name,
            )
    except Exception as e:
        log.warning("Could not rename pending user before delete: %r", e)

    return original_action(context, data_dict)

# ----------------------------------------------------------------------------------------------

def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _is_upload_or_tabledesigner_resource(data_dict: Dict[str, Any], current: Dict[str, Any] | None = None) -> bool:
    """
    Επιστρέφει True όταν ο πόρος είναι upload ή tabledesigner.

    Σημείωση:
    - Στο resource_create για upload, συχνά δεν έχει μπει ακόμα url_type=upload,
      αλλά υπάρχει το πεδίο `upload`.
    """
    current = current or {}
    if data_dict.get('upload'):
        return True

    for d in (data_dict, current):
        url_type = d.get('url_type')
        if isinstance(url_type, str) and url_type.strip().lower() in {'upload', 'tabledesigner'}:
            return True
        resource_type = d.get('resource_type')
        if isinstance(resource_type, str) and resource_type.strip().lower() == 'tabledesigner':
            return True

    return False


def _get_dataset_name_from_package_id(package_id_or_name: Any) -> str | None:
    if _is_blank(package_id_or_name):
        return None
    try:
        pkg = model.Package.get(package_id_or_name)
        if pkg and pkg.name:
            return pkg.name
    except Exception:
        pass
    return str(package_id_or_name)


def _build_dataset_url(dataset_name: str) -> str:
    try:
        return toolkit.url_for('dataset.read', id=dataset_name, qualified=True)
    except Exception:
        return f"/dataset/{dataset_name}"


def _ensure_access_and_download_urls(data_dict: Dict[str, Any], current: Dict[str, Any] | None = None) -> None:
    """
    - Κατά την αποθήκευση πόρου, αν το access_url είναι κενό:
      - Αν ο τύπος του resource είναι upload ή tabledesigner:
        - παίρνει το url του πόρου (resource.url)
        - ή το url του dataset (χτισμένο βάσει name), γιατί δεν θα υπάρχουν ids
      - Σε διαφορετική περίπτωση: γεμίζει με το url του πόρου (resource.url)

    - Κατά την αποθήκευση πόρου, αν το download_url είναι κενό:
      - συμπληρώνεται με το access_url (όπως θα γεμίζει και αυτό)

    Σημείωση για update:
    - Αν δεν έρθει πεδίο στο payload, διατηρούμε την υπάρχουσα τιμή (για να μην «χαθεί»).
    """
    current = current or {}

    if 'access_url' not in data_dict and not _is_blank(current.get('access_url')):
        data_dict['access_url'] = current.get('access_url')
    if 'download_url' not in data_dict and not _is_blank(current.get('download_url')):
        data_dict['download_url'] = current.get('download_url')

    access_url = data_dict.get('access_url')
    if _is_blank(access_url):
        candidate_resource_url = data_dict.get('url')
        if _is_blank(candidate_resource_url):
            candidate_resource_url = current.get('url')

        if _is_upload_or_tabledesigner_resource(data_dict, current=current):
            if not _is_blank(candidate_resource_url):
                data_dict['access_url'] = candidate_resource_url
            else:
                dataset_name = _get_dataset_name_from_package_id(data_dict.get('package_id') or current.get('package_id'))
                if dataset_name:
                    data_dict['access_url'] = _build_dataset_url(dataset_name)
        else:
            if not _is_blank(candidate_resource_url):
                data_dict['access_url'] = candidate_resource_url

    download_url = data_dict.get('download_url')
    if _is_blank(download_url):
        final_access_url = data_dict.get('access_url')
        if not _is_blank(final_access_url):
            data_dict['download_url'] = final_access_url


def _current_package_for_hvd_sync(context: Context, data_dict: Dict[str, Any]) -> Dict[str, Any] | None:
    package_id = data_dict.get('id') or data_dict.get('name')
    if _is_blank(package_id):
        return None

    try:
        show_context = dict(context, ignore_auth=True)
        show_context.pop('schema', None)
        return toolkit.get_action('package_show')(
            show_context,
            {'id': package_id},
        )
    except Exception as e:
        log.debug('Could not load current package for HVD legislation sync: %r', e)
        return None


def _drop_read_only_relationship_fields(data_dict: Dict[str, Any]) -> None:
    """
    Relationships are exposed in package_show for API visibility, but they are
    managed by the dedicated package relationship actions, not package_update.
    """
    data_dict.pop('relationships_as_subject', None)
    data_dict.pop('relationships_as_object', None)


@toolkit.chained_action
def package_create(original_action, context, data_dict):
    """
    Συγχρονίζει την HVD εφαρμοστέα νομοθεσία στη δημιουργία dataset/data-service.
    """
    data_dict.pop(HVD_CATEGORY_FORM_PRESENT_FIELD, None)
    sync_package_hvd_applicable_legislation(data_dict)
    return original_action(context, data_dict)


@toolkit.chained_action
def package_update(original_action, context, data_dict):
    """
    Συγχρονίζει την HVD εφαρμοστέα νομοθεσία στην ενημέρωση dataset/data-service.
    """
    _drop_read_only_relationship_fields(data_dict)
    hvd_category_form_present = bool(
        data_dict.pop(HVD_CATEGORY_FORM_PRESENT_FIELD, None)
    )
    current_package = _current_package_for_hvd_sync(context, data_dict)
    sync_package_hvd_applicable_legislation(
        data_dict,
        current_package=current_package,
        missing_hvd_category_means_removed=hvd_category_form_present,
    )
    return original_action(context, data_dict)


@toolkit.chained_action
def resource_create(original_action, context, data_dict):
    """
    Προσυμπλήρωση access_url / download_url κατά το save (resource_create).
    """
    _ensure_access_and_download_urls(data_dict)
    return original_action(context, data_dict)


@toolkit.chained_action
def resource_update(original_action, context, data_dict):
    """
    Προσυμπλήρωση access_url / download_url κατά το save (resource_update).
    """
    current = {}
    resource_id = data_dict.get('id') or data_dict.get('resource_id')
    if not _is_blank(resource_id):
        try:
            current = toolkit.get_action('resource_show')(context, {'id': resource_id})
        except Exception:
            current = {}

    _ensure_access_and_download_urls(data_dict, current=current)
    return original_action(context, data_dict)


# Define some shortcuts
_get_action = logic.get_action
_check_access = logic.check_access
ValidationError = logic.ValidationError
NotFound = logic.NotFound

def organization_list_with_user_extras(context: Dict[str, Any], data_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a list of organizations with full user information including extras.

    Only sysadmins can access this action.

    Args:
        context: CKAN context
        data_dict: Can contain 'all_fields', 'include_extras', 'include_users'

    Returns:
        List of organizations with enriched user information
    """
    # Check if user has permission
    toolkit.check_access('organization_list_with_user_extras', context, data_dict)

    # Get the original organization list
    org_list = toolkit.get_action('organization_list')(
        context,
        {
            'all_fields': True,
            'include_extras': True,
            'include_users': True
        }
    )

    # Enrich user information for each organization
    for org in org_list:
        if 'users' in org:
            enriched_users = []
            for user in org['users']:
                try:
                    full_user = toolkit.get_action('user_show')(
                        context,
                        {
                            'id': user['id'],
                            'include_plugin_extras': True
                        }
                    )
                    enriched_users.append(full_user)
                except toolkit.ObjectNotFound:
                    continue
            org['users'] = enriched_users

    return org_list


def user_organization_capacity(context: Dict[str, Any], data_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Check if a user with given sub ID is a member of specified organization and return their capacity.

    Args:
        context: CKAN context
        data_dict: Must contain:
            - org_id: Organization ID or name
            - sub: User's sub ID from Keycloak

    Returns:
        dict with:
            - is_member: boolean indicating if user is member
            - capacity: user's role in organization (if member)
            - user_found (bool): True if user was found

    Raises:
        NotAuthorized: If the user is not a sysadmin
        ValidationError: If required parameters are missing
        ObjectNotFound: If the organization doesn't exist
    """
    # Check if user has permission (only sysadmins)
    if not toolkit.check_access('sysadmin', context, data_dict):
        raise toolkit.NotAuthorized('Only system administrators can perform this action')

    org_id = toolkit.get_or_bust(data_dict, 'org_id')
    sub = toolkit.get_or_bust(data_dict, 'sub')

    # Get organization with users
    try:
        org = toolkit.get_action('organization_show')(
            {'ignore_auth': True},
            {
                'id': org_id,
                'include_users': True
            }
        )
    except toolkit.ObjectNotFound:
        raise toolkit.ValidationError('Organization not found')

    result = {
        'is_member': False,
        'capacity': None,
        'user_found': False
    }

    if 'users' in org:
        for user in org['users']:
            try:
                user_info = toolkit.get_action('user_show')(
                    {'ignore_auth': True},
                    {
                        'id': user['id'],
                        'include_plugin_extras': True
                    }
                )

                # Check if this user has matching sub in plugin_extras
                plugin_extras = user_info.get('plugin_extras', {})
                if plugin_extras.get('sub') == sub:
                    result['is_member'] = True
                    result['capacity'] = user.get('capacity')
                    result['user_found'] = True
                    break

            except toolkit.ObjectNotFound:
                continue
            except Exception as e:
                log.error(f"Unexpected error while checking user {user.get('id')}: {str(e)}")
                continue

    return result


def organization_member_create_custom(context, data_dict):
    '''
    Custom organization_member_create που παρακάμπτει το member creation
    αν το username είναι ο default user
    '''

    # Ελέγχουμε αν είναι ο default site user
    username = data_dict.get('username', '')

    if username == 'default':
        # Έλεγχος αν έρχεται από notification context
        if context.get('skip_member_creation'):
            log.info(f"Skipping member creation for default user in notification context")
            # Επιστρέφουμε fake membership response
            return {
                'group_id': data_dict.get('id'),
                'table_name': 'user',
                'table_id': 'default',  # Hardcoded default
                'capacity': data_dict.get('role', 'member'),
                'state': 'notification_sent'  # Custom state
            }

    # Κανονικό member creation για άλλες περιπτώσεις
    from ckan.logic.action.create import organization_member_create as original_org_member_create
    return original_org_member_create(context, data_dict)

def user_invite_notify(context, data_dict):
    '''
    Αντικατάσταση του user_invite - στέλνει μόνο email ειδοποίηση.
    '''

    # Χρησιμοποιούμε την αρχική authorization του user_invite
    toolkit.check_access('user_invite', context, data_dict)

    # Χρησιμοποιούμε το αρχικό schema για συμβατότητα
    schema = context.get('schema', ckan.logic.schema.default_user_invite_schema())

    data, errors = _validate(data_dict, schema, context)
    if errors:
        raise toolkit.ValidationError(errors)

    # Παίρνουμε πληροφορίες για την ομάδα/οργανισμό
    model = context['model']
    group = model.Group.get(data['group_id'])
    if not group:
        raise toolkit.ObjectNotFound(_('Group not found'))

    # Παίρνουμε πληροφορίες για τον οργανισμό
    org_or_group = 'organization' if group.is_organization else 'group'
    group_dict = toolkit.get_action(f'{org_or_group}_show')(
        context, {'id': data['group_id']}
    )

    # Στέλνουμε το email ειδοποίησης
    try:
        _send_registration_notification_email(
            recipient_email=data['email'],
            group_dict=group_dict,
            role=data['role']
        )

        # Προσθήκη flash message
        h.flash_success(_('Email ειδοποίησης στάλθηκε επιτυχώς στο {0}').format(data['email']))

        # Σηματοδοτούμε ότι δεν θέλουμε member creation
        context['skip_member_creation'] = True

        # Παίρνουμε τον default site user
        site_user = toolkit.get_action('get_site_user')({'ignore_auth': True}, {})

        # Επιστρέφουμε τον site user με custom state
        site_user['state'] = 'notification_sent'
        site_user['target_email'] = data['email']  # Κρατάμε το πραγματικό email

        return site_user

    except Exception as error:
        # Όμοια με το αρχικό user_invite, πετάμε ValidationError
        message = _('Error sending registration notification email: {0}').format(error)
        raise toolkit.ValidationError(message)

def user_invite_waiting_keycloak_user(context: Context,
                                      data_dict: DataDict) -> ActionResult.UserInvite:
    '''Invite a new user.

    You must be authorized to create group members.

    :param email: the email of the user to be invited to the group
    :type email: string
    :param group_id: the id or name of the group
    :type group_id: string
    :param role: role of the user in the group. One of ``member``, ``editor``,
        or ``admin``
    :type role: string
    :param send_email: (optional) αν θα σταλεί email πρόσκλησης (default: False)
    :type send_email: bool

    :returns: the newly created user
    :rtype: dictionary
    '''
    _check_access('user_invite', context, data_dict)

    schema = context.get('schema',
                         ckan.logic.schema.default_user_invite_schema())
    data, errors = _validate(data_dict, schema, context)
    if errors:
        raise ValidationError(errors)

    # 1. Ελέγχουμε αν υπάρχει ορισμένη τιμή στο ckan.ini
    config_send_email = toolkit.config.get('ckanext.data_gov_gr.user_invite.waiting_keycloak.send_email')

    if config_send_email is not None:
        # Αν υπάρχει στο config, την επιβάλλουμε (υπερτερεί όλων)
        send_email = toolkit.asbool(config_send_email)
    else:
        # 2. Αν δεν υπάρχει στο config, κοιτάμε το data_dict
        # Αν δεν δοθεί, προεπιλογή False
        extras = data.get('__extras') or {}
        send_email_raw = extras.get('send_email', False)
        send_email = toolkit.asbool(send_email_raw)

    model = context['model']
    group = model.Group.get(data['group_id'])
    if not group:
        raise NotFound()

    # name = _get_random_username_from_email(data['email'])
    name = data['email']

    data['name'] = name
    # send the proper schema when creating a user from here
    # so the password field would be ignored.
    invite_schema = ckan.logic.schema.create_user_for_user_invite_schema()

    data['state'] = model.State.PENDING
    user_dict = _get_action('user_create')(
        Context(context, schema=invite_schema, ignore_auth=True),
        data)
    user = model.User.get(user_dict['id'])
    assert user
    member_dict = {
        'username': user.id,
        'id': data['group_id'],
        'role': data['role']
    }

    org_or_group = 'organization' if group.is_organization else 'group'
    _get_action(f'{org_or_group}_member_create')(context, member_dict)
    group_dict = _get_action(f'{org_or_group}_show')(
        context, {'id': data['group_id']})

    if send_email:
        try:
            _send_invite_email_waiting_keycloak_user(user, group_dict, data['role'])
        except (socket_error, mailer.MailerException) as error:
            # Email could not be sent, delete the pending user

            _get_action('user_delete')(context, {'id': user.id})

            message = _(
                'Error sending the invite email, '
                'the user was not created: {0}').format(error)
            raise ValidationError(message)

    # Role στα ελληνικά
    role_translations = {
        'member': 'Μέλος',
        'editor': 'Συντάκτης',
        'admin': 'Διαχειριστής'
    }
    role_gr = role_translations.get(data['role'], data['role'])

    if send_email:
        h.flash_success(_('Το email ένταξης με ρόλο "{0}" στάλθηκε επιτυχώς στο {1}. Μόλις ο χρήστης '
                          'εγγραφεί/συνδεθεί με το συγκεκριμένο email που προσκλήθηκε '
                          'θα έχει τα δικαιώματα του ρόλου με τον οποίο προσκλήθηκε.').format(role_gr, data['email']))
    else:
        h.flash_success(_('Ο χρήστης δημιουργήθηκε με ρόλο "{0}" χωρίς αποστολή email στο {1}.').format(role_gr, data['email']))

    return model_dictize.user_dictize(user, context)

def _send_invite_email_waiting_keycloak_user(user, group_dict, role):
    '''Στέλνει email πρόσκλησης για χρήστη με ενεργό membership που θα συνδεθεί μέσω keycloak '''

    # Πληροφορίες οργανισμού
    org_name = group_dict.get('display_name', group_dict.get('title', group_dict.get('name', '')))
    org_type = 'οργανισμό' if group_dict.get('is_organization') else 'ομάδα'
    contact_email = _get_organization_contact_email(group_dict)

    # Δημιουργία URL για τη σελίδα του οργανισμού στο CKAN
    site_url = toolkit.config.get('ckan.site_url', '').rstrip('/')
    org_name_for_url = group_dict.get('name', '')
    org_url = f"{site_url}/organization/{org_name_for_url}" if org_name_for_url else ''

    # Role στα ελληνικά
    role_translations = {
        'member': 'μέλος',
        'editor': 'συντάκτης',
        'admin': 'διαχειριστής'
    }
    role_gr = role_translations.get(role, role)

    site_name = toolkit.config.get('ckan.site_title', '')

    # Template variables
    extra_vars = {
        'user_name': user.name,
        'user_display_name': user.display_name or user.fullname or user.name,
        'user_email': user.email,
        'org_name': org_name,
        'org_type': org_type,
        'contact_email': contact_email,
        'org_url': org_url,
        'role_gr': role_gr,
        'site_name': site_name,
        'site_url': toolkit.config.get('ckan.site_url', ''),
        'login_url': toolkit.url_for('/user/sso', _external=True)
    }

    subject = f"Έχετε προσκληθεί στον {org_type} {org_name} - {site_name}"

    use_html_links = toolkit.asbool(
        toolkit.config.get(
            'ckanext.data_gov_gr.user_invite.waiting_keycloak.html_links',
            False
        )
    )

    if use_html_links:
        body_text = toolkit.render('emails/user_invite_waiting_keycloak.txt', extra_vars)
        body_html = toolkit.render('emails/user_invite_waiting_keycloak.html', extra_vars)
        mail_recipient(
            recipient_name=user.display_name or user.fullname or user.name,
            recipient_email=user.email,
            subject=subject,
            body=body_text,
            body_html=body_html
        )
    else:
        body = toolkit.render('emails/user_invite_waiting_keycloak.txt', extra_vars)
        mail_recipient(
            recipient_name=user.display_name or user.fullname or user.name,
            recipient_email=user.email,
            subject=subject,
            body=body
        )

def _send_registration_notification_email(recipient_email, group_dict, role):
    '''Στέλνει το email ειδοποίησης'''

    # Πληροφορίες οργανισμού
    org_name = group_dict.get('display_name', group_dict.get('title', group_dict.get('name', '')))
    org_type = 'οργανισμό' if group_dict.get('is_organization') else 'ομάδα'
    contact_email = _get_organization_contact_email(group_dict)
    org_url = group_dict.get('url', '')

    # Role στα ελληνικά
    role_translations = {
        'member': 'μέλος',
        'editor': 'συντάκτης',
        'admin': 'διαχειριστής'
    }
    role_gr = role_translations.get(role, role)
    site_name = toolkit.config.get('ckan.site_title', '')

    # Template variables
    extra_vars = {
        'org_name': org_name,
        'org_type': org_type,
        'contact_email': contact_email,
        'org_url': org_url,
        'role_gr': role_gr,
        'site_name': site_name
    }

    subject = f"Πρόσκληση εγγραφής στην πλατφόρμα { site_name } - {org_name}"

    # Render το template
    body = toolkit.render('emails/user_invite_notification.txt', extra_vars)

    mail_recipient(
        recipient_name="",
        recipient_email=recipient_email,
        subject=subject,
        body=body
    )

def _get_organization_contact_email(group_dict):
    '''Παίρνει το contact email του οργανισμού αν υπάρχει'''
    return group_dict.get('email')

def check_user_org_permission(context: Dict[str, Any], data_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ελέγχει αν ένας χρήστης (μέσω API token) έχει δικαιώματα εκδότη σε έναν οργανισμό.

    :param organization_id: Το ID του οργανισμού
    :type organization_id: string

    :returns: Αποτέλεσμα ελέγχου εξουσιοδότησης
    :rtype: dictionary
    """

    # Validation
    organization_id = data_dict.get('organization_id')
    if not organization_id:
        raise toolkit.ValidationError({'organization_id': ['Organization ID is required']})

    # Παίρνουμε το token από το Authorization header
    token = request.headers.get('Authorization', '')
    if not token:
        return {
            'success': False,
            'message': 'No authorization token provided',
            'user_id': None
        }

    # Επικύρωση token και λήψη χρήστη
    user = get_user_from_token(token)
    if not user:
        return {
            'success': False,
            'message': 'Invalid or expired token',
            'user_id': None
        }

    # Έλεγχος ύπαρξης οργανισμού
    try:
        toolkit.get_action('organization_show')(
            {'ignore_auth': True},
            {'id': organization_id}
        )
    except toolkit.ObjectNotFound:
        return {
            'success': False,
            'message': 'Organization not found',
            'user_id': user.id
        }

    # Έλεγχος δικαιωμάτων εκδότη στον οργανισμό
    has_permission = authz._has_user_permission_for_groups(
        user.id,
        'create_dataset',  # Permission που χρειάζεται ένας εκδότης
        [organization_id],
        capacity='editor'  # Ελέγχουμε συγκεκριμένα για editor role
    ) or authz._has_user_permission_for_groups(
        user.id,
        'create_dataset',
        [organization_id],
        capacity='admin'  # Ή admin role
    )

    return {
        'success': has_permission,
        'message': 'User authorized' if has_permission else 'User not authorized for this organization',
        'user_id': user.id,
        'username': user.name,
        'organization_id': organization_id
    }

# ----------------------------------------------------------------------------------------------

# Define some shortcuts

_select = sqlalchemy.sql.select
_or_ = sqlalchemy.or_
_and_ = sqlalchemy.and_
_func = sqlalchemy.func
_case = sqlalchemy.case
_null = sqlalchemy.null

def organization_list(context: Context,
                      data_dict: DataDict) -> ActionResult.OrganizationList:
    _check_access('organization_list', context, data_dict)
    data_dict['groups'] = data_dict.pop('organizations', [])
    data_dict.setdefault('type', 'organization')
    return _group_or_org_list(context, data_dict, is_org=True)

def _group_or_org_list(
        context: Context, data_dict: DataDict, is_org: bool = False):
    model = context['model']
    api = context.get('api_version')
    groups = data_dict.get('groups')
    group_type = data_dict.get('type', 'group')
    ref_group_by = 'id' if api == 2 else 'name'
    pagination_dict = {}
    limit = data_dict.get('limit')
    if limit:
        pagination_dict['limit'] = data_dict['limit']
    offset = data_dict.get('offset')
    if offset:
        pagination_dict['offset'] = data_dict['offset']
    if pagination_dict:
        pagination_dict, errors = _validate(
            data_dict, ckan.logic.schema.default_pagination_schema(), context)
        if errors:
            raise ValidationError(errors)
    sort = data_dict.get('sort') or config.get('ckan.default_group_sort')
    q = data_dict.get('q', '').strip()

    all_fields = asbool(data_dict.get('all_fields', None))

    if all_fields:
        # all_fields is really computationally expensive, so need a tight limit
        try:
            max_limit = config.get(
                'ckan.group_and_organization_list_all_fields_max')
        except ValueError:
            max_limit = 25
    else:
        try:
            max_limit = config.get('ckan.group_and_organization_list_max')
        except ValueError:
            max_limit = 1000

    if limit is None or int(limit) > max_limit:
        limit = max_limit

    # order_by deprecated in ckan 1.8
    # if it is supplied and sort isn't use order_by and raise a warning
    order_by = data_dict.get('order_by', '')
    if order_by:
        log.warn('`order_by` deprecated please use `sort`')
        if not data_dict.get('sort'):
            sort = order_by

    requested_relevance = bool(
        data_dict.get('sort') and data_dict['sort'].strip() == 'relevance'
    )
    if requested_relevance:
        sort = config.get('ckan.default_group_sort')
    elif not data_dict.get('sort') and is_org and context.get('for_view') and not q:
        if (
            organization_stats.organization_profile_visit_sort_default_enabled()
            and organization_stats.organization_profile_visit_sort_available()
        ):
            sort = 'visits desc'
        else:
            sort = 'dataset_count desc'

    # if the sort is packages and no sort direction is supplied we want to do a
    # reverse sort to maintain compatibility.
    if sort.strip() == 'dataset_count':
        sort = 'dataset_count desc'
    elif sort.strip() in ('packages', 'package_count'):
        sort = 'package_count desc'

    allowed_sort_fields = ['name', 'packages', 'package_count', 'title']
    if is_org:
        allowed_sort_fields.append('dataset_count')
        allowed_sort_fields.append('visits')

    sort_info = _unpick_search(sort,
                               allowed_fields=allowed_sort_fields,
                               total=1)

    if sort_info and sort_info[0][0] == 'package_count':
        query = model.Session.query(model.Group.id,
                                    model.Group.name,
                                    sqlalchemy.func.count(model.Group.id))

        query = query.filter(model.Member.group_id == model.Group.id) \
            .filter(model.Member.table_id == model.Package.id) \
            .filter(model.Member.table_name == 'package') \
            .filter(model.Package.state == 'active')
    else:
        query = model.Session.query(model.Group.id,
                                    model.Group.name,
                                    model.Group.title)

    query = query.filter(model.Group.state == 'active')

    if groups:
        groups = aslist(groups, sep=",")
        query = query.filter(model.Group.name.in_(groups))

    from sqlalchemy import func
    import ckan.model.misc as misc

    def _norm(expr):
        return func.translate(func.unaccent(func.lower(expr)), 'ς', 'σ')

    if q:
        q_escaped = misc.escape_sql_like_special_characters(q, escape='\\')
        like_term = '%{0}%'.format(q_escaped)
        qn = q.strip()

        base_like = _or_(
            _norm(model.Group.name).like(_norm(like_term), escape='\\'),
            _norm(model.Group.title).like(_norm(like_term), escape='\\'),
            _norm(model.Group.description).like(_norm(like_term), escape='\\'),
        )

        score_name = func.word_similarity(_norm(model.Group.name), _norm(qn))
        score_title = func.word_similarity(_norm(model.Group.title), _norm(qn))
        score_desc = func.word_similarity(_norm(model.Group.description), _norm(qn))

        if len(qn) >= 3:
            fuzzy_match = _or_(
                score_name > 0.35,
                score_title > 0.35,
                score_desc > 0.35,
            )
            query = query.filter(_or_(base_like, fuzzy_match))

            if (not data_dict.get('sort') or requested_relevance) and is_org:
                query = query.order_by(sqlalchemy.desc(
                    func.greatest(
                        score_title * 1.2,
                        score_name * 1.0,
                        score_desc * 0.8
                    )
                ))
        else:
            query = query.filter(base_like)

    query = query.filter(model.Group.is_organization == is_org)
    query = query.filter(model.Group.type == group_type)

    uses_visits_sort = bool(
        sort_info and sort_info[0][0] == 'visits'
    )
    uses_dataset_count_sort = bool(
        sort_info and sort_info[0][0] == 'dataset_count'
    )

    if uses_visits_sort:
        sort_direction = sort_info[0][1]
        cache_key = (
            '_organization_profile_visits_cache',
            group_type,
            is_org,
            q,
            tuple(groups) if isinstance(groups, list) else groups,
        )
        cache = context.get(cache_key)

        def _normalized_label(value: Any) -> str:
            return str(value or '').lower().replace('ς', 'σ')

        if cache is None:
            candidate_rows = query.order_by(None).with_entities(
                model.Group.id,
                model.Group.name,
                model.Group.title,
            ).all()
            candidate_names = [row.name for row in candidate_rows]
            visit_counts = (
                organization_stats
                .get_organization_profile_visit_counts_for_org_names(candidate_names)
            )
            nonzero_rows = [
                row for row in candidate_rows
                if visit_counts.get(row.name, 0) > 0
            ]
            zero_rows = [
                row for row in candidate_rows
                if visit_counts.get(row.name, 0) <= 0
            ]

            nonzero_desc = sorted(
                nonzero_rows,
                key=lambda row: (
                    -visit_counts.get(row.name, 0),
                    _normalized_label(row.title or row.name),
                    _normalized_label(row.name),
                ),
            )
            nonzero_asc = sorted(
                nonzero_rows,
                key=lambda row: (
                    visit_counts.get(row.name, 0),
                    _normalized_label(row.title or row.name),
                    _normalized_label(row.name),
                ),
            )
            zero_asc = sorted(
                zero_rows,
                key=lambda row: (
                    _normalized_label(row.title or row.name),
                    _normalized_label(row.name),
                ),
            )

            cache = {
                'visit_counts': visit_counts,
                'nonzero_ids_desc': [row.id for row in nonzero_desc],
                'nonzero_ids_asc': [row.id for row in nonzero_asc],
                'zero_ids_asc': [row.id for row in zero_asc],
                'nonzero_count': len(nonzero_rows),
                'total_count': len(candidate_rows),
            }
            context[cache_key] = cache

        total_count = int(cache['total_count'])
        nonzero_ids_desc = cache['nonzero_ids_desc']
        nonzero_ids_asc = cache['nonzero_ids_asc']
        zero_ids_asc = cache['zero_ids_asc']
        nonzero_count = int(cache['nonzero_count'])
        zero_count = max(0, total_count - nonzero_count)

        limit_int = int(limit or max_limit)
        offset_int = int(offset or 0)

        page_ids: list[str] = []
        if sort_direction == 'desc':
            page_ids = nonzero_ids_desc[offset_int: offset_int + limit_int]
            if len(page_ids) < limit_int:
                zero_offset = max(0, offset_int - len(nonzero_ids_desc))
                page_ids.extend(
                    zero_ids_asc[zero_offset: zero_offset + limit_int - len(page_ids)]
                )
        else:
            if offset_int < zero_count:
                page_ids = zero_ids_asc[offset_int: offset_int + limit_int]
                if len(page_ids) < limit_int:
                    page_ids.extend(nonzero_ids_asc[: (limit_int - len(page_ids))])
            else:
                nonzero_offset = max(0, offset_int - zero_count)
                page_ids = nonzero_ids_asc[nonzero_offset: nonzero_offset + limit_int]

        if context.get('for_view') and not all_fields:
            return organization_stats.CountOnlySequence(total_count)

        if all_fields:
            group_list = []
            for org_id in page_ids:
                data_dict['id'] = org_id
                for key in ('include_extras', 'include_tags', 'include_users',
                            'include_groups', 'include_followers'):
                    if key not in data_dict:
                        data_dict[key] = False

                group_list.append(logic.get_action('organization_show')(context, data_dict))
            return group_list

        rows = model.Session.query(model.Group.id, model.Group.name) \
            .filter(model.Group.id.in_(page_ids)).all()
        id_to_name = {row.id: row.name for row in rows}
        if ref_group_by == 'id':
            return list(page_ids)
        return [id_to_name.get(org_id) for org_id in page_ids if id_to_name.get(org_id)]

    if uses_dataset_count_sort:
        sort_direction = sort_info[0][1]
        cache_key = (
            '_dataset_count_cache',
            group_type,
            is_org,
            q,
            tuple(groups) if isinstance(groups, list) else groups,
        )
        cache = context.get(cache_key)

        def _normalized_label(value: Any) -> str:
            return str(value or '').lower().replace('ς', 'σ')

        if cache is None:
            facet_items = organization_stats.get_public_dataset_facet_items()
            facet_counts: dict[str, int] = {}
            for item in facet_items:
                item = item or {}
                org_id = item.get('name')
                if not org_id:
                    continue
                facet_counts[org_id] = int(item.get('count') or 0)

            nonzero_rows = []
            if facet_counts:
                nonzero_rows = query.with_entities(
                    model.Group.id,
                    model.Group.name,
                    model.Group.title,
                ).filter(model.Group.id.in_(list(facet_counts.keys()))).all()

            nonzero_desc = sorted(
                nonzero_rows,
                key=lambda row: (
                    -facet_counts.get(row.id, 0),
                    _normalized_label(row.title or row.name),
                    _normalized_label(row.name),
                ),
            )
            nonzero_asc = sorted(
                nonzero_rows,
                key=lambda row: (
                    facet_counts.get(row.id, 0),
                    _normalized_label(row.title or row.name),
                    _normalized_label(row.name),
                ),
            )

            total_count = query.order_by(None).count()
            cache = {
                'facet_counts': facet_counts,
                'nonzero_ids_desc': [row.id for row in nonzero_desc],
                'nonzero_ids_asc': [row.id for row in nonzero_asc],
                'nonzero_count': len(nonzero_rows),
                'total_count': total_count,
            }
            context[cache_key] = cache

        total_count = int(cache['total_count'])
        nonzero_ids_desc = cache['nonzero_ids_desc']
        nonzero_ids_asc = cache['nonzero_ids_asc']
        nonzero_count = int(cache['nonzero_count'])
        zero_count = max(0, total_count - nonzero_count)

        limit_int = int(limit or max_limit)
        offset_int = int(offset or 0)

        def _zero_ids_page(offset_zero: int, limit_zero: int) -> list[str]:
            zero_query = query.with_entities(model.Group.id)
            if nonzero_ids_desc:
                zero_query = zero_query.filter(~model.Group.id.in_(nonzero_ids_desc))
            zero_query = zero_query.order_by(
                sqlalchemy.asc(_norm(func.coalesce(
                    model.Group.title,
                    model.Group.name,
                ))),
                sqlalchemy.asc(_norm(model.Group.name)),
            )
            if offset_zero:
                zero_query = zero_query.offset(offset_zero)
            if limit_zero:
                zero_query = zero_query.limit(limit_zero)
            return [row.id for row in zero_query.all()]

        page_ids: list[str] = []
        if sort_direction == 'desc':
            page_ids = nonzero_ids_desc[offset_int: offset_int + limit_int]
            if len(page_ids) < limit_int:
                zero_offset = max(0, offset_int - len(nonzero_ids_desc))
                page_ids.extend(
                    _zero_ids_page(zero_offset, limit_int - len(page_ids))
                )
        else:
            if offset_int < zero_count:
                page_ids = _zero_ids_page(offset_int, limit_int)
                if len(page_ids) < limit_int:
                    page_ids.extend(nonzero_ids_asc[: (limit_int - len(page_ids))])
            else:
                nonzero_offset = max(0, offset_int - zero_count)
                page_ids = nonzero_ids_asc[nonzero_offset: nonzero_offset + limit_int]

        if context.get('for_view') and not all_fields:
            return organization_stats.CountOnlySequence(total_count)

        if all_fields:
            group_list = []
            for org_id in page_ids:
                data_dict['id'] = org_id
                for key in ('include_extras', 'include_tags', 'include_users',
                            'include_groups', 'include_followers'):
                    if key not in data_dict:
                        data_dict[key] = False

                group_list.append(logic.get_action('organization_show')(context, data_dict))
            return group_list

        # all_fields=False: return id or name in the correct order
        rows = model.Session.query(model.Group.id, model.Group.name) \
            .filter(model.Group.id.in_(page_ids)).all()
        id_to_name = {row.id: row.name for row in rows}
        if ref_group_by == 'id':
            return list(page_ids)
        return [id_to_name.get(org_id) for org_id in page_ids if id_to_name.get(org_id)]

    if sort_info:
        sort_field = sort_info[0][0]
        sort_direction = sort_info[0][1]
        sort_model_field: Any = sqlalchemy.func.count(model.Group.id)
        if sort_field == 'package_count':
            query = query.group_by(model.Group.id, model.Group.name)
        elif sort_field == 'name':
            sort_model_field = model.Group.name
        elif sort_field == 'title':
            sort_model_field = model.Group.title

        if sort_direction == 'asc':
            query = query.order_by(sqlalchemy.asc(sort_model_field))
        else:
            query = query.order_by(sqlalchemy.desc(sort_model_field))

    if limit:
        query = query.limit(limit)
    if offset:
        query = query.offset(offset)

    groups = query.all()

    if all_fields:
        action = 'organization_show' if is_org else 'group_show'
        group_list = []
        for group in groups:
            data_dict['id'] = group.id
            for key in ('include_extras', 'include_tags', 'include_users',
                        'include_groups', 'include_followers'):
                if key not in data_dict:
                    data_dict[key] = False

            group_list.append(logic.get_action(action)(context, data_dict))
    else:
        group_list = [getattr(group, ref_group_by) for group in groups]

    return group_list

def _unpick_search(
        sort: str,
        allowed_fields: Optional['Container[str]'] = None,
        total: Optional[int] = None) -> list[tuple[str, str]]:
    ''' This is a helper function that takes a sort string
    eg 'name asc, last_modified desc' and returns a list of
    split field order eg [('name', 'asc'), ('last_modified', 'desc')]
    allowed_fields can limit which field names are ok.
    total controls how many sorts can be specifed '''
    sorts: list[tuple[str, str]] = []
    split_sort = sort.split(',')
    for part in split_sort:
        split_part = part.strip().split()
        field = split_part[0]
        if len(split_part) > 1:
            order = split_part[1].lower()
        else:
            order = 'asc'
        if allowed_fields:
            if field not in allowed_fields:
                raise ValidationError({
                    'message': 'Cannot sort by field `%s`' % field})
        if order not in ['asc', 'desc']:
            raise ValidationError({
                'message': 'Invalid sort direction `%s`' % order})
        sorts.append((field, order))
    if total and len(sorts) > total:
        raise ValidationError(
            'Too many sort criteria provided only %s allowed' % total)
    return sorts

# ----------------------------------------------------------------------------------------------
