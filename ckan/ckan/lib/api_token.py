# -*- coding: utf-8 -*-
from __future__ import annotations

import jwt
import logging
from typing import Any, Iterable, Mapping, Optional
from calendar import timegm
from datetime import datetime

from flask import has_request_context

import ckan.plugins as plugins
import ckan.model as model
from ckan.common import config, request
from ckan.logic.schema import default_create_api_token_schema
from ckan.exceptions import CkanConfigurationException
from ckan.types import Schema


log = logging.getLogger(__name__)

_config_encode_secret = u"api_token.jwt.encode.secret"
_config_decode_secret = u"api_token.jwt.decode.secret"
_config_secret_fallback = u"SECRET_KEY"

_config_algorithm = u"api_token.jwt.algorithm"


def _get_plugins() -> Iterable[plugins.IApiToken]:
    return plugins.PluginImplementations(plugins.IApiToken)


def _get_algorithm() -> str:
    return config.get(_config_algorithm)


def _get_secret(encode: bool) -> str:
    config_key = _config_encode_secret if encode else _config_decode_secret
    secret: str = config.get(config_key)
    if not secret:
        secret = u"string:" + config.get(_config_secret_fallback)
    type_, value = secret.split(u":", 1)
    if type_ == u"file":
        with open(value, u"r") as key_file:
            value = key_file.read()

    if not value:
        raise CkanConfigurationException(
            (
                u"Neither `{key}` nor `{fallback}` specified. "
                u"Missing secret key is a critical security issue."
            ).format(
                key=config_key, fallback=_config_secret_fallback,
            )
        )
    return value


def into_seconds(dt: datetime) -> int:
    return timegm(dt.timetuple())


def get_schema() -> Schema:
    schema = default_create_api_token_schema()
    for plugin in _get_plugins():
        schema = plugin.create_api_token_schema(schema)
    return schema


def postprocess(data: dict[str, Any], jti: str,
                data_dict: dict[str, Any]) -> dict[str, Any]:
    for plugin in _get_plugins():
        data = plugin.postprocess_api_token(data, jti, data_dict)
    return data


def _invalid_token_log_context(encoded: str) -> str:
    try:
        token = str(encoded or u"")
        auth_scheme = u"raw"
        if token:
            first_part = token.split(None, 1)[0].lower()
            if first_part in {u"bearer", u"basic", u"digest"}:
                auth_scheme = first_part
            elif u" " in token:
                auth_scheme = u"other"

        context = [
            u"token_length={}".format(len(token)),
            u"dot_count={}".format(token.count(u".")),
            u"auth_scheme={}".format(auth_scheme),
        ]

        if has_request_context():
            context.extend([
                u"method={}".format(request.method),
                u"path={}".format(request.path),
                u"remote_addr={}".format(request.remote_addr),
                u"x_forwarded_for={!r}".format(
                    request.headers.get(u"X-Forwarded-For", u"")
                ),
                u"user_agent={!r}".format(request.user_agent.string),
            ])

        return u" ".join(context)
    except Exception as e:
        return u"context_error={}".format(type(e).__name__)


def decode(encoded: str, **kwargs: Any) -> Optional[Mapping[str, Any]]:
    for plugin in _get_plugins():
        data = plugin.decode_api_token(encoded, **kwargs)
        if data:
            break
    else:
        try:
            data = jwt.decode(
                encoded,
                _get_secret(encode=False),
                algorithms=[_get_algorithm()],
                **kwargs
            )
        except jwt.InvalidTokenError as e:
            # TODO: add signal for performing extra work, like removing
            # expired tokens
            log.warning(
                u"Rejected invalid API token: reason=%s %s",
                e,
                _invalid_token_log_context(encoded),
            )
            data = None
    return data


def encode(data: dict[str, Any], **kwargs: Any) -> str:
    for plugin in _get_plugins():
        token = plugin.encode_api_token(data, **kwargs)
        if token:
            break
    else:
        token = jwt.encode(
            data,
            _get_secret(encode=True),
            algorithm=_get_algorithm(),
            **kwargs
        )

    return token


def add_extra(result: dict[str, Any]) -> dict[str, Any]:
    for plugin in _get_plugins():
        result = plugin.add_extra_fields(result)
    return result


def get_user_from_token(token: str,
                        update_access_time: bool = True
                        ) -> Optional[model.User]:
    data = decode(token)
    if not data:
        return None
    # do preprocessing in reverse order, allowing onion-like "unwrapping" of
    # the data, added during postprocessing, when token was
    # created. `Interface._reverse_iteration_order` cannot be used here,
    # because all other methods of IApiToken should be executed in a normal
    # order and only `IApiToken.preprocess_api_token` must be different.
    for plugin in reversed(list(_get_plugins())):
        data = plugin.preprocess_api_token(data)
    if not data or u"jti" not in data:
        return None
    token_obj = model.ApiToken.get(data[u"jti"])
    if not token_obj:
        return None
    if update_access_time:
        token_obj.touch(True)
    return token_obj.owner
