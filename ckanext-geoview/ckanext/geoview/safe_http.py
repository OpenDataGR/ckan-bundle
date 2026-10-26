"""SSRF-safe HTTP transport for the geoview service proxy.

Every request hop is resolved and validated once.  The TCP connection is then
opened directly to one of those validated numeric addresses while the original
hostname is retained for the HTTP Host header, TLS SNI and certificate checks.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
import socket
import ssl
from typing import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import (
    ConnectTimeoutError,
    NewConnectionError,
    ReadTimeoutError,
    SSLError as Urllib3SSLError,
)
from urllib3.util import Timeout


REDIRECT_STATUSES = frozenset((301, 302, 303, 307, 308))


class UnsafeProxyUrl(ValueError):
    """Raised when an upstream URL violates the service-proxy policy."""


@dataclass(frozen=True)
class ValidatedTarget:
    """A normalized URL bound to its validated public IP addresses."""

    url: str
    scheme: str
    hostname: str
    port: int
    addresses: tuple[str, ...]

    @property
    def authority(self) -> str:
        host = "[{0}]".format(self.hostname) if ":" in self.hostname else self.hostname
        default_port = 443 if self.scheme == "https" else 80
        return host if self.port == default_port else "{0}:{1}".format(host, self.port)

    @property
    def request_target(self) -> str:
        parts = urlsplit(self.url)
        return urlunsplit(("", "", parts.path or "/", parts.query, ""))

    @property
    def loop_key(self):
        return (
            self.scheme,
            self.hostname,
            self.port,
            self.request_target,
        )


def _normalized_ip(ip_address: str):
    if "%" in ip_address:
        raise ValueError("Scoped IP addresses are not valid proxy targets.")

    parsed = ipaddress.ip_address(ip_address)
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        return parsed.ipv4_mapped
    return parsed


def is_blocked_ip(ip_address: str) -> bool:
    """Return true unless ``ip_address`` is a globally routable address."""
    try:
        address = _normalized_ip(ip_address)
    except ValueError:
        return True

    return any(
        (
            not address.is_global,
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def _canonical_hostname(hostname: str) -> str:
    hostname = hostname.strip().lower().rstrip(".")
    if not hostname:
        raise UnsafeProxyUrl("URL hostname is missing.")

    try:
        literal_ip = _normalized_ip(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        return str(literal_ip)

    # Single-label names are normally resolved through local search domains and
    # are therefore unsuitable for a public-resource proxy.
    if hostname == "localhost" or "." not in hostname:
        raise UnsafeProxyUrl("Local hostnames are not allowed.")

    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeProxyUrl("URL hostname is invalid.") from exc


def _validated_addresses(addr_infos: Iterable[tuple]) -> tuple[str, ...]:
    addresses = []
    seen = set()

    for info in addr_infos:
        family = info[0]
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue

        try:
            address = str(_normalized_ip(info[4][0]))
        except ValueError as exc:
            raise UnsafeProxyUrl(
                "URL resolved to an invalid network address."
            ) from exc

        # Reject the complete DNS result when even one address is unsafe.  A
        # mixed public/private result must not let the HTTP stack choose the
        # address after validation.
        if is_blocked_ip(address):
            raise UnsafeProxyUrl("URL resolves to a blocked network address.")

        if address not in seen:
            seen.add(address)
            addresses.append(address)

    if not addresses:
        raise UnsafeProxyUrl("URL hostname did not resolve to an IP address.")

    return tuple(addresses)


def resolve_and_validate_target(url: str) -> ValidatedTarget:
    """Parse and resolve one request hop, retaining its public address set."""
    if not isinstance(url, str) or any(ord(character) < 32 for character in url):
        raise UnsafeProxyUrl("URL is malformed.")

    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        hostname = parts.hostname
        port = parts.port
        username = parts.username
        password = parts.password
    except (TypeError, ValueError) as exc:
        raise UnsafeProxyUrl("URL is malformed.") from exc

    if scheme not in ("http", "https"):
        raise UnsafeProxyUrl("Only HTTP(S) URLs can be proxied.")
    if "\\" in parts.netloc:
        raise UnsafeProxyUrl("URL authority is malformed.")
    if username is not None or password is not None:
        raise UnsafeProxyUrl("Credentials in proxy URLs are not allowed.")
    if not hostname:
        raise UnsafeProxyUrl("URL hostname is missing.")

    hostname = _canonical_hostname(hostname)
    port = port or (443 if scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise UnsafeProxyUrl("URL port is invalid.")

    try:
        addr_infos = socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except (socket.gaierror, UnicodeError) as exc:
        raise UnsafeProxyUrl("URL hostname could not be resolved.") from exc

    host_for_url = "[{0}]".format(hostname) if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    authority = (
        host_for_url
        if port == default_port
        else "{0}:{1}".format(host_for_url, port)
    )
    normalized_url = urlunsplit(
        (scheme, authority, parts.path or "/", parts.query, "")
    )

    return ValidatedTarget(
        url=normalized_url,
        scheme=scheme,
        hostname=hostname,
        port=port,
        addresses=_validated_addresses(addr_infos),
    )


class _PinnedConnectionMixin:
    """Connect to a validated numeric IP without performing another lookup."""

    def __init__(
        self,
        *args,
        pinned_ip: str,
        validated_addresses: tuple[str, ...],
        **kwargs,
    ):
        self.pinned_ip = str(_normalized_ip(pinned_ip))
        self.validated_addresses = frozenset(validated_addresses)
        super().__init__(*args, **kwargs)

    def _new_conn(self):
        address = _normalized_ip(self.pinned_ip)
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)

        try:
            sock.settimeout(self.timeout)
            for option in self.socket_options or ():
                sock.setsockopt(*option)

            if self.source_address:
                sock.bind(self.source_address)

            destination = (
                (str(address), self.port, 0, 0)
                if family == socket.AF_INET6
                else (str(address), self.port)
            )
            sock.connect(destination)

            peer_ip = str(_normalized_ip(sock.getpeername()[0]))
            if peer_ip not in self.validated_addresses:
                raise UnsafeProxyUrl(
                    "Connected peer is outside the validated address set."
                )
            return sock
        except UnsafeProxyUrl:
            sock.close()
            raise
        except socket.timeout as exc:
            sock.close()
            raise ConnectTimeoutError(
                self,
                "Connection to validated address timed out.",
            ) from exc
        except OSError as exc:
            sock.close()
            raise NewConnectionError(
                self,
                "Connection to validated address failed.",
            ) from exc


class _PinnedHTTPConnection(_PinnedConnectionMixin, HTTPConnection):
    pass


class _PinnedHTTPSConnection(_PinnedConnectionMixin, HTTPSConnection):
    pass


class _PinnedHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = _PinnedHTTPConnection


class _PinnedHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = _PinnedHTTPSConnection


class _PinnedResponse(requests.Response):
    def __init__(self, pool):
        super().__init__()
        self._pinned_pool = pool

    def iter_content(self, chunk_size=1, decode_unicode=False):
        try:
            for chunk in self.raw.stream(chunk_size, decode_content=True):
                if chunk:
                    yield chunk
        except ReadTimeoutError as exc:
            raise requests.Timeout("Upstream response timed out.") from exc

    def close(self):
        try:
            super().close()
        finally:
            self._pinned_pool.close()


def _urllib3_timeout(timeout) -> Timeout:
    if isinstance(timeout, tuple):
        if len(timeout) != 2:
            raise ValueError("Timeout must contain connect and read values.")
        return Timeout(connect=timeout[0], read=timeout[1])
    return Timeout.from_float(timeout)


def _ca_bundle_settings():
    path = (
        os.environ.get("REQUESTS_CA_BUNDLE")
        or os.environ.get("CURL_CA_BUNDLE")
        or requests.certs.where()
    )
    if os.path.isdir(path):
        return {"ca_cert_dir": path}
    return {"ca_certs": path}


def _build_response(target, pool, raw, method, headers, body):
    response = _PinnedResponse(pool)
    response.status_code = raw.status
    response.headers = CaseInsensitiveDict(raw.headers)
    response.raw = raw
    response.url = target.url
    response.reason = raw.reason
    response.encoding = get_encoding_from_headers(response.headers)
    response.request = requests.Request(
        method,
        target.url,
        headers=headers,
        data=body,
    ).prepare()
    return response


class PinnedHttpTransport:
    """Send a request without DNS re-resolution or environment proxies."""

    def _pool_for(self, target, pinned_ip, timeout):
        common = {
            "host": target.hostname,
            "port": target.port,
            "timeout": _urllib3_timeout(timeout),
            "maxsize": 1,
            "block": True,
            "pinned_ip": pinned_ip,
            "validated_addresses": target.addresses,
        }
        if target.scheme == "https":
            return _PinnedHTTPSConnectionPool(
                cert_reqs=ssl.CERT_REQUIRED,
                assert_hostname=target.hostname,
                **_ca_bundle_settings(),
                **common,
            )
        return _PinnedHTTPConnectionPool(**common)

    def request(self, target, *, method, timeout, headers=None, body=None):
        request_headers = dict(headers or {})
        for key in tuple(request_headers):
            if key.lower() == "host":
                del request_headers[key]
        request_headers["Host"] = target.authority

        last_error = None
        timed_out = False
        tls_failed = False

        for pinned_ip in target.addresses:
            pool = self._pool_for(target, pinned_ip, timeout)
            try:
                raw = pool.urlopen(
                    method,
                    target.request_target,
                    body=body,
                    headers=request_headers,
                    retries=False,
                    redirect=False,
                    preload_content=False,
                    decode_content=False,
                    timeout=_urllib3_timeout(timeout),
                )
                return _build_response(
                    target,
                    pool,
                    raw,
                    method,
                    request_headers,
                    body,
                )
            except UnsafeProxyUrl:
                pool.close()
                raise
            except (ConnectTimeoutError, ReadTimeoutError, socket.timeout) as exc:
                pool.close()
                last_error = exc
                timed_out = True
            except Urllib3SSLError as exc:
                pool.close()
                last_error = exc
                tls_failed = True
            except Exception as exc:
                pool.close()
                last_error = exc

        if timed_out:
            raise requests.Timeout("Upstream connection timed out.") from last_error
        if tls_failed:
            raise requests.SSLError("Upstream TLS validation failed.") from last_error
        raise requests.ConnectionError(
            "Could not connect to any validated upstream address."
        ) from last_error


_DEFAULT_TRANSPORT = PinnedHttpTransport()


def _redirect_request(status_code, method, headers, body):
    method = method.upper()
    if status_code == 303 and method != "HEAD":
        method = "GET"
    elif status_code in (301, 302) and method == "POST":
        method = "GET"

    if method in ("GET", "HEAD"):
        body = None
        headers = dict(headers or {})
        for key in tuple(headers):
            if key.lower() in ("content-length", "content-type", "transfer-encoding"):
                del headers[key]

    return method, headers, body


def safe_request(
    method,
    url,
    *,
    timeout,
    headers=None,
    body=None,
    max_redirects=10,
    transport=None,
):
    """Request a URL, independently validating and pinning every hop."""
    method = method.upper()
    if method not in ("GET", "POST"):
        raise UnsafeProxyUrl("Unsupported proxy request method.")

    current_url = url
    current_headers = dict(headers or {})
    current_body = body
    transport = transport or _DEFAULT_TRANSPORT
    visited = set()
    redirect_count = 0

    while True:
        target = resolve_and_validate_target(current_url)
        if target.loop_key in visited:
            raise UnsafeProxyUrl("Redirect loop detected.")
        visited.add(target.loop_key)

        response = transport.request(
            target,
            method=method,
            timeout=timeout,
            headers=current_headers,
            body=current_body,
        )
        if response.status_code not in REDIRECT_STATUSES:
            return response

        location = response.headers.get("Location")
        response.close()
        if not location:
            raise UnsafeProxyUrl(
                "Redirect response is missing a Location header."
            )
        if redirect_count >= max_redirects:
            raise UnsafeProxyUrl("Too many redirects while proxying URL.")

        redirect_count += 1
        current_url = urljoin(target.url, location)
        method, current_headers, current_body = _redirect_request(
            response.status_code,
            method,
            current_headers,
            current_body,
        )
