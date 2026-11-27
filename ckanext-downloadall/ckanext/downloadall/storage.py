# -*- coding: utf-8 -*-
'''
Αποθήκευση του ZIP στο cloud storage (OD-857).

Κάθε build ανεβάζει το ZIP με νέο όνομα αρχείου. Με το ckanext-cloudstorage το
blob είναι resources/<resource id>/<όνομα αρχείου>, οπότε το προηγούμενο ZIP
μένει ως ξεχωριστό blob. Εδώ σβήνεται ακριβώς αυτό, μόνο αφού έχει αποθηκευτεί
επιτυχώς το νέο και βρεθεί στο storage με το σωστό μέγεθος. Δεν γίνεται ποτέ
διαγραφή με βάση πρόθεμα.

Χωρίς cloudstorage (τοπική αποθήκευση του CKAN) το αρχείο ενός πόρου έχει
πάντα την ίδια διαδρομή και αντικαθίσταται, οπότε δεν χρειάζεται διαγραφή.
'''
import logging
import posixpath
from urllib.parse import unquote

from ckan import plugins as p

log = logging.getLogger(__name__)


def upload_filename(resource):
    '''Το όνομα αρχείου ενός πόρου upload, όπως είναι αποθηκευμένο.'''
    if not resource or resource.get('url_type') != 'upload':
        return None
    url = (resource.get('url') or '').split('?', 1)[0].rstrip('/')
    return unquote(url.rsplit('/', 1)[-1]) or None


def blob_path(resource_id, filename):
    return posixpath.join('resources', resource_id, filename)


def cloudstorage_enabled():
    return p.plugin_loaded('cloudstorage')


def _cloud_storage():
    from ckanext.cloudstorage.storage import CloudStorage
    return CloudStorage()


def blob_verified(resource_id, filename, size=None):
    '''True αν το blob resources/<resource_id>/<filename> υπάρχει στο cloud
    storage και, όταν είναι γνωστό το size, έχει αυτό το μέγεθος. Ελέγχεται
    πριν σβηστούν τα blobs των προηγούμενων ZIP (handoff του OD-857, §5: το
    παλιό blob σβήνεται μόνο αφού επαληθευτεί το νέο).

    Χωρίς cloudstorage δεν σβήνεται κανένα blob, άρα δεν χρειάζεται έλεγχος.
    '''
    if not cloudstorage_enabled():
        return True
    if not filename:
        return False
    path = blob_path(resource_id, filename)
    try:
        from libcloud.storage.types import ObjectDoesNotExistError
        storage = _cloud_storage()
    except Exception:
        log.exception('Cloud storage is not available; cannot check %s', path)
        return False
    try:
        blob = storage.container.get_object(path)
    except ObjectDoesNotExistError:
        log.error('The DownloadAll ZIP blob %s does not exist', path)
        return False
    except Exception:
        log.exception('Could not check the DownloadAll ZIP blob %s', path)
        return False
    try:
        expected = int(size) if size not in (None, '') else None
    except (TypeError, ValueError):
        expected = None
    if expected is not None and blob.size != expected:
        log.error('The DownloadAll ZIP blob %s has %s bytes instead of %s',
                  path, blob.size, expected)
        return False
    return True


def delete_upload_blob(resource_id, filename):
    '''Σβήνει ακριβώς το blob resources/<resource_id>/<filename>.

    :returns: True αν σβήστηκε ή δεν υπάρχει (ή δεν χρειάζεται διαγραφή),
        False σε σφάλμα, ώστε να ξαναδοκιμαστεί αργότερα
    '''
    if not filename or not cloudstorage_enabled():
        return True
    try:
        from libcloud.storage.types import ObjectDoesNotExistError
        storage = _cloud_storage()
    except Exception:
        log.exception('Cloud storage is not available; cannot delete %s/%s',
                      resource_id, filename)
        return False
    if storage.leave_files:
        log.info('ckanext.cloudstorage.leave_files is set; keeping %s',
                 blob_path(resource_id, filename))
        return True
    path = blob_path(resource_id, filename)
    try:
        container = storage.container
        container.delete_object(container.get_object(path))
    except ObjectDoesNotExistError:
        log.info('Superseded ZIP blob already absent: %s', path)
        return True
    except Exception:
        log.exception('Could not delete superseded ZIP blob %s', path)
        return False
    log.info('Deleted superseded ZIP blob %s', path)
    return True


def iterate_zip_blobs(zip_resource_ids):
    '''(resource id, όνομα αρχείου) για κάθε blob κάτω από resources/<id>/ των
    πόρων ZIP. Μία σάρωση του prefix resources/ σε σελίδες.'''
    storage = _cloud_storage()
    container = storage.container
    for obj in storage.driver.iterate_container_objects(container, prefix='resources/'):
        parts = obj.name.split('/', 2)
        if len(parts) == 3 and parts[1] in zip_resource_ids:
            yield parts[1], parts[2]
