# -*- coding: utf-8 -*-
'''
Ονόματα αρχείων μέσα στο ZIP (OD-857).

Σειρά προτίμησης: Content-Disposition της απάντησης, όνομα αρχείου του upload,
τελευταίο τμήμα του URL (χωρίς query/fragment, με URL decoding), όνομα του
πόρου, και τέλος «resource-<θέση>». Αν λείπει έγκυρη κατάληξη, συμπληρώνεται
από το format ή το Content-Type. Τα ίδια ονόματα παίρνουν αριθμό, με σταθερή
σειρά (με βάση τη θέση του πόρου).
'''
import mimetypes
import posixpath
import re
import unicodedata
from urllib.parse import unquote, urlsplit

MAX_NAME_LENGTH = 150

_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')
_EXTENSION = re.compile(r'^[A-Za-z0-9]{1,8}$')
_CD_EXTENDED = re.compile(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", re.I)
_CD_PLAIN = re.compile(r'filename\s*=\s*"?([^";]+)"?', re.I)

# Μορφές που δεν αντιστοιχούν άμεσα σε κατάληξη
FORMAT_EXTENSIONS = {
    'shapefile': 'zip', 'shp': 'zip', 'excel': 'xlsx', 'text': 'txt',
    'esri rest': 'json', 'geopackage': 'gpkg',
}


def content_disposition_filename(header):
    if not header:
        return None
    match = _CD_EXTENDED.search(header)
    if match:
        encoding = match.group(1) or 'utf-8'
        try:
            return unquote(match.group(2).strip(), encoding=encoding)
        except LookupError:
            return unquote(match.group(2).strip())
    match = _CD_PLAIN.search(header)
    if match:
        return match.group(1).strip()
    return None


def url_basename(url):
    if not url:
        return None
    try:
        path = urlsplit(url).path
    except ValueError:
        return None
    # Ένα URL που τελειώνει σε / (π.χ. https://x/) δεν δίνει όνομα αρχείου
    if not path or path.endswith('/'):
        return None
    return unquote(posixpath.basename(path)) or None


def has_valid_extension(name):
    if not name or '.' not in name.strip('.'):
        return False
    extension = name.rsplit('.', 1)[1]
    return bool(_EXTENSION.match(extension)) and any(c.isalpha() for c in extension)


def extension_for(resource_format=None, content_type=None):
    '''Κατάληξη (χωρίς τελεία) από το format του πόρου ή το Content-Type.'''
    fmt = (resource_format or '').strip().lower().lstrip('.')
    if fmt:
        if '/' in fmt:
            guessed = mimetypes.guess_extension(fmt.split(';')[0].strip())
            if guessed:
                return guessed.lstrip('.')
        elif fmt in FORMAT_EXTENSIONS:
            return FORMAT_EXTENSIONS[fmt]
        elif _EXTENSION.match(fmt):
            return fmt
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(';')[0].strip().lower())
        if guessed:
            return guessed.lstrip('.')
    return None


def sanitize(name):
    name = unicodedata.normalize('NFC', name or '')
    name = _UNSAFE.sub('_', name).strip().strip('.').strip()
    if len(name) > MAX_NAME_LENGTH:
        if has_valid_extension(name):
            stem, extension = name.rsplit('.', 1)
            name = stem[:MAX_NAME_LENGTH - len(extension) - 1] + '.' + extension
        else:
            name = name[:MAX_NAME_LENGTH]
    return name


def choose_filename(resource, position, content_disposition=None,
                    content_type=None):
    '''Όνομα αρχείου για τον πόρο, πριν την εξασφάλιση μοναδικότητας.

    :param position: θέση του πόρου στο dataset (για το «resource-<θέση>»)
    '''
    # Για τα uploads, το τελευταίο τμήμα του URL είναι το όνομα του αρχείου
    candidates = [content_disposition_filename(content_disposition),
                  url_basename(resource.get('url')),
                  resource.get('name')]
    name = None
    for candidate in candidates:
        candidate = sanitize(candidate or '')
        if candidate:
            name = candidate
            break
    if not name:
        name = 'resource-%d' % (position + 1)
    if not has_valid_extension(name):
        extension = extension_for(resource.get('format'), content_type)
        if extension:
            name = '%s.%s' % (name, extension)
    return name


def make_unique(name, used):
    '''Μοναδικό όνομα μέσα στο ZIP: «όνομα (2).csv», «όνομα (3).csv», ...
    Η σύγκριση γίνεται χωρίς διάκριση πεζών/κεφαλαίων. Ενημερώνει το used.'''
    if has_valid_extension(name):
        stem, extension = name.rsplit('.', 1)
        extension = '.' + extension
    else:
        stem, extension = name, ''
    candidate, counter = name, 2
    while candidate.lower() in used:
        candidate = '%s (%d)%s' % (stem, counter, extension)
        counter += 1
    used.add(candidate.lower())
    return candidate
