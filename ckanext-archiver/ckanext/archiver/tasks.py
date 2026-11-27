from __future__ import absolute_import
from builtins import str
import os
import hashlib
import http.client
import requests
import json
import tempfile
import shutil
import datetime
import copy
import mimetypes
import re
import ssl
from time import sleep, monotonic

from requests.packages import urllib3
try:
    # Στο urllib3 1.x το όνομα του πιστοποιητικού το ελέγχει το ίδιο το urllib3
    from urllib3.util.ssl_match_hostname import CertificateError as _HostnameMismatch
except ImportError:
    _HostnameMismatch = ssl.SSLCertVerificationError
from future.moves.urllib.parse import urlparse, urljoin, quote, urlunparse

from ckan.common import _
from ckan.lib import uploader
from ckan import plugins as p
from ckanext.archiver import interfaces as archiver_interfaces

import logging

from ckanext.azurefilestore.uploader import AzureResourceUploader
from ckanext.archiver import default_settings as settings

from ckanext.archiver.resource_evaluation import \
    get_non_evaluable_resource_reason

log = logging.getLogger(__name__)

toolkit = p.toolkit

ALLOWED_SCHEMES = set(('http', 'https', 'ftp'))

USER_AGENT = 'ckanext-archiver'


def _cleanup_temp_file(file_path, log, source='archiver'):
    if not file_path:
        return

    temp_dir = os.path.realpath(tempfile.gettempdir())
    saved_file = os.path.realpath(file_path)

    if not saved_file.startswith(temp_dir + os.sep):
        log.debug('Skipping %s cleanup for non-temp file: %s', source, saved_file)
        return

    if not os.path.exists(saved_file):
        return

    try:
        os.remove(saved_file)
        log.info('Removed %s temp file: %s', source, saved_file)
    except OSError as e:
        log.warning('Could not remove %s temp file %s: %s', source, saved_file, e)


# CKAN 2.7 introduces new jobs system
if p.toolkit.check_ckan_version(max_version='2.6.99'):
    from ckan.lib.celery_app import celery

    @celery.task(name="archiver.update_resource")
    def update_resouce_celery(*args, **kwargs):
        update_resource(*args, **kwargs)

    @celery.task(name="archiver.update_package")
    def update_package_celery(*args, **kwargs):
        update_package(*args, **kwargs)

    @celery.task(name="archiver.clean")
    def clean_celery(*args, **kwargs):
        clean(*args, **kwargs)

    @celery.task(name="archiver.link_checker")
    def link_checker_celery(*args, **kwargs):
        link_checker(*args, **kwargs)


class ArchiverError(Exception):
    pass


class ArchiverErrorBeforeDownloadStarted(ArchiverError):
    pass


class DownloadException(ArchiverError):
    pass


class ArchiverErrorAfterDownloadStarted(ArchiverError):
    def __init__(self, msg, url_redirected_to=None):
        super(ArchiverError, self).__init__(msg)
        self.url_redirected_to = url_redirected_to


class DownloadError(ArchiverErrorAfterDownloadStarted):
    pass


class ArchiveError(ArchiverErrorAfterDownloadStarted):
    pass


class ChooseNotToDownload(ArchiverErrorAfterDownloadStarted):
    pass


class NotChanged(ArchiverErrorAfterDownloadStarted):
    pass


class LinkCheckerError(ArchiverError):
    pass


class LinkInvalidError(LinkCheckerError):
    pass


class LinkHeadRequestError(LinkCheckerError):
    pass


class LinkHeadMethodNotSupported(LinkCheckerError):
    pass


class CkanError(ArchiverError):
    pass


def update_resource(resource_id, queue='bulk'):
    '''
    Archive a resource.
    '''

    log.info('Starting update_resource task: res_id=%r queue=%s', resource_id, queue)

    # HACK because of race condition #1481
    sleep(2)

    # Do all work in a sub-routine since it can then be tested without celery.
    # Also put try/except around it is easier to monitor ckan's log rather than
    # celery's task status.
    try:
        result = _update_resource(resource_id, queue, log)
        return result
    except Exception as e:
        if os.environ.get('DEBUG'):
            raise
        # Any problem at all is logged and reraised so that celery can log it too
        log.error('Error occurred during archiving resource: %s\nResource: %r',
                  e, resource_id)
        raise


def update_package(package_id, queue='bulk'):
    '''
    Archive a package.
    '''

    log.info('Starting update_package task: package_id=%r queue=%s',
             package_id, queue)

    # Do all work in a sub-routine since it can then be tested without celery.
    # Also put try/except around it is easier to monitor ckan's log rather than
    # celery's task status.
    try:
        from ckanext.archiver import job_dedup, lib as archiver_lib
        # Ένα job ανά dataset τη φορά· αλλαγή όσο τρέχει → μία επανάληψη μετά
        job_dedup.run_once(
            'archiver', package_id,
            lambda: _update_package(package_id, queue, log),
            lambda rerun_queue: archiver_lib.enqueue_archiver_package(
                package_id, rerun_queue))
    except Exception as e:
        if os.environ.get('DEBUG'):
            raise
        # Any problem at all is logged and reraised so that celery can log it
        # too
        log.error('Error occurred during archiving package: %s\nPackage: %s',
                  e, package_id)
        raise


def _update_package(package_id, queue, log):
    from ckan import model
    from ckanext.archiver.lib import is_check_only_mode

    get_action = toolkit.get_action
    check_only = is_check_only_mode()

    # archive: πόροι που αρχειοθετήθηκαν εκ νέου.
    # check_only: πόροι των οποίων άλλαξε το αποτέλεσμα του ελέγχου URL.
    num_archived = 0
    context_ = {'model': model, 'ignore_auth': True, 'session': model.Session}
    package = get_action('package_show')(context_, {'id': package_id})

    resources = package['resources']
    from ckanext.archiver import lib as archiver_lib
    deadline = None
    hosts = HostTimeouts(
        archiver_lib.check_only_host_timeout_limit() if check_only else 0, log)
    if check_only:
        resources = _oldest_checked_first(package_id, resources)
        deadline = _check_only_deadline()

    for index, resource in enumerate(resources):
        if deadline is not None and index > 0 and monotonic() > deadline:
            # Οι υπόλοιποι πόροι ελέγχονται πρώτοι στο επόμενο job· το notify
            # και το reindex γίνονται κανονικά για όσους ελέγχθηκαν
            log.warning('Time limit reached for %s: %d of %d resources left '
                        'unchecked', package['name'], len(resources) - index,
                        len(resources))
            break
        resource_id = resource['id']
        res = _update_resource(resource_id, queue, log, hosts)
        if res:
            num_archived += 1

    if hosts.skipped:
        log.info('Links not requested in %s because their server did not '
                 'respond: %s', package['name'], hosts.skipped)

    if num_archived > 0:
        log.info("Notifying package as %d items were %s", num_archived,
                 'checked with a changed result' if check_only else 'archived')
        notify_package(package, queue)
    else:
        log.info("Not notifying package as 0 items were %s",
                 'changed' if check_only else 'archived')

    if check_only and num_archived == 0:
        # Κανένας πόρος δεν άλλαξε κατάσταση· δεν χρειάζεται reindex
        log.info('Search index skipped %s (no change)', package['name'])
        return

    # Refresh the index for this dataset, so that it contains the latest
    # archive info. However skip it if there are downstream plugins that will
    # do this anyway, since it is an expensive step to duplicate.
    if not _qa_reindexes_after_notify():
        _update_search_index(package_id, log)
    else:
        log.info('Search index skipped %s', package['name'])


def _oldest_checked_first(package_id, resources):
    '''check_only: πρώτα οι πόροι που δεν έχουν ελεγχθεί ποτέ και μετά όσοι
    ελέγχθηκαν παλαιότερα. Αν ένα job σταματήσει στο χρονικό όριο, το επόμενο
    συνεχίζει από τους πόρους που έμειναν, αντί να ξεκινά πάλι από την αρχή.'''
    from ckanext.archiver.model import Archival
    checked = dict((archival.resource_id, archival.updated)
                   for archival in Archival.get_for_package(package_id))
    return sorted(resources,
                  key=lambda resource: checked.get(resource['id']) or datetime.datetime.min)


def _check_only_deadline():
    '''check_only: χρονική στιγμή (time.monotonic) μετά την οποία δεν ξεκινά
    έλεγχος νέου πόρου, ώστε το job να τελειώνει πριν από το timeout της RQ.
    Αφήνει περιθώριο για τον χειρότερο έλεγχο ενός πόρου (HEAD και GET σε κάθε
    προσπάθεια), το notify και το reindex. None εκτός RQ ή χωρίς timeout.'''
    from rq import get_current_job
    from ckanext.archiver import lib as archiver_lib
    job = get_current_job()
    timeout = getattr(job, 'timeout', None) if job else None
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        return None
    retries = archiver_lib.check_only_retries()
    worst_resource = (retries + 1) * 2 * archiver_lib.check_only_timeout() + \
        retries * RETRY_DELAY_SECONDS
    margin = max(timeout * 0.1, worst_resource + 60)
    return monotonic() + max(timeout - margin, 0)


def _qa_reindexes_after_notify():
    '''True όταν κάποιος IPipe observer (π.χ. το QA σε archival mode) θα κάνει
    reindex μετά το package-archived. Το δηλώνει ο ίδιος ο observer μέσω του
    reindexes_after_package_archived(), αντί ο archiver να διαβάζει τις
    ρυθμίσεις του.
    '''
    for observer in p.PluginImplementations(archiver_interfaces.IPipe):
        check = getattr(observer, 'reindexes_after_package_archived', None)
        if check is not None and check():
            return True
    return False


def _update_search_index(package_id, log):
    '''
    Tells CKAN to update its search index for a given package.
    '''
    from ckan import model
    from ckan.lib.search.index import PackageSearchIndex
    package_index = PackageSearchIndex()
    context_ = {'model': model, 'ignore_auth': True, 'session': model.Session,
                'use_cache': False, 'validate': False}
    package = toolkit.get_action('package_show')(context_, {'id': package_id})
    package_index.index_package(package, defer_commit=False)
    log.info('Search indexed %s', package['name'])


def _update_resource(resource_id, queue, log, hosts=None):
    """
    Link check and archive the given resource.
    If successful, updates the archival table with the cache_url & hash etc.
    Finally, a notification of the archival is broadcast.

    Params:
      resource - resource dict
      queue - name of the celery queue

    Should only raise on a fundamental error:
      ArchiverError
      CkanError

    Returns a JSON dict, ready to be returned from the celery task giving a
    success status:
        {
            'resource': the updated resource dict,
            'file_path': path to archived file (if archive successful), or None
        }
    If not successful, returns None.
    """

    from ckan import model
    from ckan.plugins.toolkit import config
    from ckanext.archiver import default_settings as settings
    from ckanext.archiver.model import Status, Archival

    get_action = toolkit.get_action

    assert is_id(resource_id), resource_id
    context_ = {'model': model, 'ignore_auth': True, 'session': model.Session}
    resource = get_action('resource_show')(context_, {'id': resource_id})

    if not os.path.exists(settings.ARCHIVE_DIR):
        log.info("Creating archive directory: %s" % settings.ARCHIVE_DIR)
        os.mkdir(settings.ARCHIVE_DIR)

    def _save(status_id, exception, resource, url_redirected_to=None,
              download_result=None, archive_result=None):
        reason = u'%s' % exception
        save_archival(resource, status_id,
                      reason, url_redirected_to,
                      download_result, archive_result,
                      log)
        notify_resource(
            resource,
            queue,
            archive_result.get('cache_filename') if archive_result else None)

    non_evaluable_reason = get_non_evaluable_resource_reason(resource)
    if non_evaluable_reason:
        log.info('Skipping non-evaluable resource: id=%s reason=%s',
                 resource['id'], non_evaluable_reason)
        _save(Status.by_text('Chose not to download'),
              ChooseNotToDownload(non_evaluable_reason),
              resource)
        return

    from ckanext.archiver.lib import is_check_only_mode
    if is_check_only_mode():
        # Έλεγχος μόνο του URL, χωρίς λήψη/hash/αντίγραφο στο Azure
        return _check_resource_url(resource, queue, log, hosts)

    # Download
    try_as_api = False
    requires_archive = True

    url = resource['url']
    if not url.startswith('http'):
        url = config['ckan.site_url'].rstrip('/') + url

    if resource.get('url_type') == 'upload':
        upload = uploader.get_resource_uploader(resource)
        filepath = upload.get_path(resource['id'])

        hosted_externally = not url.startswith(config['ckan.site_url']) or urlparse(filepath).scheme != ''
        # if resource.get('resource_type') == 'file.upload' and not hosted_externally:
        if not hosted_externally:
            log.info("Won't attemp to archive resource uploaded locally: %s" % resource['url'])

            try:
                hash, length = _file_hashnlength(filepath)
            except IOError as e:
                log.error('Error while accessing local resource %s: %s', filepath, e)

                download_status_id = Status.by_text('URL request failed')
                _save(download_status_id, e, resource)
                return

            mimetype = None
            headers = None
            content_type, content_encoding = mimetypes.guess_type(url)
            if content_type:
                mimetype = _clean_content_type(content_type)
                headers = {'Content-Type': content_type}

            download_result_mock = {'mimetype': mimetype,
                                    'size': length,
                                    'hash': hash,
                                    'headers': headers,
                                    'saved_file': filepath,
                                    'url_redirected_to': url,
                                    'request_type': 'GET'}

            archive_result_mock = {'cache_filepath': filepath,
                                   'cache_url': url}

            # Success
            _save(Status.by_text('Archived successfully'), '', resource,
                  download_result_mock['url_redirected_to'], download_result_mock, archive_result_mock)

            # The return value is only used by tests. Serialized for Celery.
            return json.dumps(dict(download_result_mock, **archive_result_mock))
            # endif: processing locally uploaded resource

    log.info("Attempting to download resource: %s" % resource['url'])
    download_result = None
    download_status_id = Status.by_text('Archived successfully')
    previous = Archival.get_for_resource(resource_id)
    if previous is not None and not previous.cache_url:
        # Χωρίς αρχειοθετημένο αντίγραφο, το ETag (π.χ. από έλεγχο check_only)
        # δεν μπορεί να σημαίνει «δεν άλλαξε»· γίνεται κανονική λήψη
        previous = None
    context = {
        'site_url': config.get('ckan.site_url_internally') or config['ckan.site_url'],
        'cache_url_root': config.get('ckanext-archiver.cache_url_root'),
        'previous': previous
        }

    err = None
    try:
        download_result = download(context, resource)
    except NotChanged as e:
        download_status_id = Status.by_text('Content has not changed')
        try_as_api = False
        requires_archive = False
        err = e
    except LinkInvalidError as e:
        download_status_id = Status.by_text('URL invalid')
        try_as_api = False
        err = e
    except DownloadException as e:
        download_status_id = Status.by_text('Download error')
        try_as_api = True
        err = e
    except DownloadError as e:
        download_status_id = Status.by_text('Download error')
        try_as_api = True
        err = e
    except ChooseNotToDownload as e:
        download_status_id = Status.by_text('Chose not to download')
        try_as_api = False
        err = e
    except Exception as e:
        if os.environ.get('DEBUG'):
            raise
        log.error('Uncaught download failure: %r, %r', e, e.args)
        _save(Status.by_text('Download failure'), e, resource)
        return

    if not Status.is_ok(download_status_id) and err:
        log.info('GET error: %s - %r, %r "%s"',
                 Status.by_id(download_status_id), err, err.args,
                 resource.get('url'))

        if try_as_api:
            download_result = api_request(context, resource)
            if download_result:
                download_status_id = Status.by_text('Archived successfully')
            # else the download_status_id (i.e. an error) is left what it was
            # from the previous download (i.e. not when we tried it as an API)

        if not try_as_api or not Status.is_ok(download_status_id):
            extra_args = [err.args.url_redirected_to] if 'url_redirected_to' in err.args else []
            _save(download_status_id, err, resource, *extra_args)
            if download_result:
                _cleanup_temp_file(download_result.get('saved_file'), log)
            return

    if not requires_archive:
        # We don't need to archive if the remote content has not changed
        if download_result:
            _cleanup_temp_file(download_result.get('saved_file'), log)
        return None

    # Archival
    log.info('Attempting to archive resource')
    try:
        archive_result = archive_resource(context, resource, log, download_result)
    except ArchiveError as e:
        log.error('System error during archival: %r, %r', e, e.args)
        _save(Status.by_text('System error during archival'), e, resource, download_result['url_redirected_to'])
        _cleanup_temp_file(download_result.get('saved_file'), log)
        return

    # Success
    _save(Status.by_text('Archived successfully'), '', resource,
          download_result['url_redirected_to'], download_result, archive_result)
    _cleanup_temp_file(download_result.get('saved_file'), log)

    # The return value is only used by tests. Serialized for Celery.
    return json.dumps(dict(download_result, **archive_result))


def download(context, resource, url_timeout=30,
             max_content_length='default',
             method='GET'):
    '''Given a resource, tries to download it.

    Params:
      resource - dict of the resource

    Exceptions from tidy_url may be propagated:
       LinkInvalidError if the URL is invalid

    If there is an error performing the download, raises:
       DownloadException - connection problems etc.
       DownloadError - HTTP status code is an error or 0 length

    If download is not suitable (e.g. too large), raises:
       ChooseNotToDownload

    If the basic GET fails then it will try it with common API
    parameters (SPARQL, WMS etc) to get a better response.

    Returns a dict of results of a successful download:
      mimetype, size, hash, headers, saved_file, url_redirected_to
    '''
    from ckanext.archiver import default_settings as settings
    from ckan.plugins.toolkit import config

    if max_content_length == 'default':
        max_content_length = settings.MAX_CONTENT_LENGTH

    url = resource['url']
    url = tidy_url(url)

    if (resource.get('url_type') == 'upload' and
            not url.startswith('http')):
        url = context['site_url'].rstrip('/') + url

    hosted_externally = not url.startswith(config['ckan.site_url'])
    if resource.get('url_type') == 'upload' and hosted_externally:
        # ckanext-cloudstorage for example does that

        # enable ckanext-archiver.archive_cloud for qa to work on cloud resources
        # till https://github.com/ckan/ckanext-qa/issues/48 is resolved
        # Warning: this will result in double storage of all files below archival filesize limit

        if not toolkit.asbool(config.get('ckanext-archiver.archive_cloud', False)):
            raise ChooseNotToDownload('Skipping resource hosted externally to download resource: %s'
                                      % url,  url)

    headers = _set_user_agent_string({})

    # start the download - just get the headers
    # May raise DownloadException
    method_func = {'GET': requests.get, 'POST': requests.post}[method]
    kwargs = {'timeout': url_timeout, 'stream': True, 'headers': headers,
              'verify': verify_https()}
    if 'ckan.download_proxy' in config:
        download_proxy = config.get('ckan.download_proxy')
        log.debug('Downloading via proxy %s', download_proxy)
        kwargs['proxies'] = {'http': download_proxy, 'https': download_proxy}
    res = requests_wrapper(log, method_func, url, **kwargs)
    url_redirected_to = res.url if url != res.url else None

    if context.get('previous') and ('etag' in res.headers):
        if context.get('previous').etag == res.headers['etag']:
            log.info("ETAG matches, not downloading content")
            raise NotChanged("etag suggests content has not changed")

    if not res.ok:  # i.e. 404 or something
        raise DownloadError(_('Server reported status error: %s %s') %
                            (res.status_code, res.reason),
                            url_redirected_to)
    log.info('GET started successfully. Content headers: %r', res.headers)

    # record headers
    mimetype = _clean_content_type(res.headers.get('content-type', '').lower())

    # make sure resource content-length does not exceed our maximum
    content_length = res.headers.get('content-length')

    if content_length:
        try:
            content_length = int(content_length)
        except ValueError:
            # if there are multiple Content-Length headers, requests
            # will return all the values, comma separated
            if ',' in content_length:
                try:
                    content_length = int(content_length.split(',')[0])
                except ValueError:
                    pass
    if isinstance(content_length, int) and \
       int(content_length) >= max_content_length:
        # record fact that resource is too large to archive
        log.warning('Resource too large to download: %s > max (%s). '
                    'Resource: %s %r', content_length,
                    max_content_length, resource['id'], url)
        raise ChooseNotToDownload(_('Content-length %s exceeds maximum '
                                    'allowed value %s') %
                                  (content_length, max_content_length),
                                  url_redirected_to)
    # content_length in the headers is useful but can be unreliable, so when we
    # download, we will monitor it doesn't go over the max.

    # continue the download - stream the response body
    def get_content():
        return res.text
    log.info('Downloading the body')
    content = requests_wrapper(log, get_content)

    # APIs can return status 200, but contain an error message in the body
    if response_is_an_api_error(content):
        raise DownloadError(_('Server content contained an API error message: %s') %
                            content[:250],
                            url_redirected_to)

    content_length = len(content)
    if content_length > max_content_length:
        raise ChooseNotToDownload(_("Content-length %s exceeds maximum allowed value %s") %
                                  (content_length, max_content_length),
                                  url_redirected_to)

    log.info('Saving resource')
    try:
        length, hash, saved_file_path = _save_resource(resource, res, max_content_length)
    except ChooseNotToDownload as e:
        raise ChooseNotToDownload(str(e), url_redirected_to)
    log.info('Resource saved. Length: %s File: %s', length, saved_file_path)

    # zero length (or just one byte) indicates a problem
    if length < 2:
        # record fact that resource is zero length
        log.warning('Resource found was length %i - not archiving. Resource: %s %r',
                    length, resource['id'], url)
        raise DownloadError(_("Content-length after streaming was %i") % length,
                            url_redirected_to)

    log.info('Resource downloaded: id=%s url=%r cache_filename=%s length=%s hash=%s',
             resource['id'], url, saved_file_path, length, hash)

    return {'mimetype': mimetype,
            'size': length,
            'hash': hash,
            'headers': dict(res.headers),
            'saved_file': saved_file_path,
            'url_redirected_to': url_redirected_to,
            'request_type': method}


def _file_hashnlength(local_path):
    BLOCKSIZE = 65536
    hasher = hashlib.sha1()
    length = 0

    with open(local_path, 'rb') as afile:
        buf = afile.read(BLOCKSIZE)
        while len(buf) > 0:
            hasher.update(buf)
            length += len(buf)

            buf = afile.read(BLOCKSIZE)

    return (str(hasher.hexdigest()), length)


def archive_resource(context, resource, log, result=None, url_timeout=30):
    """
    Archive the given resource. Uploads the file to Azure Blob Storage
    using AzureResourceUploader.

    Params:
       result - result of the download(), containing keys: length, saved_file

    If there is a failure, raises ArchiveError.

    Returns: {cache_filepath, cache_url}
    """
    if not result or 'saved_file' not in result:
        raise ArchiveError(_('Missing downloaded file information'))

    # Extract filename
    parsed_url = urlparse(resource.get('url'))
    file_name = parsed_url.path.split('/')[-1] or 'resource'
    file_name = file_name.strip()

    # Upload to Azure
    try:
        uploader = AzureResourceUploader(resource)
        uploader.upload_stream(result['saved_file'], os.path.join(settings.BLOB_ARCHIVE_DIR, resource['id'][:2], resource['id'], file_name))
        log.info('Uploaded resource to Azure as: %s', os.path.join(settings.BLOB_ARCHIVE_DIR, resource['id'][:2], resource['id'], file_name))
    except Exception as e:
        log.error('Azure upload failed: %s', str(e))
        raise ArchiveError(_('Azure upload failed'))

    # Build cache URL (assumes cache_url_root points to Azure public URL root)
    if not context.get('cache_url_root'):
        log.warning('Not saved cache_url because no value for '
                    'ckanext-archiver.cache_url_root in config')
        raise ArchiveError(_('No value for ckanext-archiver.cache_url_root in config'))

    relative_archive_path = os.path.join(settings.BLOB_ARCHIVE_DIR, resource['id'][:2], resource['id'], file_name)
    cache_url = urljoin(str(context['cache_url_root']), relative_archive_path)

    return {
        'cache_filepath': file_name,
        'cache_url': cache_url
    }


# Αποτελέσματα ελέγχου URL στο check_only
URL_OK = 'ok'
URL_BROKEN = 'broken'
URL_TRANSIENT = 'transient'
# Ο πόρος δεν ελέγχεται (π.χ. upload στο cloud με archive_cloud = false)
URL_SKIPPED = 'skipped'
# Αναμονή ανάμεσα σε επαναλήψεις μετά από προσωρινή αποτυχία
RETRY_DELAY_SECONDS = 2


def _check_resource_url(resource, queue, log, hosts=None):
    '''check_only: ελέγχει μόνο το resource.url και αποθηκεύει το αποτέλεσμα.

    Δεν κατεβάζει το αρχείο, δεν γράφει προσωρινό αρχείο, δεν υπολογίζει hash
    και δεν ανεβάζει αντίγραφο στο Azure.
    Επιστρέφει True αν άλλαξε το αποτέλεσμα σε σχέση με τον προηγούμενο έλεγχο.
    '''
    try:
        outcome = _url_check_outcome(resource, log, hosts)
    except Exception:
        # Απρόσμενο σφάλμα (π.χ. bug ή ρυθμίσεις), όχι αποτυχία του συνδέσμου:
        # η εγγραφή archival μένει ως έχει, ώστε να μη μετρήσει στο κατώφλι
        # αποτυχιών, και το job συνεχίζει με τους υπόλοιπους πόρους
        log.exception('Unexpected error checking resource %s; result not saved',
                      resource.get('id'))
        return False
    changed = save_url_check(resource, outcome, log)
    notify_resource(resource, queue, None)
    return changed


def _outcome(result, reason='', status_text=None, url_redirected_to=None,
             headers=None, timed_out=False, responded=False,
             not_requested=False, retry=True):
    '''Αποτέλεσμα ελέγχου ενός URL. timed_out: ο server δεν απάντησε μέσα στο
    timeout· responded: ο server έδωσε απάντηση HTTP (οποιοσδήποτε κωδικός)·
    not_requested: ο σύνδεσμος δεν ζητήθηκε, γιατί ο server του δεν απαντούσε.
    Τα τρία χρησιμοποιούνται από το HostTimeouts. retry: μια νέα προσπάθεια σε
    λίγα δευτερόλεπτα μπορεί να δώσει άλλο αποτέλεσμα. Ισχύει μόνο όταν δεν
    ήρθε καμία απάντηση (σύνδεση που κόπηκε, άρνηση σύνδεσης, timeout)· όχι
    όταν ο server απάντησε με σφάλμα HTTP ή δεν επαληθεύεται το πιστοποιητικό
    του, γιατί αυτά δεν αλλάζουν σε δευτερόλεπτα.'''
    return {'result': result, 'reason': reason, 'status_text': status_text,
            'url_redirected_to': url_redirected_to,
            'headers': {k.lower(): v for k, v in (headers or {}).items()},
            'timed_out': timed_out, 'responded': responded,
            'not_requested': not_requested, 'retry': retry}


class HostTimeouts(object):
    '''check_only: servers που δεν απαντούν, μέσα σε ένα job (ένα dataset).

    Μετρά τους συνεχόμενους «αργούς» συνδέσμους κάθε server (host και port
    του URL του πόρου): όσους δεν πήραν καμία απάντηση HTTP σε καμία
    προσπάθεια, και τουλάχιστον μία προσπάθεια έληξε ή κράτησε όσο το timeout
    (π.χ. DNS που κρεμά). Μετρά ο server του URL του πόρου, ακόμη κι αν το
    timeout έγινε μετά από ανακατεύθυνση (π.χ. http → https).

    - Μετά τον πρώτο αργό σύνδεσμο ενός server, οι επόμενοι σύνδεσμοί του
      δοκιμάζονται μία φορά, χωρίς επανάληψη.
    - Όταν οι αργοί σύνδεσμοι φτάσουν το όριο (ckanext.archiver.check_only.
      host_timeout_limit), οι υπόλοιποι σύνδεσμοι του server σε αυτό το job
      δεν ζητούνται. Μετρούν στις αποτυχίες (έως ένα κάτω από το κατώφλι),
      αλλά ένας σύνδεσμος γίνεται broken μόνο μετά από πραγματικό έλεγχο που
      απέτυχε, και ένας ήδη broken σύνδεσμος μένει όπως είναι, εκτός αν
      άλλαξε ο πόρος (βλ. save_url_check).
    - Οποιαδήποτε απάντηση HTTP σε οποιαδήποτε προσπάθεια (και 404, 503,
      ανακατευθύνσεις σε κύκλο, ή απάντηση στο HEAD πριν από ένα GET που
      λήγει) μηδενίζει τον μετρητή. Οι γρήγορες αποτυχίες (π.χ. SSL, άρνηση
      σύνδεσης) δεν τον αλλάζουν, γιατί δεν κοστίζουν χρόνο.

    Οι σύνδεσμοι που δεν ζητήθηκαν κρατούν την προηγούμενη ώρα ελέγχου
    (archival.updated, ο τελευταίος πραγματικός έλεγχος), οπότε στο επόμενο
    πέρασμα ελέγχονται πρώτοι (_oldest_checked_first).

    Με όριο 0 δεν κάνει τίποτα (εκτός check_only ή σε έλεγχο ενός πόρου).
    '''

    DEFAULT_PORTS = {'http': 80, 'https': 443}

    def __init__(self, limit=0, log=log):
        self.limit = limit
        self.log = log
        self.slow = {}
        self.skipped = {}

    @classmethod
    def host(cls, url):
        '''host:port, με το προεπιλεγμένο port του scheme (80/443).'''
        try:
            parts = urlparse(url or '')
            hostname = (parts.hostname or '').lower()
            port = parts.port or cls.DEFAULT_PORTS.get((parts.scheme or '').lower())
        except ValueError:
            return None
        if not hostname:
            return None
        return '%s:%s' % (hostname, port) if port else hostname

    def blocked(self, host):
        return bool(self.limit) and host is not None and \
            self.slow.get(host, 0) >= self.limit

    def retry_allowed(self, host):
        '''Χωρίς επανάληψη για server που άργησε ήδη σε αυτό το job.'''
        return not (self.limit and self.slow.get(host, 0))

    def skip(self, host):
        '''Αποτέλεσμα για σύνδεσμο που δεν ζητείται.'''
        self.skipped[host] = self.skipped.get(host, 0) + 1
        return _outcome(URL_TRANSIENT, _(
            'Not checked: the server %s did not respond (timeout) to %d '
            'previous links in this check') % (host, self.limit),
            not_requested=True)

    def record(self, host, responded, slow):
        '''responded: κάποια προσπάθεια πήρε απάντηση HTTP· slow: καμία δεν πήρε
        και κάποια έληξε ή κράτησε όσο το timeout.'''
        if not self.limit or host is None:
            return
        if responded:
            self.slow[host] = 0
        elif slow:
            self.slow[host] = self.slow.get(host, 0) + 1
            if self.slow[host] == self.limit:
                self.log.info('Server %s did not respond to %d consecutive links; '
                              'its remaining links in this job are not requested',
                              host, self.limit)


def _url_check_outcome(resource, log, hosts=None):
    from ckan.plugins.toolkit import config
    if hosts is None:
        hosts = HostTimeouts()

    url = (resource.get('url') or '').strip()
    site_url = config['ckan.site_url']

    if resource.get('url_type') == 'upload':
        relative = not url.startswith('http')
        # Όπως στο _update_resource: η σύγκριση γίνεται με το δημόσιο URL του site
        public_url = site_url.rstrip('/') + url if relative else url
        upload = uploader.get_resource_uploader(resource)
        filepath = upload.get_path(resource['id'])
        hosted_externally = not public_url.startswith(site_url) or \
            urlparse(filepath).scheme != ''
        if not hosted_externally:
            # Τοπικό upload: αρκεί να υπάρχει το αρχείο, χωρίς hashing
            try:
                stat = os.stat(filepath)
            except OSError as e:
                return _outcome(URL_BROKEN, str(e), 'URL request failed')
            return _outcome(URL_OK, headers={'content-length': str(stat.st_size)})
        if not toolkit.asbool(config.get('ckanext-archiver.archive_cloud', False)):
            # Όπως στο archive mode: τα uploads στο cloud δεν ελέγχονται
            return _outcome(URL_SKIPPED,
                            'Skipping resource hosted externally to download resource: %s'
                            % public_url, 'Chose not to download')
        # Ο έλεγχος HTTP γίνεται στο εσωτερικό URL του site, όπως στο download()
        url = (config.get('ckan.site_url_internally') or site_url).rstrip('/') + url \
            if relative else url

    try:
        url = tidy_url(url)
    except LinkInvalidError as e:
        return _outcome(URL_BROKEN, str(e), 'URL invalid')

    host = HostTimeouts.host(url)
    if hosts.blocked(host):
        return hosts.skip(host)

    from ckanext.archiver import lib as archiver_lib
    retries = archiver_lib.check_only_retries() if hosts.retry_allowed(host) else 0
    timeout = archiver_lib.check_only_timeout()
    outcome = None
    responded = slow = False
    for attempt in range(retries + 1):
        started = monotonic()
        outcome = _http_check_once(url, timeout)
        # Ανά προσπάθεια, χωρίς την παύση ανάμεσα στις προσπάθειες
        responded = responded or outcome['responded']
        slow = slow or (not outcome['responded'] and
                        outcome['result'] == URL_TRANSIENT and
                        (outcome['timed_out'] or monotonic() - started >= timeout))
        if outcome['result'] != URL_TRANSIENT:
            break
        log.info('URL check attempt %d failed for %s: %s',
                 attempt + 1, url, outcome['reason'])
        if not outcome['retry']:
            break
        if attempt < retries and RETRY_DELAY_SECONDS:
            sleep(RETRY_DELAY_SECONDS)
    hosts.record(host, responded, slow)
    return outcome


_CERT_ERRORS = (ssl.SSLCertVerificationError, _HostnameMismatch)


def _cert_verify_failed(error):
    '''True αν το σφάλμα SSL είναι αποτυχία επαλήθευσης του πιστοποιητικού του
    server (π.χ. λείπει το ενδιάμεσο πιστοποιητικό, έληξε, self-signed, είναι
    για άλλο όνομα). Αυτή δεν αλλάζει με νέα προσπάθεια, σε αντίθεση με άλλα
    σφάλματα SSL, π.χ. μια σύνδεση που κόπηκε στη μέση του handshake.
    Η requests τυλίγει το αρχικό σφάλμα: SSLError → MaxRetryError (στο
    reason) → SSLError του urllib3 → σφάλμα του πιστοποιητικού.'''
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, _CERT_ERRORS):
            return True
        pending.extend(e for e in (getattr(current, 'reason', None),) + current.args
                       if isinstance(e, BaseException))
    return False


def _http_check_once(url, timeout):
    '''HEAD με redirects· αν αποτύχει ή επιστρέψει >= 400, streamed GET που
    κλείνει χωρίς να διαβάσει το body.'''
    from ckan.plugins.toolkit import config
    kwargs = {'timeout': timeout, 'headers': _set_user_agent_string({}),
              'verify': verify_https(), 'allow_redirects': True}
    if 'ckan.download_proxy' in config:
        proxy = config.get('ckan.download_proxy')
        kwargs['proxies'] = {'http': proxy, 'https': proxy}

    # Αν ο server απαντήσει στο HEAD (>= 400), είναι ζωντανός, ακόμη κι αν το
    # GET που ακολουθεί αποτύχει (HostTimeouts)
    head_responded = False
    try:
        response = requests.head(url, **kwargs)
        response.close()
        if response.status_code < 400:
            return _response_outcome(url, response)
        head_responded = True
    except requests.exceptions.Timeout:
        # Δεν ξαναδοκιμάζουμε με GET, θα διπλασίαζε μόνο τον χρόνο αναμονής
        return _outcome(URL_TRANSIENT, _('Connection timed out after %ss') % timeout,
                        timed_out=True)
    except requests.exceptions.SSLError as e:
        if _cert_verify_failed(e):
            # Το πιστοποιητικό είναι του server· το GET θα αποτύχει το ίδιο
            return _outcome(URL_TRANSIENT, _('Connection error: %s') % e,
                            retry=False)
        # Άλλο σφάλμα SSL: δοκιμή με GET
    except Exception:
        pass  # π.χ. ο server κόβει τα HEAD· δοκιμή με GET

    try:
        response = requests.get(url, stream=True, **kwargs)
        response.close()
    except (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema,
            requests.exceptions.InvalidSchema) as e:
        return _outcome(URL_BROKEN, str(e), 'URL invalid')
    except requests.exceptions.TooManyRedirects:
        # Ο server απαντά (με ανακατευθύνσεις σε κύκλο)
        return _outcome(URL_BROKEN, _('Too many redirects'), 'URL request failed',
                        responded=True)
    except requests.exceptions.Timeout:
        return _outcome(URL_TRANSIENT, _('Connection timed out after %ss') % timeout,
                        timed_out=True, responded=head_responded)
    except requests.exceptions.SSLError as e:
        # Π.χ. ανακατεύθυνση σε server με πιστοποιητικό που δεν επαληθεύεται
        return _outcome(URL_TRANSIENT, _('Connection error: %s') % e,
                        responded=head_responded, retry=not _cert_verify_failed(e))
    except requests.exceptions.ConnectionError as e:
        return _outcome(URL_TRANSIENT, _('Connection error: %s') % e,
                        responded=head_responded)
    except requests.exceptions.RequestException as e:
        return _outcome(URL_TRANSIENT, _('Error during request: %s') % e,
                        responded=head_responded)
    except Exception as e:
        # π.χ. LocationParseError από redirect σε άκυρο host
        return _outcome(URL_TRANSIENT, _('Error with the request: %s') % e,
                        responded=head_responded)
    return _response_outcome(url, response)


def _response_outcome(url, response):
    redirected = response.url if response.url and response.url != url else None
    if response.status_code < 400:
        return _outcome(URL_OK, url_redirected_to=redirected,
                        headers=response.headers, responded=True)
    reason = _('Server reported status error: %s %s') % \
        (response.status_code, response.reason)
    if response.status_code in (404, 410):
        return _outcome(URL_BROKEN, reason, 'URL request failed', redirected,
                        responded=True)
    # 401, 403, 429, 5xx και λοιπά: προσωρινά, μέχρι να φτάσουν το όριο
    # αποτυχιών. Χωρίς επανάληψη: ο server απάντησε (π.χ. 403 σε αυτόματα
    # αιτήματα, 502 όταν έχει πέσει το GeoServer πίσω από τον proxy) και η
    # απάντηση δεν θα αλλάξει σε 2 δευτερόλεπτα· από τις σύντομες διακοπές
    # προστατεύει το κατώφλι αποτυχιών ανάμεσα στα περάσματα
    return _outcome(URL_TRANSIENT, reason, url_redirected_to=redirected,
                    responded=True, retry=False)


def save_url_check(resource, outcome, log):
    '''Αποθηκεύει αποτέλεσμα check_only στον πίνακα archival.

    Ενημερώνει status, reason, redirect, ιστορικό αποτυχιών και updated σε
    κάθε έλεγχο. Δεν αγγίζει τα cache_url, cache_filepath και hash.
    Στο resource_timestamp κρατά το metadata_modified του πόρου που ελέγχθηκε
    (στο CKAN 2.10 δεν χρησιμοποιείται αλλιώς, αφού δεν υπάρχουν revisions).

    Επιστρέφει True αν άλλαξε το status ή αν ο πόρος τροποποιήθηκε (π.χ. νέο
    URL ή format) από τον προηγούμενο έλεγχο· τότε στέλνεται package-archived,
    ώστε το QA σε archival mode να ξαναβαθμολογήσει.
    '''
    from ckan import model
    from ckanext.archiver.model import Archival, Status
    from ckanext.archiver import lib as archiver_lib

    now = datetime.datetime.now()
    archival = Archival.get_for_resource(resource['id'])
    first_check = archival is None
    if first_check:
        archival = Archival.create(resource['id'])
        model.Session.add(archival)
    previous_status_id = archival.status_id
    not_requested = outcome.get('not_requested')
    resource_timestamp = _resource_metadata_modified(resource)
    edited = resource_timestamp is not None and \
        archival.resource_timestamp is not None and \
        resource_timestamp != archival.resource_timestamp
    if not_requested and archival.is_broken and not edited:
        # Δεν ζητήθηκε (ο server του δεν απαντούσε) και είναι ήδη broken από
        # πραγματικό έλεγχο του ίδιου URL: η εγγραφή μένει ως έχει
        log.info('URL not requested, archival unchanged (already broken): %s',
                 archival.resource_id)
        model.repo.commit_and_remove()
        return False
    if resource_timestamp is not None and not not_requested:
        # Σε σύνδεσμο που δεν ζητήθηκε, η αλλαγή του πόρου μένει για τον
        # επόμενο πραγματικό έλεγχο
        archival.resource_timestamp = resource_timestamp

    if outcome['result'] == URL_OK:
        status_id = Status.by_text('URL checked successfully')
        archival.last_success = now
        archival.first_failure = None
        archival.failure_count = 0
        # Αν υπάρχει παλιό αρχειοθετημένο αντίγραφο, τα etag/last_modified/
        # mimetype/size περιγράφουν εκείνο και δεν αλλάζουν· αλλιώς ένα νέο
        # archive θα έβλεπε το ETag του ελέγχου και θα θεωρούσε το αρχείο
        # «αμετάβλητο».
        if not archival.cache_url:
            headers = outcome['headers']
            if headers.get('etag'):
                archival.etag = headers['etag']
            if headers.get('last-modified'):
                archival.last_modified = headers['last-modified']
            if headers.get('content-type'):
                archival.mimetype = _clean_content_type(headers['content-type'].lower())
            try:
                archival.size = int(headers['content-length'].split(',')[0])
            except (KeyError, ValueError, AttributeError):
                pass
    elif outcome['result'] == URL_SKIPPED:
        status_id = Status.by_text(outcome['status_text'])
    else:
        # Συνεχόμενες αποτυχίες μετρούν μόνο αν και ο προηγούμενος έλεγχος απέτυχε
        continuing = previous_status_id is not None and \
            not Status.is_ok(previous_status_id) and \
            previous_status_id != Status.by_text('Chose not to download')
        threshold = archiver_lib.check_only_failure_threshold()
        if continuing and archival.failure_count:
            # Οι σύνδεσμοι που δεν ζητήθηκαν ανεβάζουν τον μετρητή έως ένα κάτω
            # από το κατώφλι· πάνω από αυτό μόνο πραγματικοί έλεγχοι
            if not not_requested or archival.failure_count < threshold - 1:
                archival.failure_count += 1
        else:
            archival.first_failure = now
            archival.failure_count = 1
        if outcome['result'] == URL_BROKEN:
            status_id = Status.by_text(outcome['status_text'])
        elif archival.failure_count >= threshold and not not_requested:
            # Broken μόνο μετά από πραγματικό έλεγχο που απέτυχε· ένας σύνδεσμος
            # που δεν ζητήθηκε (HostTimeouts) μένει προσωρινή αποτυχία
            status_id = Status.by_text('URL request failed')
        else:
            status_id = Status.by_text('URL check temporarily failed')

    archival.status_id = status_id
    archival.is_broken = Status.is_status_broken(status_id)
    archival.reason = outcome['reason']
    if not not_requested:
        archival.url_redirected_to = outcome['url_redirected_to']
        # Σύνδεσμος που δεν ζητήθηκε (HostTimeouts) κρατά την προηγούμενη
        # ώρα ελέγχου, ώστε στο επόμενο πέρασμα να ελεγχθεί πρώτος
        archival.updated = now
    log.info('URL check saved: %r', archival)
    changed = first_check or previous_status_id != status_id or edited
    model.repo.commit_and_remove()
    return changed


def _resource_metadata_modified(resource):
    value = resource.get('metadata_modified')
    if isinstance(value, datetime.datetime):
        return value
    try:
        return datetime.datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def notify_resource(resource, queue, cache_filepath):
    '''
    Broadcasts an IPipe notification that an resource archival has taken place
    (or at least the archival object is changed somehow).
    '''
    archiver_interfaces.IPipe.send_data('archived',
                                        resource_id=resource['id'],
                                        queue=queue,
                                        cache_filepath=cache_filepath)


def notify_package(package, queue):
    '''
    Broadcasts an IPipe notification that a package archival has taken place
    (or at least the archival object is changed somehow). e.g.
    ckanext-packagezip listens for this
    '''
    archiver_interfaces.IPipe.send_data('package-archived',
                                        package_id=package['id'],
                                        queue=queue)


def get_plugins_waiting_on_ipipe():
    return [observer.name for observer in
            p.PluginImplementations(archiver_interfaces.IPipe)]


def verify_https():
    from ckan.plugins.toolkit import config
    return toolkit.asbool(config.get('ckanext-archiver.verify_https', True))


def _clean_content_type(ct):
    # For now we should remove the charset from the content type and
    # handle it better, differently, later on.
    if 'charset' in ct:
        # Κρατά μόνο τον τύπο, κόβοντας στο ';' ή στο πρώτο κενό
        # (π.χ. "text/html; charset=utf-8" ή "text/html charset=utf-8")
        return re.split(r'[;\s]', ct.strip(), 1)[0]
    return ct


def _set_user_agent_string(headers):
    '''
    Update the passed headers object with a `User-Agent` key, if there is a
    USER_AGENT_STRING option in settings.
    '''
    from ckanext.archiver import default_settings as settings
    ua_str = settings.USER_AGENT_STRING
    if ua_str is not None:
        headers['User-Agent'] = ua_str
    return headers


def tidy_url(url):
    '''
    Given a URL it does various checks before returning a tidied version
    suitable for calling.

    It may raise LinkInvalidError if the URL has a problem.
    '''

    # Find out if it has unicode characters, and if it does, quote them
    # so we are left with an ascii string
    try:
        url = url.decode('ascii')
    except Exception:
        parts = list(urlparse(url))
        # Κωδικοποιούνται μόνο οι χαρακτήρες εκτός ASCII (π.χ. ελληνικά ονόματα
        # αρχείων). Τα ήδη κωδικοποιημένα %XX και οι χαρακτήρες με ειδική
        # σημασία στο path μένουν ως έχουν· αλλιώς το %CE%B1 γινόταν %25CE%25B1
        # και ο server απαντούσε 404.
        parts[2] = quote(parts[2].encode('utf-8'), safe="/%:@!$&'()*+,;=")
        url = urlunparse(parts)
    url = str(url)

    # strip whitespace from url
    # (browsers appear to do this)
    url = url.strip()

    # Use urllib3 to parse the url ahead of time, since that is what
    # requests uses, but when it does it during a GET, errors are not
    # caught well
    try:
        parsed_url = urllib3.util.parse_url(url)
    except urllib3.exceptions.LocationParseError as e:
        raise LinkInvalidError(_('URL parsing failure: %s') % e)

    # Check we aren't using any schemes we shouldn't be.
    # Scheme is case-insensitive.
    if not parsed_url.scheme or not parsed_url.scheme.lower() in ALLOWED_SCHEMES:
        raise LinkInvalidError(_('Invalid url scheme. Please use one of: %s') %
                               ' '.join(ALLOWED_SCHEMES))

    if not parsed_url.host:
        raise LinkInvalidError(_('URL parsing failure - did not find a host name'))

    return url


def _save_resource(resource, response, max_file_size, chunk_size=1024*16):
    """
    Write the response content to disk.

    Returns a tuple:

        (file length: int, content hash: string, saved file path: string)
    """
    resource_hash = hashlib.sha1()
    length = 0

    fd, tmp_resource_file_path = tempfile.mkstemp()
    os.close(fd)

    try:
        with open(tmp_resource_file_path, 'wb') as fp:
            for chunk in response.iter_content(chunk_size=chunk_size,
                                               decode_unicode=False):
                fp.write(chunk)
                length += len(chunk)
                resource_hash.update(chunk)

                if length >= max_file_size:
                    raise ChooseNotToDownload(
                        _("Content-length %s exceeds maximum allowed value %s") %
                        (length, max_file_size))
    except Exception:
        _cleanup_temp_file(tmp_resource_file_path, log)
        raise

    content_hash = str(resource_hash.hexdigest())
    return length, content_hash, tmp_resource_file_path


def save_archival(resource, status_id, reason, url_redirected_to,
                  download_result, archive_result, log):
    '''Writes to the archival table the result of an attempt to download
    the resource.

    May propagate a CkanError.
    '''
    now = datetime.datetime.now()

    from ckanext.archiver.model import Archival, Status
    from ckan import model

    archival = Archival.get_for_resource(resource['id'])
    first_archival = not archival
    previous_archival_was_broken = None
    if not archival:
        archival = Archival.create(resource['id'])
        model.Session.add(archival)
    else:
        log.info('Archival from before: %r', archival)
        previous_archival_was_broken = archival.is_broken

    try:
        revision = model.Session.query(model.Revision) \
            .get(resource['revision_id'])
        archival.resource_timestamp = revision.timestamp
    except AttributeError:
        # CKAN 2.9 doesn't have revisions, so we can't get a timestamp
        pass

    # Details of the latest archival attempt
    archival.status_id = status_id
    archival.is_broken = Status.is_status_broken(status_id)
    archival.reason = reason
    archival.url_redirected_to = url_redirected_to

    # Details of successful archival
    if archival.is_broken is False:
        archival.cache_filepath = archive_result['cache_filepath']
        archival.cache_url = archive_result['cache_url']
        archival.size = download_result['size']
        archival.mimetype = download_result['mimetype']
        archival.hash = download_result['hash']
        archival.etag = download_result['headers'].get('etag')
        archival.last_modified = download_result['headers'].get('last-modified')

    # History
    if archival.is_broken is False:
        archival.last_success = now
        archival.first_failure = None
        archival.failure_count = 0
    else:
        log.info('First_archival=%r Previous_broken=%r Failure_count=%r' %
                 (first_archival, previous_archival_was_broken,
                  archival.failure_count))
        if first_archival or previous_archival_was_broken is False:
            # i.e. this is the first failure (or the first archival)
            archival.first_failure = now
            archival.failure_count = 1
        else:
            archival.failure_count += 1

    archival.updated = now
    log.info('Archival saved: %r', archival)
    model.repo.commit_and_remove()


def requests_wrapper(log, func, *args, **kwargs):
    '''
    Run a requests command, catching exceptions and reraising them as
    DownloadException. Status errors, such as 404 or 500 do not cause
    exceptions, instead exposed as not response.ok.
    e.g.
    >>> requests_wrapper(log, requests.get, url, timeout=url_timeout)
    runs:
        res = requests.get(url, timeout=url_timeout)
    '''
    from .requests_ssl import SSLv3Adapter
    try:
        try:
            response = func(*args, **kwargs)
        except requests.exceptions.ConnectionError as e:
            if 'SSL23_GET_SERVER_HELLO' not in str(e):
                raise
            log.info('SSLv23 failed so trying again using SSLv3: %r', args)
            requests_session = requests.Session()
            requests_session.mount('https://', SSLv3Adapter())
            func = {requests.get: requests_session.get,
                    requests.post: requests_session.post}[func]
            response = func(*args, **kwargs)

    except requests.exceptions.ConnectionError as e:
        raise DownloadException(_('Connection error: %s') % e)
    except requests.exceptions.HTTPError as e:
        raise DownloadException(_('Invalid HTTP response: %s') % e)
    except requests.exceptions.Timeout:
        raise DownloadException(_('Connection timed out after %ss') % kwargs.get('timeout', '?'))
    except requests.exceptions.TooManyRedirects:
        raise DownloadException(_('Too many redirects'))
    except requests.exceptions.RequestException as e:
        raise DownloadException(_('Error downloading: %s') % e)
    except Exception as e:
        if os.environ.get('DEBUG'):
            raise
        raise DownloadException(_('Error with the download: %s') % e)
    return response


def ogc_request(context, resource, service, wms_version):
    original_url = url = resource['url']
    # Remove parameters
    url = url.split('?')[0]
    # Add WMS GetCapabilities parameters
    url += '?service=%s&request=GetCapabilities&version=%s' % \
           (service, wms_version)
    resource['url'] = url
    # Make the request
    response = download(context, resource)
    # Restore the URL so that it doesn't get saved in the actual resource
    resource['url'] = original_url
    return response


def wms_1_3_request(context, resource):
    res = ogc_request(context, resource, 'WMS', '1.3')
    res['request_type'] = 'WMS 1.3'
    return res


def wms_1_1_1_request(context, resource):
    res = ogc_request(context, resource, 'WMS', '1.1.1')
    res['request_type'] = 'WMS 1.1.1'
    return res


def wfs_request(context, resource):
    res = ogc_request(context, resource, 'WFS', '2.0')
    res['request_type'] = 'WFS 2.0'
    return res


def api_request(context, resource):
    '''
    Tries making requests as if the resource is a well-known sort of API to try
    and get a valid response. If it does it returns the response, otherwise
    Archives the response and stores what sort of request elicited it.
    '''
    # 'resource' holds the results of the download and will get saved. Only if
    # an API request is successful do we want to save the details of it.
    # However download() gets altered for these API requests. So only give
    # download() a copy of 'resource'.
    for api_request_func in wms_1_3_request, wms_1_1_1_request, wfs_request:
        resource_copy = copy.deepcopy(resource)
        try:
            download_dict = api_request_func(context, resource_copy)
        except ArchiverError as e:
            log.info('API %s error: %r, %r "%s"', api_request_func,
                     e, e.args, resource.get('url'))
            continue
        except Exception as e:
            if os.environ.get('DEBUG'):
                raise
            log.error('Uncaught API %s failure: %r, %r', api_request_func,
                      e, e.args)
            continue

        return download_dict


def is_id(id_string):
    '''Tells the client if the string looks like a revision id or not'''
    reg_ex = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    return bool(re.match(reg_ex, id_string))


def response_is_an_api_error(response_body):
    '''Some APIs return errors as the response body, but HTTP status 200. So we
    need to check response bodies for these error messages.
    '''
    response_sample = response_body[:250]  # to allow for <?xml> and <!DOCTYPE> lines

    # WMS spec
    # e.g. https://map.bgs.ac.uk/ArcGIS/services/BGS_Detailed_Geology/MapServer/WMSServer?service=abc
    # <?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
    # <ServiceExceptionReport version="1.3.0"
    if '<ServiceExceptionReport' in response_sample:
        return True

    # This appears to be an alternative - I can't find the spec.
    # e.g. http://sedsh13.sedsh.gov.uk/ArcGIS/services/HS/Historic_Scotland/MapServer/WFSServer?service=abc
    # <ows:ExceptionReport version='1.1.0' language='en' xmlns:ows='http://www.opengis.net/ows'>
    # <ows:Exception exceptionCode='NoApplicableCode'><ows:ExceptionText>Wrong service type.
    # </ows:ExceptionText></ows:Exception></ows:ExceptionReport>
    if '<ows:ExceptionReport' in response_sample:
        return True


def clean():
    """
    Remove all archived resources.
    """
    log.error("clean task not implemented yet")


def link_checker(context, data):
    """
    Check that the resource's url is valid, and accepts a HEAD request.

    Redirects are not followed - they simple return 'location' in the headers.

    data is a JSON dict describing the link:
        { 'url': url,
          'url_timeout': url_timeout }

    Raises LinkInvalidError if the URL is invalid
    Raises LinkHeadRequestError if HEAD request fails
    Raises LinkHeadMethodNotSupported if server says HEAD is not supported

    Returns a json dict of the headers of the request
    """
    data = json.loads(data)
    url_timeout = data.get('url_timeout', 30)

    error_message = ''
    headers = {'User-Agent': USER_AGENT}

    url = tidy_url(data['url'])

    # Send a head request
    try:
        res = requests.head(url, timeout=url_timeout)
        headers = res.headers
    except http.client.InvalidURL as ve:
        log.error("Could not make a head request to %r, error is: %s."
                  " Package is: %r. This sometimes happens when using an old version of requests on a URL"
                  " which issues a 301 redirect. Version=%s", url, ve, data.get('package'), requests.__version__)
        raise LinkHeadRequestError(_("Invalid URL or Redirect Link"))
    except ValueError as ve:
        log.error("Could not make a head request to %r, error is: %s. Package is: %r.", url, ve, data.get('package'))
        raise LinkHeadRequestError(_("Could not make HEAD request"))
    except requests.exceptions.ConnectionError as e:
        raise LinkHeadRequestError(_('Connection error: %s') % e)
    except requests.exceptions.HTTPError as e:
        raise LinkHeadRequestError(_('Invalid HTTP response: %s') % e)
    except requests.exceptions.Timeout:
        raise LinkHeadRequestError(_('Connection timed out after %ss') % url_timeout)
    except requests.exceptions.TooManyRedirects:
        raise LinkHeadRequestError(_('Too many redirects'))
    except requests.exceptions.RequestException as e:
        raise LinkHeadRequestError(_('Error during request: %s') % e)
    except Exception as e:
        raise LinkHeadRequestError(_('Error with the request: %s') % e)
    else:
        if res.status_code == 405:
            # this suggests a GET request may be ok, so proceed to that
            # in the download
            raise LinkHeadMethodNotSupported()
        if not res.ok or res.status_code >= 400:
            error_message = _('Server returned HTTP error status: %s %s') % \
                (res.status_code, res.reason)
            raise LinkHeadRequestError(error_message)
    return json.dumps(dict(headers))
