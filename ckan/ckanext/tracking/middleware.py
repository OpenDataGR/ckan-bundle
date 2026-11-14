import hashlib
import logging

import ckan.model as model
from ckan.common import request

from ckanext.tracking.model import TrackingRaw


logger = logging.getLogger(__name__)
ALLOWED_TRACKING_TYPES = frozenset(("page", "resource"))


def track_request() -> tuple[str, int]:
    """Validate and store a tracking event inside the request lifecycle."""
    url = request.form.get("url")
    tracking_type = request.form.get("type")

    # An empty URL represents the home page and is valid. Tracking types are
    # an enum in practice even though the database column is a varchar.
    if url is None or tracking_type not in ALLOWED_TRACKING_TYPES:
        return "", 400

    # We want a unique anonymized key for each user so that we do not count
    # multiple clicks from the same user. Missing headers must not turn a
    # best-effort tracking request into a server error.
    key = "".join([
        request.environ.get("HTTP_USER_AGENT", ""),
        request.environ.get("REMOTE_ADDR", ""),
        request.environ.get("HTTP_ACCEPT_LANGUAGE", ""),
        request.environ.get("HTTP_ACCEPT_ENCODING", ""),
    ])
    h = hashlib.new("md5", usedforsecurity=False)
    h.update(key.encode())
    user_key = h.hexdigest()

    try:
        logger.debug("Tracking %s for %s", tracking_type, url)
        TrackingRaw.create(
            user_key=user_key,
            url=url,
            tracking_type=tracking_type,
        )
    except Exception:
        # TrackingRaw.create() commits, so a failed flush leaves the scoped
        # session unusable until it is explicitly rolled back. Always recover
        # it before this worker handles another request.
        model.Session.rollback()
        logger.exception("Error tracking request")

    # Tracking is best-effort and must not affect the page being measured.
    return "", 204
