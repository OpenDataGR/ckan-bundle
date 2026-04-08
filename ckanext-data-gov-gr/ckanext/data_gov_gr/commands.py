from __future__ import annotations

import json
import logging
from datetime import datetime

from ckan.model.system_info import set_system_info

from ckanext.data_gov_gr import helpers

log = logging.getLogger(__name__)


def refresh_home_dataset_resources_snapshot() -> dict[str, object]:
    """
    Υπολογίζει και αποθηκεύει το snapshot του πλήθους των πόρων για την αρχική σελίδα.
    """
    count = helpers.count_home_dataset_resources()
    computed_at = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    payload = {
        'count': count,
        'computed_at': computed_at,
    }
    set_system_info(
        helpers.HOME_DATASET_RESOURCES_SNAPSHOT_KEY,
        json.dumps(payload, ensure_ascii=False),
    )
    log.info(
        'Stored homepage dataset resources snapshot: count=%s computed_at=%s',
        count,
        computed_at,
    )
    return payload
