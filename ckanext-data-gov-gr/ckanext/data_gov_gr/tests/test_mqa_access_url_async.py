import requests

from ckanext.data_gov_gr.logic import mqa_access_url_cache
from ckanext.data_gov_gr.logic import mqa_calculator
from ckanext.data_gov_gr.logic.mqa_calculator import MQACalculator


def test_access_url_async_is_disabled_by_default(monkeypatch):
    cache_checked = []
    enqueued = []

    monkeypatch.setattr(mqa_access_url_cache, '_get_config_value', lambda key, default: default)
    monkeypatch.setattr(
        mqa_access_url_cache,
        'get_cached_access_url_result',
        lambda url: cache_checked.append(url) or None,
    )
    monkeypatch.setattr(
        mqa_access_url_cache,
        'enqueue_access_url_check',
        lambda url: enqueued.append(url) or True,
    )

    def raise_timeout(*args, **kwargs):
        raise requests.ReadTimeout('slow endpoint')

    monkeypatch.setattr(mqa_calculator.requests, 'head', raise_timeout)

    calculator = MQACalculator(check_urls=True, url_check_timeout=2)

    assert mqa_access_url_cache.is_async_enabled() is False
    assert calculator._check_url_accessibility('https://example.test', url_role='access_url') is False
    assert cache_checked == []
    assert enqueued == []
    assert calculator._status_code_cache['https://example.test'] == 'Timeout after 2 seconds'


def test_access_url_uses_cached_async_success(monkeypatch):
    monkeypatch.setattr(mqa_access_url_cache, 'is_async_enabled', lambda: True)
    monkeypatch.setattr(
        mqa_access_url_cache,
        'get_cached_access_url_result',
        lambda url: {
            'accessible': True,
            'status_code': 200,
            'method': 'HEAD',
        },
    )
    monkeypatch.setattr(
        mqa_calculator.requests,
        'head',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('HEAD should not run')),
    )

    calculator = MQACalculator(check_urls=True)

    assert calculator._check_url_accessibility('https://example.test', url_role='access_url') is True
    assert calculator._status_code_cache['https://example.test'] == '200 (verified asynchronously, HEAD)'


def test_access_url_timeout_enqueues_async_check(monkeypatch):
    enqueued = []

    monkeypatch.setattr(mqa_access_url_cache, 'is_async_enabled', lambda: True)
    monkeypatch.setattr(mqa_access_url_cache, 'get_cached_access_url_result', lambda url: None)
    monkeypatch.setattr(
        mqa_access_url_cache,
        'enqueue_access_url_check',
        lambda url: enqueued.append(url) or True,
    )

    def raise_timeout(*args, **kwargs):
        raise requests.ReadTimeout('slow endpoint')

    monkeypatch.setattr(mqa_calculator.requests, 'head', raise_timeout)

    calculator = MQACalculator(check_urls=True, url_check_timeout=2)

    assert calculator._check_url_accessibility('https://example.test', url_role='access_url') is False
    assert enqueued == ['https://example.test']
    assert calculator._status_code_cache['https://example.test'] == (
        'Timeout after 2 seconds; queued for async verification'
    )


def test_download_url_timeout_does_not_enqueue_access_url_check(monkeypatch):
    enqueued = []

    monkeypatch.setattr(mqa_access_url_cache, 'is_async_enabled', lambda: True)
    monkeypatch.setattr(
        mqa_access_url_cache,
        'enqueue_access_url_check',
        lambda url: enqueued.append(url) or True,
    )

    def raise_timeout(*args, **kwargs):
        raise requests.ReadTimeout('slow endpoint')

    monkeypatch.setattr(mqa_calculator.requests, 'head', raise_timeout)

    calculator = MQACalculator(check_urls=True, url_check_timeout=2)

    assert calculator._check_url_accessibility('https://example.test/file', url_role='download_url') is False
    assert enqueued == []
    assert calculator._status_code_cache['https://example.test/file'] == 'Timeout after 2 seconds'


def test_resource_url_fallback_does_not_use_access_url_async_cache(monkeypatch):
    cache_checked = []

    monkeypatch.setattr(mqa_access_url_cache, 'is_async_enabled', lambda: True)
    monkeypatch.setattr(
        mqa_access_url_cache,
        'get_cached_access_url_result',
        lambda url: cache_checked.append(url) or {
            'accessible': True,
            'status_code': 200,
            'method': 'HEAD',
        },
    )

    class Response:
        status_code = 200
        elapsed = None

    monkeypatch.setattr(mqa_calculator.requests, 'head', lambda *args, **kwargs: Response())

    calculator = MQACalculator(check_urls=True)
    resource = {'url': 'https://example.test/file'}

    assert calculator._get_resource_access_url_role(resource) == 'generic'
    assert calculator._check_url_accessibility(
        calculator._get_resource_access_url(resource),
        url_role=calculator._get_resource_access_url_role(resource),
    ) is True
    assert cache_checked == []


def test_async_check_uses_get_fallback_after_head_failure(monkeypatch):
    stored_results = []
    released_locks = []
    calls = []

    def fake_check_url_once(url, method, timeout):
        calls.append((url, method, timeout))
        if method == 'HEAD':
            return {
                'url': url,
                'accessible': False,
                'status_code': None,
                'method': 'HEAD',
                'checked_at': '2026-06-22T00:00:00Z',
                'elapsed': 10,
                'error': 'Timeout after 10 seconds',
            }
        return {
            'url': url,
            'accessible': True,
            'status_code': 200,
            'method': 'GET',
            'checked_at': '2026-06-22T00:00:01Z',
            'elapsed': 6.5,
            'error': None,
        }

    monkeypatch.setattr(mqa_access_url_cache, 'check_url_once', fake_check_url_once)
    monkeypatch.setattr(
        mqa_access_url_cache,
        'set_cached_access_url_result',
        lambda url, result: stored_results.append((url, result)) or True,
    )
    monkeypatch.setattr(
        mqa_access_url_cache,
        'release_lock',
        lambda url: released_locks.append(url),
    )

    result = mqa_access_url_cache.check_access_url_async('https://example.test', timeout=10)

    assert result['accessible'] is True
    assert result['method'] == 'GET'
    assert calls == [
        ('https://example.test', 'HEAD', 10),
        ('https://example.test', 'GET', 10),
    ]
    assert stored_results == [('https://example.test', result)]
    assert released_locks == ['https://example.test']
