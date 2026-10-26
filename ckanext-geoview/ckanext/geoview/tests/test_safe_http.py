import socket

import pytest
import requests

from ckanext.geoview import safe_http


PUBLIC_V4 = "93.184.216.34"
PUBLIC_V4_SECONDARY = "93.184.216.35"
PUBLIC_V6 = "2606:4700:4700::1111"


def _addr_info(address, port=443):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (
        (address, port, 0, 0)
        if family == socket.AF_INET6
        else (address, port)
    )
    return (family, socket.SOCK_STREAM, 6, "", sockaddr)


def _install_dns(monkeypatch, *addresses):
    calls = []

    def getaddrinfo(hostname, port, **kwargs):
        calls.append((hostname, port, kwargs))
        return [_addr_info(address, port) for address in addresses]

    monkeypatch.setattr(safe_http.socket, "getaddrinfo", getaddrinfo)
    return calls


@pytest.mark.parametrize(
    "url,address,hostname,port",
    [
        ("https://example.test/path", PUBLIC_V4, "example.test", 443),
        ("http://example.test:8080/path", PUBLIC_V4, "example.test", 8080),
        (
            "https://[2606:4700:4700::1111]/path",
            PUBLIC_V6,
            PUBLIC_V6,
            443,
        ),
    ],
)
def test_resolves_public_targets_once(
    monkeypatch, url, address, hostname, port
):
    calls = _install_dns(monkeypatch, address)

    target = safe_http.resolve_and_validate_target(url)

    assert target.hostname == hostname
    assert target.port == port
    assert target.addresses == (address,)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
    ],
)
def test_rejects_non_public_addresses(monkeypatch, address):
    _install_dns(monkeypatch, address)

    with pytest.raises(safe_http.UnsafeProxyUrl, match="blocked"):
        safe_http.resolve_and_validate_target("https://example.test/data")


def test_rejects_mixed_public_private_dns(monkeypatch):
    _install_dns(monkeypatch, PUBLIC_V4, "127.0.0.1")

    with pytest.raises(safe_http.UnsafeProxyUrl, match="blocked"):
        safe_http.resolve_and_validate_target("https://example.test/data")


@pytest.mark.parametrize(
    "url,message",
    [
        ("file:///etc/passwd", "HTTP"),
        ("//example.test/path", "HTTP"),
        ("https:///path", "hostname"),
        ("https://localhost/path", "Local"),
        ("https://intranet/path", "Local"),
        ("https://user:pass@example.test/path", "Credentials"),
        ("https://example.test:99999/path", "malformed"),
        ("https://example.test\\@127.0.0.1/path", "authority"),
    ],
)
def test_rejects_invalid_urls_without_dns(monkeypatch, url, message):
    monkeypatch.setattr(
        safe_http.socket,
        "getaddrinfo",
        lambda *args, **kwargs: pytest.fail("DNS must not be used"),
    )

    with pytest.raises(safe_http.UnsafeProxyUrl, match=message):
        safe_http.resolve_and_validate_target(url)


class FakeSocket:
    def __init__(self, peer_ip):
        self.peer_ip = peer_ip
        self.timeout = None
        self.connected_to = None
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def setsockopt(self, *option):
        pass

    def bind(self, address):
        self.bound_to = address

    def connect(self, address):
        self.connected_to = address

    def getpeername(self):
        return (self.peer_ip, 443)

    def close(self):
        self.closed = True


def _pinned_connection(validated_addresses=(PUBLIC_V4,)):
    return safe_http._PinnedHTTPConnection(
        host="example.test",
        port=443,
        timeout=5,
        pinned_ip=validated_addresses[0],
        validated_addresses=validated_addresses,
    )


def test_pinned_socket_connects_to_numeric_ip_without_dns(monkeypatch):
    fake_socket = FakeSocket(PUBLIC_V4)
    monkeypatch.setattr(
        safe_http.socket,
        "socket",
        lambda *args, **kwargs: fake_socket,
    )
    monkeypatch.setattr(
        safe_http.socket,
        "getaddrinfo",
        lambda *args, **kwargs: pytest.fail("Pinned connect must not use DNS"),
    )

    result = _pinned_connection()._new_conn()

    assert result is fake_socket
    assert fake_socket.connected_to == (PUBLIC_V4, 443)
    assert fake_socket.timeout == 5


def test_connected_peer_must_match_validated_set(monkeypatch):
    fake_socket = FakeSocket(PUBLIC_V4_SECONDARY)
    monkeypatch.setattr(
        safe_http.socket,
        "socket",
        lambda *args, **kwargs: fake_socket,
    )

    with pytest.raises(safe_http.UnsafeProxyUrl, match="peer"):
        _pinned_connection()._new_conn()

    assert fake_socket.closed is True


def test_https_pool_preserves_hostname_for_sni_and_certificate_check():
    target = safe_http.ValidatedTarget(
        url="https://example.test/data",
        scheme="https",
        hostname="example.test",
        port=443,
        addresses=(PUBLIC_V4,),
    )

    pool = safe_http.PinnedHttpTransport()._pool_for(
        target, PUBLIC_V4, timeout=(10, 90)
    )

    assert pool.host == "example.test"
    assert pool.assert_hostname == "example.test"
    assert pool.cert_reqs == safe_http.ssl.CERT_REQUIRED
    assert pool.conn_kw["pinned_ip"] == PUBLIC_V4
    assert pool.proxy is None
    pool.close()


class FakeRawResponse:
    status = 200
    headers = {"Content-Type": "text/plain"}
    reason = "OK"

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class FakePool:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []
        self.closed = False

    def urlopen(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return self.result

    def close(self):
        self.closed = True


def test_transport_preserves_host_method_body_and_request_target(monkeypatch):
    pool = FakePool(result=FakeRawResponse())
    transport = safe_http.PinnedHttpTransport()
    monkeypatch.setattr(transport, "_pool_for", lambda *args, **kwargs: pool)
    target = safe_http.ValidatedTarget(
        url="https://example.test:8443/path?q=1",
        scheme="https",
        hostname="example.test",
        port=8443,
        addresses=(PUBLIC_V4,),
    )

    response = transport.request(
        target,
        method="POST",
        timeout=(10, 90),
        headers={"Content-Type": "application/xml", "host": "attacker.test"},
        body=b"payload",
    )

    method, request_target, kwargs = pool.calls[0]
    assert method == "POST"
    assert request_target == "/path?q=1"
    assert kwargs["body"] == b"payload"
    assert kwargs["headers"]["Host"] == "example.test:8443"
    assert "host" not in kwargs["headers"]
    assert kwargs["redirect"] is False
    response.close()
    assert pool.closed is True


def test_transport_falls_back_only_to_another_validated_ip(monkeypatch):
    first_pool = FakePool(error=OSError("unreachable"))
    second_pool = FakePool(result=FakeRawResponse())
    pools = iter((first_pool, second_pool))
    selected = []
    transport = safe_http.PinnedHttpTransport()

    def pool_for(target, pinned_ip, timeout):
        selected.append(pinned_ip)
        return next(pools)

    monkeypatch.setattr(transport, "_pool_for", pool_for)
    target = safe_http.ValidatedTarget(
        url="http://example.test/data",
        scheme="http",
        hostname="example.test",
        port=80,
        addresses=(PUBLIC_V4, PUBLIC_V4_SECONDARY),
    )

    response = transport.request(
        target,
        method="GET",
        timeout=(10, 90),
    )

    assert selected == [PUBLIC_V4, PUBLIC_V4_SECONDARY]
    assert first_pool.closed is True
    response.close()


class FakeResponse:
    def __init__(self, status=200, location=None):
        self.status_code = status
        self.headers = {}
        if location is not None:
            self.headers["Location"] = location
        self.closed = False

    def close(self):
        self.closed = True


class RecordingTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, target, **kwargs):
        self.calls.append((target, kwargs))
        return next(self.responses)


def test_each_redirect_is_resolved_and_validated(monkeypatch):
    dns_calls = []

    def getaddrinfo(hostname, port, **kwargs):
        dns_calls.append(hostname)
        address = PUBLIC_V4 if hostname == "first.test" else PUBLIC_V4_SECONDARY
        return [_addr_info(address, port)]

    monkeypatch.setattr(safe_http.socket, "getaddrinfo", getaddrinfo)
    redirect = FakeResponse(302, "https://second.test/final")
    final = FakeResponse()
    transport = RecordingTransport((redirect, final))

    result = safe_http.safe_request(
        "GET",
        "https://first.test/start",
        timeout=(10, 90),
        transport=transport,
    )

    assert result is final
    assert redirect.closed is True
    assert dns_calls == ["first.test", "second.test"]
    assert [call[0].addresses for call in transport.calls] == [
        (PUBLIC_V4,),
        (PUBLIC_V4_SECONDARY,),
    ]


def test_private_redirect_is_blocked_before_second_request(monkeypatch):
    answers = iter((PUBLIC_V4, "127.0.0.1"))
    monkeypatch.setattr(
        safe_http.socket,
        "getaddrinfo",
        lambda hostname, port, **kwargs: [_addr_info(next(answers), port)],
    )
    redirect = FakeResponse(302, "http://private.test/admin")
    transport = RecordingTransport((redirect,))

    with pytest.raises(safe_http.UnsafeProxyUrl, match="blocked"):
        safe_http.safe_request(
            "GET",
            "https://public.test/start",
            timeout=(10, 90),
            transport=transport,
        )

    assert redirect.closed is True
    assert len(transport.calls) == 1


def test_redirect_loop_is_stopped(monkeypatch):
    _install_dns(monkeypatch, PUBLIC_V4)
    redirect = FakeResponse(302, "/same")
    transport = RecordingTransport((redirect,))

    with pytest.raises(safe_http.UnsafeProxyUrl, match="loop"):
        safe_http.safe_request(
            "GET",
            "https://example.test/same",
            timeout=(10, 90),
            transport=transport,
        )

    assert redirect.closed is True


def test_redirect_limit_closes_intermediate_responses(monkeypatch):
    _install_dns(monkeypatch, PUBLIC_V4)
    first = FakeResponse(302, "/second")
    second = FakeResponse(302, "/third")
    transport = RecordingTransport((first, second))

    with pytest.raises(safe_http.UnsafeProxyUrl, match="Too many"):
        safe_http.safe_request(
            "GET",
            "https://example.test/first",
            timeout=(10, 90),
            max_redirects=1,
            transport=transport,
        )

    assert first.closed is True
    assert second.closed is True


@pytest.mark.parametrize(
    "status,expected_method,expected_body",
    [
        (302, "GET", None),
        (303, "GET", None),
        (307, "POST", b"payload"),
        (308, "POST", b"payload"),
    ],
)
def test_redirect_method_semantics(
    monkeypatch, status, expected_method, expected_body
):
    _install_dns(monkeypatch, PUBLIC_V4)
    redirect = FakeResponse(status, "/final")
    final = FakeResponse()
    transport = RecordingTransport((redirect, final))

    safe_http.safe_request(
        "POST",
        "https://example.test/start",
        timeout=(10, 90),
        headers={"Content-Type": "application/xml"},
        body=b"payload",
        transport=transport,
    )

    second_call = transport.calls[1][1]
    assert second_call["method"] == expected_method
    assert second_call["body"] == expected_body
    if expected_method == "GET":
        assert "Content-Type" not in second_call["headers"]


def test_dns_is_not_repeated_between_validation_and_connect(monkeypatch):
    answers = iter(((PUBLIC_V4,), ("127.0.0.1",)))
    dns_calls = []

    def getaddrinfo(hostname, port, **kwargs):
        dns_calls.append(hostname)
        return [_addr_info(address, port) for address in next(answers)]

    monkeypatch.setattr(safe_http.socket, "getaddrinfo", getaddrinfo)
    final = FakeResponse()
    transport = RecordingTransport((final,))

    result = safe_http.safe_request(
        "GET",
        "https://attacker.test/data",
        timeout=(10, 90),
        transport=transport,
    )

    assert result is final
    assert dns_calls == ["attacker.test"]
    assert transport.calls[0][0].addresses == (PUBLIC_V4,)


def test_transport_does_not_use_environment_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8888")
    target = safe_http.ValidatedTarget(
        url="https://example.test/data",
        scheme="https",
        hostname="example.test",
        port=443,
        addresses=(PUBLIC_V4,),
    )

    pool = safe_http.PinnedHttpTransport()._pool_for(
        target, PUBLIC_V4, timeout=(10, 90)
    )

    assert pool.proxy is None
    pool.close()
