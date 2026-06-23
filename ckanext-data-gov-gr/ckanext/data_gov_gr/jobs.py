# -*- coding: utf-8 -*-
"""Background jobs for ckanext-data-gov-gr."""

import logging
from typing import Dict, Any

from ckanext.data_gov_gr.logic import mqa_access_url_cache

log = logging.getLogger(__name__)


def check_mqa_access_url(url: str) -> Dict[str, Any]:
    """Run the slower asynchronous MQA access_url verification."""
    result = mqa_access_url_cache.check_access_url_async(url)
    log.info(
        'MQA access_url check finished for %s: accessible=%s status=%s error=%s',
        url,
        result.get('accessible'),
        result.get('status_code'),
        result.get('error'),
    )
    return result
