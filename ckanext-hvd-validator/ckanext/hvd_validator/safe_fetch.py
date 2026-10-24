"""SSRF-safe HTTP fetching with DNS validation and connection pinning."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
import socket
import ssl
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError
from urllib3.util import Timeout


class UnsafeFetchUrl(ValueError):
    """Raised when a fetch target violates the SSRF policy."""


@dataclass(frozen=True)
class ValidatedTarget:
    """A URL bound to the public IP addresses validated for one request hop."""

    url: str
    scheme: str
    hostname: str
    port: int
    addresses: tuple[str, ...]

    @property
    def authority(self) -> str:
        host = f"[{self.hostname}]" if ":" in self.hostname else self.hostname
        default_port = 443 if self.scheme == "https" else 80
        return host if self.port == default_port else f"{host}:{self.port}"

    @property
    def request_target(self) -> str:
        parsed = urlparse(self.url)
        return urlunparse(
            ("", "", parsed.path or "/", parsed.params, parsed.query, "")
        )


def _normalized_ip(
    ip_address: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if "%" in ip_address:
        raise ValueError("Scoped IP addresses are not valid fetch targets.")

    parsed = ipaddress.ip_address(ip_address)
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        return parsed.ipv4_mapped
    return parsed


def is_blocked_ip(ip_address: str) -> bool:
    try:
        ip = _normalized_ip(ip_address)
    except ValueError:
        return True

    return any(
        (
            not ip.is_global,
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def _canonical_hostname(hostname: str) -> str:
    hostname = hostname.strip().lower().rstrip(".")
    if not hostname:
        raise UnsafeFetchUrl("URL hostname is missing.")

    try:
        literal_ip = _normalized_ip(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        return str(literal_ip)

    if hostname == "localhost" or "." not in hostname:
        raise UnsafeFetchUrl("Local hostnames cannot be fetched.")

    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeFetchUrl("URL hostname is invalid.") from exc


def _resolved_public_addresses(addr_infos: Iterable[tuple]) -> tuple[str, ...]:
    addresses = []
    seen = set()

    for info in addr_infos:
        family = info[0]
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue

        raw_address = info[4][0]
        try:
            normalized = str(_normalized_ip(raw_address))
        except ValueError as exc:
            raise UnsafeFetchUrl(
                "URL resolved to an invalid network address."
            ) from exc

        # Reject the whole DNS result if even one answer is unsafe. Selecting
        # only the public subset would allow resolver-order and rebinding
        # ambiguities to re-enter the connection path.
        if is_blocked_ip(normalized):
            raise UnsafeFetchUrl("URL resolves to a blocked network address.")

        if normalized not in seen:
            seen.add(normalized)
            addresses.append(normalized)

    if not addresses:
        raise UnsafeFetchUrl("URL hostname did not resolve to an IP address.")

    return tuple(addresses)


def resolve_and_validate_target(url: str) -> ValidatedTarget:
    """Resolve once and retain every validated address for the connect."""
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
        username = parsed.username
        password = parsed.password
    except (TypeError, ValueError) as exc:
        raise UnsafeFetchUrl("URL is malformed.") from exc

    if scheme not in {"http", "https"}:
        raise UnsafeFetchUrl("Only HTTP(S) URLs can be fetched.")
    if username is not None or password is not None:
        raise UnsafeFetchUrl("Credentials in fetch URLs are not allowed.")
    if not hostname:
        raise UnsafeFetchUrl("URL hostname is missing.")

    hostname = _canonical_hostname(hostname)
    port = port or (443 if scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise UnsafeFetchUrl("URL port is invalid.")

    try:
        addr_infos = socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except (socket.gaierror, UnicodeError) as exc:
        raise UnsafeFetchUrl("URL hostname could not be resolved.") from exc

    return ValidatedTarget(
        url=url,
        scheme=scheme,
        hostname=hostname,
        port=port,
        addresses=_resolved_public_addresses(addr_infos),
    )


class _PinnedConnectionMixin:
    """Open a socket to a validated numeric IP without hostname resolution."""

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
        ip = _normalized_ip(self.pinned_ip)
        family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)

        try:
            sock.settimeout(self.timeout)
            for option in self.socket_options or ():
                sock.setsockopt(*option)

            if self.source_address:
                sock.bind(self.source_address)

            address = (
                (str(ip), self.port, 0, 0)
                if family == socket.AF_INET6
                else (str(ip), self.port)
            )
            sock.connect(address)

            peer_ip = str(_normalized_ip(sock.getpeername()[0]))
            if peer_ip not in self.validated_addresses:
                raise UnsafeFetchUrl(
                    "Connected peer is outside the validated address set."
                )
            return sock
        except UnsafeFetchUrl:
            sock.close()
            raise
        except socket.timeout as exc:
            sock.close()
            raise ConnectTimeoutError(
                self,
                "Connection to validated address timed out. "
                f"(connect timeout={self.timeout})",
            ) from exc
        except OSError as exc:
            sock.close()
            raise NewConnectionError(
                self,
                f"Failed to connect to validated address: {exc}",
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

    def close(self):
        try:
            super().close()
        finally:
            self._pinned_pool.close()


def _urllib3_timeout(timeout) -> Timeout:
    if isinstance(timeout, tuple):
        if len(timeout) != 2:
            raise ValueError(
                "Timeout tuple must contain connect and read values."
            )
        return Timeout(connect=timeout[0], read=timeout[1])
    return Timeout.from_float(timeout)


def _ca_bundle_settings() -> dict[str, str]:
    path = (
        os.environ.get("REQUESTS_CA_BUNDLE")
        or os.environ.get("CURL_CA_BUNDLE")
        or requests.certs.where()
    )
    if os.path.isdir(path):
        return {"ca_cert_dir": path}
    return {"ca_certs": path}


def _build_response(target: ValidatedTarget, pool, raw, headers):
    response = _PinnedResponse(pool)
    response.status_code = raw.status
    response.headers = CaseInsensitiveDict(raw.headers)
    response.raw = raw
    response.url = target.url
    response.reason = raw.reason
    response.encoding = get_encoding_from_headers(response.headers)

    request = requests.Request("GET", target.url, headers=headers)
    response.request = request.prepare()
    return response


class PinnedHttpTransport:
    """Fetch a validated target without DNS or environment proxies."""

    def _pool_for(self, target: ValidatedTarget, pinned_ip: str, timeout):
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

    def get(self, target: ValidatedTarget, *, timeout, headers, stream=False):
        request_headers = dict(headers or {})
        for key in tuple(request_headers):
            if key.lower() == "host":
                del request_headers[key]
        request_headers["Host"] = target.authority

        last_error = None
        for pinned_ip in target.addresses:
            pool = self._pool_for(target, pinned_ip, timeout)
            try:
                raw = pool.urlopen(
                    "GET",
                    target.request_target,
                    headers=request_headers,
                    retries=False,
                    redirect=False,
                    preload_content=False,
                    decode_content=False,
                    timeout=_urllib3_timeout(timeout),
                )
                return _build_response(target, pool, raw, request_headers)
            except UnsafeFetchUrl:
                pool.close()
                raise
            except Exception as exc:
                pool.close()
                last_error = exc

        raise requests.ConnectionError(
            "Could not connect to any validated address."
        ) from last_error


_DEFAULT_TRANSPORT = PinnedHttpTransport()


def safe_get(
    url: str,
    *,
    timeout,
    headers,
    stream: bool = False,
    max_redirects: int = 3,
    transport: PinnedHttpTransport | None = None,
):
    """GET a URL, resolving and pinning every redirect hop independently."""
    current_url = url
    transport = transport or _DEFAULT_TRANSPORT

    for _ in range(max_redirects + 1):
        target = resolve_and_validate_target(current_url)
        response = transport.get(
            target,
            timeout=timeout,
            headers=headers,
            stream=stream,
        )
        if not response.is_redirect:
            return response

        location = response.headers.get("Location")
        response.close()
        if not location:
            raise UnsafeFetchUrl(
                "Redirect response is missing a Location header."
            )
        current_url = urljoin(current_url, location)

    raise UnsafeFetchUrl("Too many redirects while fetching URL.")
