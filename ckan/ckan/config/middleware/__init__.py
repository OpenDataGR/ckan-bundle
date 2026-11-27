# encoding: utf-8

"""WSGI app initialization"""
from __future__ import annotations

import logging
from typing import Optional, Union

from flask.ctx import RequestContext

from ckan.config.environment import load_environment
from ckan.config.middleware.flask_app import (
    make_flask_stack, AUTO_URL_FOR_CONTEXT)
from ckan.common import CKANConfig
from ckan.types import CKANApp, Config


log = logging.getLogger(__name__)

# This is a test Flask request context to be used internally.
# Do not use it!
_internal_test_request_context: Optional[RequestContext] = None


def make_app(conf: Union[Config, CKANConfig]) -> CKANApp:
    '''
    Initialise the Flask app and wrap it in dispatcher middleware.
    '''

    load_environment(conf)

    flask_app = make_flask_stack(conf)

    # Set this internal test request context with the configured environment so
    # it can be used when calling url_for from tests
    # Σημαδεμένο, ώστε το teardown να μη σβήνει το session του κώδικα που
    # κάλεσε το url_for (workers, CLI)
    global _internal_test_request_context
    _internal_test_request_context = flask_app._wsgi_app.test_request_context(
        environ_overrides={AUTO_URL_FOR_CONTEXT: True})

    return flask_app
