# -*- coding: utf-8 -*-
"""Redis cache and RQ enqueue helpers for MQA access_url checks."""

import datetime
import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional

import requests

log = logging.getLogger(__name__)

CONFIG_PREFIX = 'ckanext.data_gov_gr.mqa.access_url'

DEFAULT_ASYNC_ENABLED = False
DEFAULT_QUEUE = 'mqa_access_url'
DEFAULT_ASYNC_TIMEOUT = 10
DEFAULT_SUCCESS_TTL = 86400
DEFAULT_FAILURE_TTL = 3600
DEFAULT_LOCK_TTL = 300
DEFAULT_JOB_TIMEOUT_BUFFER = 10


def _get_config_value(key: str, default: Any) -> Any:
    try:
        from ckan.common import config

        return config.get(key, default)
    except Exception:
        return default


def _asbool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ('true', '1', 'yes', 'on')
    return bool(value)


def _asint(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def is_async_enabled() -> bool:
    return _asbool(
        _get_config_value(
            f'{CONFIG_PREFIX}_async_enabled',
            DEFAULT_ASYNC_ENABLED,
        ),
        DEFAULT_ASYNC_ENABLED,
    )


def get_queue_name() -> str:
    return str(_get_config_value(f'{CONFIG_PREFIX}_queue', DEFAULT_QUEUE))


def get_async_timeout() -> int:
    return _asint(
        _get_config_value(
            f'{CONFIG_PREFIX}_async_timeout',
            DEFAULT_ASYNC_TIMEOUT,
        ),
        DEFAULT_ASYNC_TIMEOUT,
    )


def get_success_ttl() -> int:
    return _asint(
        _get_config_value(
            f'{CONFIG_PREFIX}_success_ttl',
            DEFAULT_SUCCESS_TTL,
        ),
        DEFAULT_SUCCESS_TTL,
    )


def get_failure_ttl() -> int:
    return _asint(
        _get_config_value(
            f'{CONFIG_PREFIX}_failure_ttl',
            DEFAULT_FAILURE_TTL,
        ),
        DEFAULT_FAILURE_TTL,
    )


def get_lock_ttl() -> int:
    return _asint(
        _get_config_value(
            f'{CONFIG_PREFIX}_lock_ttl',
            DEFAULT_LOCK_TTL,
        ),
        DEFAULT_LOCK_TTL,
    )


def get_job_timeout() -> int:
    configured = _get_config_value(f'{CONFIG_PREFIX}_job_timeout', None)
    if configured is not None:
        return _asint(configured, (get_async_timeout() * 2) + DEFAULT_JOB_TIMEOUT_BUFFER)
    return (get_async_timeout() * 2) + DEFAULT_JOB_TIMEOUT_BUFFER


def _site_id() -> str:
    return str(_get_config_value('ckan.site_id', 'default'))


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode('utf-8')).hexdigest()


def _cache_key(url: str) -> str:
    return f'ckan:{_site_id()}:ckanext:data_gov_gr:mqa:access_url:{_url_hash(url)}'


def _lock_key(url: str) -> str:
    return f'ckan:{_site_id()}:ckanext:data_gov_gr:mqa:access_url_lock:{_url_hash(url)}'


def _connect_to_redis():
    try:
        from ckan.lib.redis import connect_to_redis

        return connect_to_redis()
    except Exception as exc:
        log.debug('Could not connect to Redis for MQA access_url cache: %s', exc)
        return None


def get_cached_access_url_result(url: str) -> Optional[Dict[str, Any]]:
    redis_conn = _connect_to_redis()
    if not redis_conn:
        return None

    try:
        raw_value = redis_conn.get(_cache_key(url))
    except Exception as exc:
        log.debug('Could not read MQA access_url cache for %s: %s', url, exc)
        return None

    if not raw_value:
        return None

    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode('utf-8')

    try:
        result = json.loads(raw_value)
    except (TypeError, ValueError) as exc:
        log.debug('Invalid MQA access_url cache value for %s: %s', url, exc)
        return None

    return result if isinstance(result, dict) else None


def set_cached_access_url_result(url: str, result: Dict[str, Any]) -> bool:
    redis_conn = _connect_to_redis()
    if not redis_conn:
        return False

    ttl = get_success_ttl() if result.get('accessible') else get_failure_ttl()
    try:
        redis_conn.setex(
            _cache_key(url),
            ttl,
            json.dumps(result, ensure_ascii=False),
        )
        return True
    except Exception as exc:
        log.debug('Could not write MQA access_url cache for %s: %s', url, exc)
        return False


def _acquire_lock(url: str) -> bool:
    redis_conn = _connect_to_redis()
    if not redis_conn:
        return False

    try:
        return bool(redis_conn.set(_lock_key(url), '1', ex=get_lock_ttl(), nx=True))
    except Exception as exc:
        log.debug('Could not acquire MQA access_url lock for %s: %s', url, exc)
        return False


def release_lock(url: str) -> None:
    redis_conn = _connect_to_redis()
    if not redis_conn:
        return

    try:
        redis_conn.delete(_lock_key(url))
    except Exception as exc:
        log.debug('Could not release MQA access_url lock for %s: %s', url, exc)


def enqueue_access_url_check(url: str) -> bool:
    if not url or not is_async_enabled():
        return False

    if not _acquire_lock(url):
        return False

    try:
        from ckan.lib import jobs
        from ckanext.data_gov_gr.jobs import check_mqa_access_url

        jobs.enqueue(
            check_mqa_access_url,
            args=[url],
            title='MQA access_url check',
            queue=get_queue_name(),
            rq_kwargs={'timeout': get_job_timeout()},
        )
        return True
    except Exception as exc:
        release_lock(url)
        log.warning('Could not enqueue MQA access_url check for %s: %s', url, exc)
        return False


def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def format_request_exception(exc: requests.RequestException, timeout: int) -> str:
    if isinstance(exc, requests.Timeout):
        return f'Timeout after {timeout} seconds'
    if getattr(exc, 'response', None) is not None:
        status_code = getattr(exc.response, 'status_code', None)
        if status_code:
            return f'HTTP {status_code}'
    return str(exc)


def format_cached_status(result: Dict[str, Any]) -> str:
    suffix = 'verified asynchronously'
    status_code = result.get('status_code')
    method = result.get('method')

    if status_code:
        if method:
            return f'{status_code} ({suffix}, {method})'
        return f'{status_code} ({suffix})'

    error = result.get('error')
    if error:
        return f'{error} ({suffix})'

    return suffix


def build_result(
    url: str,
    accessible: bool,
    method: str,
    elapsed: float,
    status_code: Optional[int] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        'url': url,
        'accessible': bool(accessible),
        'status_code': status_code,
        'method': method,
        'checked_at': _now_iso(),
        'elapsed': round(elapsed, 3),
        'error': error,
    }


def check_url_once(url: str, method: str, timeout: int) -> Dict[str, Any]:
    start = time.monotonic()
    response = None

    try:
        if method == 'HEAD':
            response = requests.head(url, timeout=timeout, allow_redirects=True)
        elif method == 'GET':
            response = requests.get(
                url,
                timeout=timeout,
                allow_redirects=True,
                stream=True,
            )
        else:
            raise ValueError(f'Unsupported HTTP method: {method}')

        status_code = response.status_code
        return build_result(
            url=url,
            accessible=200 <= status_code < 400,
            status_code=status_code,
            method=method,
            elapsed=time.monotonic() - start,
            error=None if 200 <= status_code < 400 else f'HTTP {status_code}',
        )
    except requests.RequestException as exc:
        return build_result(
            url=url,
            accessible=False,
            status_code=getattr(getattr(exc, 'response', None), 'status_code', None),
            method=method,
            elapsed=time.monotonic() - start,
            error=format_request_exception(exc, timeout),
        )
    finally:
        if response is not None:
            response.close()


def check_access_url_async(url: str, timeout: Optional[int] = None) -> Dict[str, Any]:
    timeout = timeout or get_async_timeout()

    try:
        result = check_url_once(url, 'HEAD', timeout)
        if not result.get('accessible'):
            result = check_url_once(url, 'GET', timeout)

        set_cached_access_url_result(url, result)
        return result
    finally:
        release_lock(url)
