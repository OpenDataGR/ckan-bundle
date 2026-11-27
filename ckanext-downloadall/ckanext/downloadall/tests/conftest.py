# -*- coding: utf-8 -*-
'''Κοινά fixtures για τα tests του OD-857.

Τα tests τρέχουν χωρίς request context, όπως τα jobs στον worker, ώστε η
αποθήκευση του ZIP να ελέγχεται στις ίδιες συνθήκες. Χρειάζονται το CKAN με τη
διόρθωση του teardown: μετά το fffa2cc59 («Fix request teardown session
cleanup») το url_for έξω από request context ανοίγει/κλείνει το εσωτερικό
context του CKAN, και χωρίς τη διόρθωση το teardown σβήνει το database session
στη μέση της αποθήκευσης. with_request_context έχουν μόνο τα tests για τη
συμπεριφορά μέσα στο ίδιο αίτημα (request_cache).
'''
import re
from unittest import mock

import pytest
import responses

from ckanext.downloadall import tasks


class EnqueueCalls(list):
    '''Οι κλήσεις του toolkit.enqueue_job (args, queue, rq_kwargs).'''

    def package_ids(self):
        return [call['args'][0] for call in self]


@pytest.fixture
def enqueue_calls():
    '''Καταγράφει τα jobs αντί να τα στέλνει στη Redis.'''
    calls = EnqueueCalls()

    def _record(fn, args=None, kwargs=None, title=None, queue=None, rq_kwargs=None):
        calls.append({'fn': fn, 'args': list(args or []),
                      'kwargs': dict(kwargs or {}), 'queue': queue,
                      'rq_kwargs': rq_kwargs})

    with mock.patch('ckan.plugins.toolkit.enqueue_job', side_effect=_record):
        yield calls


@pytest.fixture
def clean_dedup_keys():
    '''Κλειδιά της Redis του DownloadAll για το site των tests, πριν και μετά
    το test: ένα test που διακόπηκε δεν αφήνει lock για το επόμενο.'''
    from ckan.common import config
    from ckanext.downloadall import dedup
    pattern = 'ckan:%s:downloadall:*' % config.get('ckan.site_id', 'default')

    def clean():
        conn = dedup._connect()
        for key in conn.scan_iter(match=pattern):
            conn.delete(key)
    clean()
    yield
    clean()


@pytest.fixture
def http():
    '''Ψεύτικες απαντήσεις HTTP για τους πόρους· χωρίς πραγματικό δίκτυο.'''
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps, \
            mock.patch.object(tasks, 'RETRY_DELAY_SECONDS', 0):
        # Solr και λοιπές τοπικές υπηρεσίες των tests περνούν κανονικά
        rsps.add_passthru(re.compile(r'https?://(127\.0\.0\.1|localhost)(:\d+)?/'))
        yield rsps
