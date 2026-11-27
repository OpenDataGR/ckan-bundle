# -*- coding: utf-8 -*-
'''
Tests για τη χρήση του archiver status από το MQA (OD-856).

Το MQA χρησιμοποιεί το αποτέλεσμα του archiver μόνο για το canonical
resource.url. Σε προσωρινή αποτυχία του check_only (status 24) δεν γίνεται
κλήση στο δίκτυο: ο σύνδεσμος θεωρείται προσβάσιμος αν έχει λειτουργήσει
έστω μία φορά (last_success).
'''
import datetime
from types import SimpleNamespace

import pytest

from ckanext.archiver.model import Archival, Status
from ckanext.data_gov_gr.logic import mqa_access_url_cache
from ckanext.data_gov_gr.logic import mqa_calculator
from ckanext.data_gov_gr.logic.mqa_calculator import MQACalculator

RESOURCE_URL = 'https://example.test/data/file.csv'


class _Response(object):
    elapsed = None

    def __init__(self, status_code):
        self.status_code = status_code


@pytest.fixture
def direct_checks(monkeypatch):
    '''Καταγράφει τους direct HEAD ελέγχους, που απαντούν πάντα 200.'''
    calls = []
    monkeypatch.setattr(mqa_access_url_cache, 'is_async_enabled', lambda: False)
    monkeypatch.setattr(
        mqa_calculator.requests, 'head',
        lambda url, **kwargs: calls.append(url) or _Response(200))
    return calls


def _calculator_with_archival(monkeypatch, status_text, resource=None, last_success=None):
    archival = SimpleNamespace(
        status_id=Status.by_text(status_text),
        status=status_text,
        reason='reason for %s' % status_text,
        last_success=last_success,
    )
    monkeypatch.setattr(Archival, 'get_for_resource',
                        classmethod(lambda cls, resource_id: archival))
    calculator = MQACalculator(check_urls=True)
    calculator._resources = [resource or {'id': 'res-1', 'url': RESOURCE_URL}]
    return calculator


def test_check_only_success_is_accessible(monkeypatch, direct_checks):
    calculator = _calculator_with_archival(monkeypatch, 'URL checked successfully')
    assert calculator._check_url_accessibility(RESOURCE_URL) is True
    assert direct_checks == []


def test_legacy_archive_success_is_accessible(monkeypatch, direct_checks):
    calculator = _calculator_with_archival(monkeypatch, 'Archived successfully')
    assert calculator._check_url_accessibility(RESOURCE_URL) is True
    assert direct_checks == []


def test_broken_is_not_accessible(monkeypatch, direct_checks):
    calculator = _calculator_with_archival(monkeypatch, 'URL request failed')
    assert calculator._check_url_accessibility(RESOURCE_URL) is False
    assert direct_checks == []


def test_transient_failure_of_previously_working_url_is_accessible(monkeypatch, direct_checks):
    '''Προσωρινή αποτυχία σε σύνδεσμο που έχει λειτουργήσει: προσβάσιμος,
    χωρίς κλήση στο δίκτυο μέσα στο αίτημα.'''
    calculator = _calculator_with_archival(
        monkeypatch, 'URL check temporarily failed', last_success=datetime.datetime(2026, 11, 1))
    assert calculator._check_url_accessibility(RESOURCE_URL) is True
    assert direct_checks == []


def test_transient_failure_of_never_working_url_is_not_accessible(monkeypatch, direct_checks):
    calculator = _calculator_with_archival(monkeypatch, 'URL check temporarily failed')
    assert calculator._check_url_accessibility(RESOURCE_URL) is False
    assert direct_checks == []


def test_explicit_access_and_download_urls_do_not_inherit_status(monkeypatch, direct_checks):
    resource = {'id': 'res-1', 'url': RESOURCE_URL,
                'access_url': 'https://example.test/page',
                'download_url': 'https://example.test/download.csv'}
    calculator = _calculator_with_archival(monkeypatch, 'URL request failed', resource)

    assert calculator._check_url_accessibility(
        'https://example.test/page', url_role='access_url') is True
    assert calculator._check_url_accessibility(
        'https://example.test/download.csv', url_role='download_url') is True
    assert direct_checks == ['https://example.test/page',
                             'https://example.test/download.csv']


def test_older_archiver_without_transient_status(monkeypatch):
    class OldStatus(object):
        @classmethod
        def by_text(cls, text):
            raise KeyError(text)

    archival = SimpleNamespace(status_id=24)
    assert mqa_calculator._is_transient_url_check(archival, OldStatus) is False
