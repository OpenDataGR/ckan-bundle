import logging

import ckan.lib.uploader as uploader
import ckan.lib.helpers as h
import ckan.model as model
import ckan.plugins.toolkit as toolkit
from ckan.logic.converters import convert_user_name_or_id_to_id
from ckan.lib.navl.dictization_functions import validate
from ckan.lib.mailer import mail_recipient
from sqlalchemy import text

import ckanext.showcase.logic.converters as showcase_converters
import ckanext.showcase.logic.schema as showcase_schema
from ckanext.showcase.model import ShowcasePackageAssociation, ShowcaseAdmin
import datetime
import hashlib

convert_package_name_or_id_to_title_or_name = \
    showcase_converters.convert_package_name_or_id_to_title_or_name
showcase_package_association_create_schema = \
    showcase_schema.showcase_package_association_create_schema
showcase_admin_add_schema = showcase_schema.showcase_admin_add_schema

log = logging.getLogger(__name__)


def showcase_create(context, data_dict):
    '''Upload the image and continue with package creation.'''

    # force type to 'showcase'
    data_dict['type'] = 'showcase'
    upload = uploader.get_uploader('showcase')

    upload.update_data_dict(data_dict, 'image_url',
                            'image_upload', 'clear_upload')

    upload.upload(uploader.get_max_image_size())


    # Δημιουργία του name για το showcase
    now_str = datetime.datetime.now().isoformat()
    input_str = f";showcase-{now_str}"
    hex_digest = hashlib.sha1(input_str.encode()).hexdigest()[:8]  # Take first 8 chars for brevity

    data_dict["name"] = f"{hex_digest}"

    # Στην δημιουργία του showcase αν δεν είναι admin θα πρέπει να μπαίνει αυτόματατα κατάσταση έγκρισης αναμονής
    from ckanext.showcase.logic.auth import _is_showcase_admin
    if not _is_showcase_admin(context):
        data_dict['approval_status'] = 'pending'

    # Στην αποθήκευση του showcase επιτρέπουμε σε όλους τους συνδεδεμένους χρήστες να κάνουν προσθήκη εφαρμογής
    context['ignore_auth'] = True
    pkg = toolkit.get_action('package_create')(context, data_dict)

    try:

        # Ανάκτηση email του δημιουργού του showcase
        creator_email = get_email_from_id(context, pkg['creator_user_id'])

        # Ανάκτηση των emails των διαχειριστών βάσει παραμετροποίησης
        admins_emails = get_showcase_notification_emails()

        # Δημιουργία του URL του showcase
        from ckan.common import config
        site_url = config.get('ckan.site_url', 'http://localhost:5000')
        showcase_url = f"{site_url}/showcase/{pkg['name']}"

        # Αποστολή email σε όλους τους διαχειριστές
        for admin_email in admins_emails:
            send_email(context, admin_email, data_dict, showcase_url)

        # Αποστολή email στον δημιουργό
        if creator_email:
            send_email(context, creator_email, data_dict, showcase_url)

    except Exception as e:
        toolkit.error_shout(f"Email sending failed: {e}")

    return pkg


def showcase_package_association_create(context, data_dict):
    '''Create an association between a showcase and a package.

    :param showcase_id: id or name of the showcase to associate
    :type showcase_id: string

    :param package_id: id or name of the package to associate
    :type package_id: string
    '''

    context['ignore_auth'] = False
    try:
        toolkit.check_access('ckanext_showcase_package_association_create',
                           context, data_dict)
    except toolkit.NotAuthorized:
        return toolkit.abort(
            403, toolkit._('Not authorized to add package to showcase')
        )

    # validate the incoming data_dict
    validated_data_dict, errors = validate(
        data_dict, showcase_package_association_create_schema(), context)

    if errors:
        raise toolkit.ValidationError(errors)

    package_id, showcase_id = toolkit.get_or_bust(validated_data_dict,
                                                  ['package_id',
                                                   'showcase_id'])

    if ShowcasePackageAssociation.exists(package_id=package_id,
                                         showcase_id=showcase_id):
        raise toolkit.ValidationError(
            "ShowcasePackageAssociation with package_id '{0}' and showcase_id '{1}' already exists.".format(
                package_id, showcase_id
            ),
            error_summary=u"The package, {0}, is already in the showcase".format(
                convert_package_name_or_id_to_title_or_name(package_id, context)
            ),
        )

    # create the association
    return ShowcasePackageAssociation.create(package_id=package_id,
                                             showcase_id=showcase_id)


def showcase_admin_add(context, data_dict):
    '''Add a user to the list of showcase admins.

    :param username: name of the user to add to showcase user admin list
    :type username: string
    '''

    toolkit.check_access('ckanext_showcase_admin_add', context, data_dict)

    # validate the incoming data_dict
    validated_data_dict, errors = validate(
        data_dict, showcase_admin_add_schema(), context)

    username = toolkit.get_or_bust(validated_data_dict, 'username')
    try:
        user_id = convert_user_name_or_id_to_id(username, context)
    except toolkit.Invalid:
        raise toolkit.ObjectNotFound

    if errors:
        raise toolkit.ValidationError(errors)

    if ShowcaseAdmin.exists(user_id=user_id):
        raise toolkit.ValidationError("ShowcaseAdmin with user_id '{0}' already exists.".format(user_id),
                                      error_summary=u"User '{0}' is already a Showcase Admin.".format(username))

    # create showcase admin entry
    return ShowcaseAdmin.create(user_id=user_id)


def showcase_upload(context, data_dict):
    ''' Uploads images to be used in showcase content.

    '''
    toolkit.check_access('ckanext_showcase_upload', context, data_dict)

    upload = uploader.get_uploader('showcase_image')

    upload.update_data_dict(data_dict, 'image_url', 'upload', 'clear_upload')
    upload.upload(uploader.get_max_image_size())

    image_url = data_dict.get('image_url')
    if image_url and image_url[0:6] not in {'http:/', 'https:'}:
        image_url = h.url_for_static(
           'uploads/showcase_image/{}'.format(image_url),
            qualified=True
        )
    return {'url': image_url}

# Μέθοδος που ανακτά το username του χρήστη με βάση το id
def get_username_from_id(context, user_id):
    try:
        user = toolkit.get_action('user_show')(context, {'id': user_id})
        return user.get('name')  # or 'fullname' if you want full name
    except toolkit.ObjectNotFound:
        return None

# ------------------------------------------------------------------------------------------------------------------------

RECIPIENTS_MODE_CONFIG = 'ckanext.showcase.notification_recipients_mode'
CONFIGURED_EMAIL_CONFIG = 'ckanext.showcase.notification_email'
EXCLUDED_EMAILS_CONFIG = 'ckanext.showcase.notification_exclude_emails'

RECIPIENTS_MODE_ALL_ADMINS = 'all_admins'
RECIPIENTS_MODE_SHOWCASE_ADMINS = 'showcase_admins'
RECIPIENTS_MODE_CONFIGURED_ONLY = 'configured_email_only'

VALID_RECIPIENT_MODES = {
    RECIPIENTS_MODE_ALL_ADMINS,
    RECIPIENTS_MODE_SHOWCASE_ADMINS,
    RECIPIENTS_MODE_CONFIGURED_ONLY,
}


# Μέθοδος που ανακτά το email του χρήστη με βάση το id
def get_email_from_id(context, user_id):
    try:
        row = model.Session.execute(
            text("""
                SELECT lower(trim(email)) AS email
                FROM "user"
                WHERE id = :user_id
                  AND state = 'active'
                  AND email IS NOT NULL
            """),
            {'user_id': user_id}
        ).fetchone()

        return row[0] if row and row[0] else None
    except Exception:
        return None


def _normalize_email(email):
    if not email:
        return None

    email = email.strip().lower()
    return email or None


def _parse_email_list(raw_value):
    if not raw_value:
        return []

    raw_value = raw_value.replace(';', ',').replace('\n', ',')
    emails = []

    for item in raw_value.split(','):
        email = _normalize_email(item)
        if email:
            emails.append(email)

    return emails


def _get_notification_mode():
    mode = toolkit.config.get(
        RECIPIENTS_MODE_CONFIG,
        RECIPIENTS_MODE_ALL_ADMINS
    )
    mode = (mode or '').strip().lower()

    if mode not in VALID_RECIPIENT_MODES:
        log.warning(
            'Invalid value "%s" for %s. Falling back to "%s".',
            mode,
            RECIPIENTS_MODE_CONFIG,
            RECIPIENTS_MODE_ALL_ADMINS
        )
        return RECIPIENTS_MODE_ALL_ADMINS

    return mode


def _get_configured_notification_email():
    return _normalize_email(toolkit.config.get(CONFIGURED_EMAIL_CONFIG))


def _get_excluded_notification_emails():
    return set(_parse_email_list(toolkit.config.get(EXCLUDED_EMAILS_CONFIG, '')))


def _get_admin_emails(include_sysadmins=True, include_showcase_admins=True):
    admin_emails = set()

    conditions = []

    if include_sysadmins:
        conditions.append('u.sysadmin = true')

    if include_showcase_admins:
        conditions.append('sa.user_id IS NOT NULL')

    if not conditions:
        return admin_emails

    query = text("""
        SELECT DISTINCT lower(trim(u.email)) AS email
        FROM "user" u
        LEFT JOIN showcase_admin sa ON sa.user_id = u.id
        WHERE u.state = 'active'
          AND u.email IS NOT NULL
          AND ({conditions})
    """.format(conditions=' OR '.join(conditions)))

    rows = model.Session.execute(query).fetchall()

    for row in rows:
        if row[0]:
            admin_emails.add(row[0])

    return admin_emails


def get_showcase_notification_emails():
    recipients = set()

    mode = _get_notification_mode()
    configured_email = _get_configured_notification_email()
    excluded_emails = _get_excluded_notification_emails()

    if mode == RECIPIENTS_MODE_ALL_ADMINS:
        recipients.update(
            _get_admin_emails(
                include_sysadmins=True,
                include_showcase_admins=True
            )
        )

    elif mode == RECIPIENTS_MODE_SHOWCASE_ADMINS:
        recipients.update(
            _get_admin_emails(
                include_sysadmins=False,
                include_showcase_admins=True
            )
        )

    elif mode == RECIPIENTS_MODE_CONFIGURED_ONLY:
        if configured_email:
            recipients.add(configured_email)
        else:
            log.warning(
                'Notification mode is "%s" but no configured email was found in %s.',
                RECIPIENTS_MODE_CONFIGURED_ONLY,
                CONFIGURED_EMAIL_CONFIG
            )

    # Το configured email να προστίθεται πάντα όταν είναι δηλωμένο
    # εκτός αν είμαστε ήδη στο configured_email_only
    if mode != RECIPIENTS_MODE_CONFIGURED_ONLY and configured_email:
        recipients.add(configured_email)

    # Exclude list
    recipients = {
        email for email in recipients
        if email not in excluded_emails
    }

    return list(recipients)

# ------------------------------------------------------------------------------------------------------------------------

# Μέθοδος αποστολής email
def send_email(context, recipient, data_dict, showcase_url):
    mail_recipient(
        recipient_name="",
        recipient_email=recipient,
        subject=f"DATA GOV GR: Δημιουργήθηκε Showcase: '{data_dict['name']}'",
        body=f"Μια νέα επανάχρηση με όνομα '{data_dict['title']}' δημιουργήθηκε με επιτυχία. Μπορείτε να επισκεφθείτε την επανάχρησή σας εδώ για να ελέγξετε την κατάστασή της. URL: '{showcase_url}'"
    )
