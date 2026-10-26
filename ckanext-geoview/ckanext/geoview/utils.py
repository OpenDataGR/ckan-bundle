# -*- coding: utf-8 -*-

import json
import logging
from six.moves.urllib.parse import parse_qsl, urlencode, urlsplit

import requests

from ckan import plugins as p
from ckan.plugins import toolkit
from ckanext.geoview import safe_http

log = logging.getLogger(__name__)

GEOJSON_MAX_FILE_SIZE = 25 * 1024 * 1024
GEOJSON_MAX_FEATURES = 500
GEOJSON_MAX_COORDINATES = 400000


SERVICE_PROXY_MAX_FILE_SIZE_MB = 3
SERVICE_PROXY_CONNECT_TIMEOUT = 10
SERVICE_PROXY_READ_TIMEOUT = 90
SERVICE_PROXY_MAX_REDIRECTS = 10
SERVICE_PROXY_MAX_CONNECT_TIMEOUT = 60
SERVICE_PROXY_MAX_READ_TIMEOUT = 300
SERVICE_PROXY_MAX_REDIRECT_LIMIT = 20
CHUNK_SIZE = 512

# HTTP request parameters that may conflict with OGC services
# protocols and should be excluded from proxied calls
OGC_EXCLUDED_PARAMS = [
    "service",
    "version",
    "request",
    "outputformat",
    "typename",
    "layers",
    "srsname",
    "bbox",
    "maxfeatures",
]


def _plain_text_response(status_code, body):
    if toolkit.check_ckan_version("2.9"):
        from flask import make_response

        response = make_response(body, status_code)
    else:
        response = toolkit.response
        response.status_int = status_code
        response.body = body

    response.content_type = "text/plain"
    response.charset = "utf-8"
    return response


def _service_proxy_too_large_response(max_file_size, actual_size):
    message = (
        "Content is too large to be proxied. Allowed file size: {allowed}, "
        "Content-Length: {actual}."
    ).format(allowed=max_file_size, actual=actual_size)
    return _plain_text_response(409, message)


def _as_config_list(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return value
    return [item for item in value.replace(",", " ").split() if item]


def _force_http_for_configured_hosts(parts):
    hosts = [
        host.lower()
        for host in _as_config_list(
            toolkit.config.get("ckanext.geoview.force_http_hosts")
        )
    ]
    hostname = (parts.hostname or "").lower()
    if hostname in hosts and parts.scheme == "https":
        log.info("Forcing HTTP for proxied geoview service host %s", hostname)
        return parts._replace(scheme="http")
    return parts


def proxy_service_resource(request, context, data_dict):
    """ Chunked proxy for resources. To make sure that the file is not too
    large, first, we try to get the content length from the headers.
    If the headers to not contain a content length (if it is a chinked
    response), we only transfer as long as the transferred data is less
    than the maximum file size. """
    resource_id = data_dict["resource_id"]
    log.info("Proxify resource {id}".format(id=resource_id))
    resource = toolkit.get_action("resource_show")(context, {"id": resource_id})
    url = resource["url"]
    return proxy_service_url(request, url)


def _prepare_service_proxy_request(req, url):
    method = req.environ["REQUEST_METHOD"]
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        port = parts.port
    except (TypeError, ValueError) as exc:
        raise safe_http.UnsafeProxyUrl("URL is malformed.") from exc
    if not parts.scheme or not parts.netloc:
        raise safe_http.UnsafeProxyUrl("URL is missing a scheme or host.")
    if not hostname:
        raise safe_http.UnsafeProxyUrl("URL hostname is missing.")
    if port is not None and not 1 <= port <= 65535:
        raise safe_http.UnsafeProxyUrl("URL port is invalid.")
    parts = _force_http_for_configured_hosts(parts)
    params = parse_qsl(parts.query, keep_blank_values=True)

    if not p.toolkit.asbool(
        toolkit.config.get(
            "ckanext.geoview.forward_ogc_request_params", "False"
        )
    ):
        # Remove conflicting parameters from the stored resource URL.  The
        # viewer's current OGC parameters are appended below unchanged.
        params = [
            (key, value)
            for key, value in params
            if key.lower() not in OGC_EXCLUDED_PARAMS
        ]
        parts = parts._replace(query=urlencode(params))

    parts = parts._replace(fragment="")
    url = parts.geturl()

    headers = {}
    body = None
    if method == "POST":
        content_type = req.environ.get("CONTENT_TYPE")
        if content_type:
            headers["Content-Type"] = content_type
        body = req.get_data() if hasattr(req, "get_data") else req.body
    else:
        method = "GET"
        query_string = req.query_string
        if isinstance(query_string, bytes):
            query_string = query_string.decode("latin-1")
        if query_string:
            separator = "&" if urlsplit(url).query else "?"
            url = "{0}{1}{2}".format(url, separator, query_string)

    return method, url, headers, body


def proxy_service_url(req, url):
    upstream_response = None
    try:
        method, url, headers, body = _prepare_service_proxy_request(req, url)

        upstream_response = safe_http.safe_request(
            method,
            url,
            headers=headers,
            body=body,
            timeout=(
                get_service_proxy_connect_timeout(),
                get_service_proxy_read_timeout(),
            ),
            max_redirects=get_service_proxy_max_redirects(),
        )

        max_file_size = get_service_proxy_max_file_size()
        content_length = upstream_response.headers.get("content-length")
        try:
            declared_size = int(content_length) if content_length else None
        except (TypeError, ValueError):
            declared_size = None
        if declared_size is not None and declared_size > max_file_size:
            log.warning(
                "Geoview service proxy rejected an oversized response from %s",
                _hostname_for_log(url),
            )
            return _service_proxy_too_large_response(
                max_file_size,
                declared_size,
            )
        if toolkit.check_ckan_version("2.9"):
            from flask import make_response

            response = make_response()
        else:
            response = toolkit.response

        response.content_type = upstream_response.headers.get(
            "content-type", "application/octet-stream"
        )
        if upstream_response.encoding:
            response.charset = upstream_response.encoding

        length = 0
        for chunk in upstream_response.iter_content(chunk_size=CHUNK_SIZE):
            length += len(chunk)
            if length > max_file_size:
                log.warning(
                    "Geoview service proxy stopped an oversized stream from %s",
                    _hostname_for_log(url),
                )
                return _service_proxy_too_large_response(max_file_size, length)

            if toolkit.check_ckan_version("2.9"):
                response.data += chunk
            else:
                response.body_file.write(chunk)

    except safe_http.UnsafeProxyUrl as error:
        log.warning(
            "Geoview service proxy blocked host %s: %s",
            _hostname_for_log(url),
            error,
        )
        toolkit.abort(
            409,
            detail="Could not proxy resource because the upstream URL is not allowed.",
        )
    except requests.exceptions.Timeout:
        log.warning(
            "Geoview service proxy timed out while contacting host %s",
            _hostname_for_log(url),
        )
        toolkit.abort(
            504,
            detail="Could not proxy resource because the connection timed out.",
        )
    except requests.exceptions.ConnectionError as error:
        log.warning(
            "Geoview service proxy could not connect to host %s: %s",
            _hostname_for_log(url),
            error,
        )
        toolkit.abort(
            502,
            detail="Could not proxy resource because an upstream connection error occurred.",
        )
    finally:
        if upstream_response is not None:
            upstream_response.close()
    return response


def _hostname_for_log(url):
    try:
        return urlsplit(url).hostname or "<missing>"
    except (TypeError, ValueError):
        return "<invalid>"


def get_common_map_config():
    """Returns a dict with all configuration options related to the common
    base map (ie those starting with 'ckanext.spatial.common_map.')
    """
    namespace = "ckanext.spatial.common_map."
    return dict(
        [
            (k.replace(namespace, ""), v)
            for k, v in toolkit.config.items()
            if k.startswith(namespace)
        ]
    )


def get_shapefile_viewer_config():
    """
        Returns a dict with all configuration options related to the
        Shapefile viewer (ie those starting with 'ckanext.geoview.shp_viewer.')
    """
    namespace = "ckanext.geoview.shp_viewer."
    return dict(
        [
            (k.replace(namespace, ""), v)
            for k, v in toolkit.config.items()
            if k.startswith(namespace)
        ]
    )


def get_max_file_size():
    return _get_positive_int_config(
        "ckanext.geoview.geojson.max_file_size", GEOJSON_MAX_FILE_SIZE
    )


def get_max_features():
    return _get_positive_int_config(
        "ckanext.geoview.geojson.max_features", GEOJSON_MAX_FEATURES
    )


def get_max_coordinates():
    return _get_positive_int_config(
        "ckanext.geoview.geojson.max_coordinates", GEOJSON_MAX_COORDINATES
    )


def get_service_proxy_max_file_size():
    max_file_size_mb = _get_positive_int_config(
        "ckanext.geoview.service_proxy.max_file_size_mb",
        SERVICE_PROXY_MAX_FILE_SIZE_MB,
    )
    return max_file_size_mb * 1024 * 1024


def get_service_proxy_connect_timeout():
    return _get_positive_int_config(
        "ckanext.geoview.service_proxy.connect_timeout",
        SERVICE_PROXY_CONNECT_TIMEOUT,
        SERVICE_PROXY_MAX_CONNECT_TIMEOUT,
    )


def get_service_proxy_read_timeout():
    return _get_positive_int_config(
        "ckanext.geoview.service_proxy.read_timeout",
        SERVICE_PROXY_READ_TIMEOUT,
        SERVICE_PROXY_MAX_READ_TIMEOUT,
    )


def get_service_proxy_max_redirects():
    return _get_positive_int_config(
        "ckanext.geoview.service_proxy.max_redirects",
        SERVICE_PROXY_MAX_REDIRECTS,
        SERVICE_PROXY_MAX_REDIRECT_LIMIT,
    )


def _get_positive_int_config(config_key, default, maximum=None):
    value = toolkit.config.get(config_key)
    if value is None or (hasattr(value, "strip") and not value.strip()):
        return default

    try:
        value = int(value)
    except (TypeError, ValueError):
        return default

    if value <= 0:
        return default
    if maximum is not None:
        return min(value, maximum)
    return value


def get_openlayers_viewer_config():
    """
        Returns a dict with all configuration options related to the
        OpenLayers viewer (ie those starting with 'ckanext.geoview.ol_viewer.')
    """
    namespace = "ckanext.geoview.ol_viewer."
    return dict(
        [
            (k.replace(namespace, ""), v)
            for k, v in toolkit.config.items()
            if k.startswith(namespace)
        ]
    )


def load_basemaps(basemapsFile):

    try:
        with open(basemapsFile) as config_file:
            basemapsConfig = json.load(config_file)
    except Exception as inst:
        msg = "Couldn't read basemaps config from %r: %s" % (
            basemapsFile,
            inst,
        )
        raise Exception(msg)

    return basemapsConfig


def get_proxified_service_url(data_dict):
    """
    :param data_dict: contains a resource and package dict
    :type data_dict: dictionary
    """
    url = toolkit.url_for(
        action="proxy_service",
        controller='service_proxy',
        id=data_dict["package"]["name"],
        resource_id=data_dict["resource"]["id"],
    )
    log.debug("Proxified url is {0}".format(url))
    return url
