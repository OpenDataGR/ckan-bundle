import pytest
import requests

from ckanext.hvd_validator import safe_fetch


PUBLIC_V4 = "93.184.216.34"
PUBLIC_V4_SECONDARY = "93.184.216.35"
PUBLIC_V6 = "2606:4700:4700::1111"


def _addr_info(address, family=None):
    family = family or (
        safe_fetch.socket.AF_INET6
        if ":" in address
        else safe_fetch.socket.AF_INET
    )
    sockaddr = (
        (address, 443, 0, 0)
        if family == safe_fetch.socket.AF_INET6
        else (address, 443)
    )
    return (family, safe_fetch.socket.SOCK_STREAM, 6, "", sockaddr)


def _install_dns(monkeypatch, *addresses):
    calls = []

    def getaddrinfo(hostname, port, **kwargs):
        calls.append((hostname, port, kwargs))
        return [_addr_info(address) for address in addresses]

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", getaddrinfo)
    return calls


@pytest.mark.parametrize(
    "url, address, expected_hostname, expected_port",
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
def test_resolve_and_validate_public_target(
    monkeypatch,
    url,
    address,
    expected_hostname,
    expected_port,
):
    calls = _install_dns(monkeypatch, address)

    target = safe_fetch.resolve_and_validate_target(url)

    assert target.hostname == expected_hostname
    assert target.port == expected_port
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
def test_blocked_address_is_rejected(monkeypatch, address):
    _install_dns(monkeypatch, address)

    with pytest.raises(safe_fetch.UnsafeFetchUrl, match="blocked"):
        safe_fetch.resolve_and_validate_target("https://example.test/data")


def test_mixed_public_and_private_dns_result_is_rejected(monkeypatch):
    _install_dns(monkeypatch, PUBLIC_V4, "127.0.0.1")

    with pytest.raises(safe_fetch.UnsafeFetchUrl, match="blocked"):
        safe_fetch.resolve_and_validate_target("https://example.test/data")


def test_duplicate_dns_addresses_are_normalized(monkeypatch):
    _install_dns(monkeypatch, PUBLIC_V4, PUBLIC_V4)

    target = safe_fetch.resolve_and_validate_target(
        "https://EXAMPLE.TEST./data"
    )

    assert target.hostname == "example.test"
    assert target.addresses == (PUBLIC_V4,)


@pytest.mark.parametrize(
    "url, message",
    [
        ("file:///etc/passwd", "HTTP"),
        ("//example.test/path", "HTTP"),
        ("https:///path", "hostname"),
        ("https://localhost/path", "Local"),
        ("https://intranet/path", "Local"),
        ("https://user:pass@example.test/path", "Credentials"),
        ("https://example.test:99999/path", "malformed"),
    ],
)
def test_invalid_url_is_rejected(monkeypatch, url, message):
    monkeypatch.setattr(
        safe_fetch.socket,
        "getaddrinfo",
        lambda *args, **kwargs: pytest.fail("DNS must not be used"),
    )

    with pytest.raises(safe_fetch.UnsafeFetchUrl, match=message):
        safe_fetch.resolve_and_validate_target(url)


def test_dns_failure_is_reported(monkeypatch):
    def fail(*args, **kwargs):
        raise safe_fetch.socket.gaierror("not found")

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", fail)

    with pytest.raises(
        safe_fetch.UnsafeFetchUrl, match="could not be resolved"
    ):
        safe_fetch.resolve_and_validate_target("https://example.test/data")


def test_empty_dns_result_is_rejected(monkeypatch):
    monkeypatch.setattr(
        safe_fetch.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [],
    )

    with pytest.raises(safe_fetch.UnsafeFetchUrl, match="did not resolve"):
        safe_fetch.resolve_and_validate_target("https://example.test/data")


class FakeSocket:
    def __init__(self, peer_ip):
        self.peer_ip = peer_ip
        self.timeout = None
        self.connected_to = None
        self.closed = False
        self.options = []

    def settimeout(self, timeout):
        self.timeout = timeout

    def setsockopt(self, *option):
        self.options.append(option)

    def bind(self, address):
        self.bound_to = address

    def connect(self, address):
        self.connected_to = address

    def getpeername(self):
        return (self.peer_ip, 443)

    def close(self):
        self.closed = True


def _pinned_connection(validated_addresses=(PUBLIC_V4,)):
    return safe_fetch._PinnedHTTPConnection(
        host="example.test",
        port=443,
        timeout=5,
        pinned_ip=validated_addresses[0],
        validated_addresses=validated_addresses,
    )


def test_pinned_socket_uses_numeric_ip_without_dns(monkeypatch):
    fake_socket = FakeSocket(PUBLIC_V4)
    monkeypatch.setattr(
        safe_fetch.socket,
        "socket",
        lambda *args, **kwargs: fake_socket,
    )
    monkeypatch.setattr(
        safe_fetch.socket,
        "getaddrinfo",
        lambda *args, **kwargs: pytest.fail("Pinned connect must not use DNS"),
    )

    result = _pinned_connection()._new_conn()

    assert result is fake_socket
    assert fake_socket.connected_to == (PUBLIC_V4, 443)
    assert fake_socket.timeout == 5


def test_connected_peer_must_be_in_validated_set(monkeypatch):
    fake_socket = FakeSocket(PUBLIC_V4_SECONDARY)
    monkeypatch.setattr(
        safe_fetch.socket,
        "socket",
        lambda *args, **kwargs: fake_socket,
    )

    with pytest.raises(safe_fetch.UnsafeFetchUrl, match="peer"):
        _pinned_connection()._new_conn()

    assert fake_socket.closed is True


def test_https_pool_preserves_hostname_for_sni_and_certificate_check():
    target = safe_fetch.ValidatedTarget(
        url="https://example.test/data",
        scheme="https",
        hostname="example.test",
        port=443,
        addresses=(PUBLIC_V4,),
    )

    pool = safe_fetch.PinnedHttpTransport()._pool_for(
        target, PUBLIC_V4, timeout=5
    )

    assert pool.host == "example.test"
    assert pool.assert_hostname == "example.test"
    assert pool.cert_reqs == safe_fetch.ssl.CERT_REQUIRED
    assert pool.conn_kw["pinned_ip"] == PUBLIC_V4
    assert pool.proxy is None
    pool.close()


def test_https_pool_honors_standard_custom_ca_bundle(monkeypatch):
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/tmp/custom-ca.pem")
    target = safe_fetch.ValidatedTarget(
        url="https://example.test/data",
        scheme="https",
        hostname="example.test",
        port=443,
        addresses=(PUBLIC_V4,),
    )

    pool = safe_fetch.PinnedHttpTransport()._pool_for(
        target, PUBLIC_V4, timeout=5
    )

    assert pool.ca_certs == "/tmp/custom-ca.pem"
    pool.close()


def test_https_pool_supports_custom_ca_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path))
    target = safe_fetch.ValidatedTarget(
        url="https://example.test/data",
        scheme="https",
        hostname="example.test",
        port=443,
        addresses=(PUBLIC_V4,),
    )

    pool = safe_fetch.PinnedHttpTransport()._pool_for(
        target, PUBLIC_V4, timeout=5
    )

    assert pool.ca_cert_dir == str(tmp_path)
    assert pool.ca_certs is None
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


def test_transport_uses_original_host_header_and_request_target(monkeypatch):
    raw = FakeRawResponse()
    pool = FakePool(result=raw)
    transport = safe_fetch.PinnedHttpTransport()
    monkeypatch.setattr(transport, "_pool_for", lambda *args, **kwargs: pool)
    target = safe_fetch.ValidatedTarget(
        url="https://example.test:8443/path?q=1#fragment",
        scheme="https",
        hostname="example.test",
        port=8443,
        addresses=(PUBLIC_V4,),
    )

    response = transport.get(
        target,
        timeout=5,
        headers={"Accept": "application/rdf+xml", "host": "attacker.test"},
        stream=True,
    )

    method, request_target, kwargs = pool.calls[0]
    assert method == "GET"
    assert request_target == "/path?q=1"
    assert kwargs["headers"]["Host"] == "example.test:8443"
    assert "host" not in kwargs["headers"]
    assert kwargs["redirect"] is False
    response.close()
    assert pool.closed is True


def test_transport_falls_back_only_to_another_validated_ip(monkeypatch):
    first_pool = FakePool(error=OSError("unreachable"))
    second_pool = FakePool(result=FakeRawResponse())
    pools = iter([first_pool, second_pool])
    selected = []
    transport = safe_fetch.PinnedHttpTransport()

    def pool_for(target, pinned_ip, timeout):
        selected.append(pinned_ip)
        return next(pools)

    monkeypatch.setattr(transport, "_pool_for", pool_for)
    target = safe_fetch.ValidatedTarget(
        url="http://example.test/data",
        scheme="http",
        hostname="example.test",
        port=80,
        addresses=(PUBLIC_V4, PUBLIC_V4_SECONDARY),
    )

    response = transport.get(target, timeout=5, headers={})

    assert selected == [PUBLIC_V4, PUBLIC_V4_SECONDARY]
    assert first_pool.closed is True
    response.close()


class FakeRedirectResponse:
    def __init__(self, location=None, status=302):
        self.status_code = status
        self.headers = {}
        if location is not None:
            self.headers["Location"] = location
        self.closed = False

    @property
    def is_redirect(self):
        return self.status_code in {301, 302, 303, 307, 308}

    def close(self):
        self.closed = True


class RecordingTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.targets = []

    def get(self, target, **kwargs):
        self.targets.append(target)
        return next(self.responses)


def test_safe_get_resolves_once_per_hop_and_revalidates_redirect(monkeypatch):
    dns_calls = []

    def getaddrinfo(hostname, port, **kwargs):
        dns_calls.append(hostname)
        address = (
            PUBLIC_V4
            if hostname == "first.test"
            else PUBLIC_V4_SECONDARY
        )
        return [_addr_info(address)]

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", getaddrinfo)
    redirect = FakeRedirectResponse("https://second.test/final")
    final = FakeRedirectResponse(status=200)
    transport = RecordingTransport([redirect, final])

    result = safe_fetch.safe_get(
        "https://first.test/start",
        timeout=5,
        headers={},
        transport=transport,
    )

    assert result is final
    assert redirect.closed is True
    assert dns_calls == ["first.test", "second.test"]
    assert [target.addresses for target in transport.targets] == [
        (PUBLIC_V4,),
        (PUBLIC_V4_SECONDARY,),
    ]


def test_private_redirect_is_blocked_before_second_request(monkeypatch):
    answers = iter([PUBLIC_V4, "127.0.0.1"])
    monkeypatch.setattr(
        safe_fetch.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [_addr_info(next(answers))],
    )
    redirect = FakeRedirectResponse("http://private.test/admin")
    transport = RecordingTransport([redirect])

    with pytest.raises(safe_fetch.UnsafeFetchUrl, match="blocked"):
        safe_fetch.safe_get(
            "https://public.test/start",
            timeout=5,
            headers={},
            transport=transport,
        )

    assert redirect.closed is True
    assert len(transport.targets) == 1


def test_toctou_second_dns_answer_is_never_requested(monkeypatch):
    dns_answers = iter([[PUBLIC_V4], ["127.0.0.1"]])
    dns_calls = []

    def getaddrinfo(*args, **kwargs):
        dns_calls.append(args[0])
        return [_addr_info(address) for address in next(dns_answers)]

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", getaddrinfo)
    final = FakeRedirectResponse(status=200)
    transport = RecordingTransport([final])

    result = safe_fetch.safe_get(
        "https://attacker.test/data",
        timeout=5,
        headers={},
        transport=transport,
    )

    assert result is final
    assert dns_calls == ["attacker.test"]
    assert transport.targets[0].addresses == (PUBLIC_V4,)


def test_missing_redirect_location_closes_response(monkeypatch):
    _install_dns(monkeypatch, PUBLIC_V4)
    redirect = FakeRedirectResponse()

    with pytest.raises(safe_fetch.UnsafeFetchUrl, match="Location"):
        safe_fetch.safe_get(
            "https://example.test/start",
            timeout=5,
            headers={},
            transport=RecordingTransport([redirect]),
        )

    assert redirect.closed is True


def test_redirect_limit_closes_every_intermediate_response(monkeypatch):
    _install_dns(monkeypatch, PUBLIC_V4)
    responses = [
        FakeRedirectResponse("/again"),
        FakeRedirectResponse("/again"),
    ]

    with pytest.raises(safe_fetch.UnsafeFetchUrl, match="Too many"):
        safe_fetch.safe_get(
            "https://example.test/start",
            timeout=5,
            headers={},
            max_redirects=1,
            transport=RecordingTransport(responses),
        )

    assert all(response.closed for response in responses)


def test_transport_does_not_use_requests_environment_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8888")
    target = safe_fetch.ValidatedTarget(
        url="https://example.test/data",
        scheme="https",
        hostname="example.test",
        port=443,
        addresses=(PUBLIC_V4,),
    )

    pool = safe_fetch.PinnedHttpTransport()._pool_for(
        target, PUBLIC_V4, timeout=5
    )

    assert pool.proxy is None
    pool.close()


def test_all_validated_addresses_failure_raises_connection_error(monkeypatch):
    pool = FakePool(error=OSError("unreachable"))
    transport = safe_fetch.PinnedHttpTransport()
    monkeypatch.setattr(transport, "_pool_for", lambda *args, **kwargs: pool)
    target = safe_fetch.ValidatedTarget(
        url="http://example.test/data",
        scheme="http",
        hostname="example.test",
        port=80,
        addresses=(PUBLIC_V4,),
    )

    with pytest.raises(requests.ConnectionError):
        transport.get(target, timeout=5, headers={})

    assert pool.closed is True
