import logging
from types import SimpleNamespace

from ckanext.spatial.harvesters import csw
from ckanext.spatial.harvesters.csw import CSWHarvester


class _HarvestObjectField:
    def __eq__(self, _other):
        return self

    def isnot(self, _other):
        return self


class _HarvestObjectModel:
    harvest_job_id = _HarvestObjectField()
    fetch_finished = _HarvestObjectField()


def _patch_fetch_progress_counts(monkeypatch, counts):
    count_iter = iter(counts)

    class Query:
        def __init__(self, count):
            self._count = count

        def filter(self, *_args):
            return self

        def count(self):
            return self._count

    def query(_model):
        return Query(next(count_iter))

    monkeypatch.setattr(csw, 'HarvestObject', _HarvestObjectModel)
    monkeypatch.setattr(
        csw.model,
        'Session',
        SimpleNamespace(query=query),
    )


def test_log_fetch_progress_logs_current_object_position(monkeypatch, caplog):
    _patch_fetch_progress_counts(monkeypatch, [46, 16])
    harvester = CSWHarvester()
    harvester._job_total_cache = {}
    harvest_object = SimpleNamespace(
        harvest_job_id='job-1',
        guid='2520136e-1b32-11ef-a4ef-00d861c828db',
        package_id=None,
    )

    with caplog.at_level(logging.INFO, logger=csw.__name__ + '.CSW.fetch'):
        progress = harvester._log_fetch_progress(harvest_object, status='new')

    assert progress == {'current': 17, 'total': 46, 'status': 'new'}
    assert (
        '[CSW] Processing 17/46: status=new '
        'guid=2520136e-1b32-11ef-a4ef-00d861c828db package_id=-'
    ) in caplog.text


def test_log_fetch_progress_caches_job_total(monkeypatch, caplog):
    _patch_fetch_progress_counts(monkeypatch, [46, 16, 17])
    harvester = CSWHarvester()
    harvester._job_total_cache = {}
    harvest_object = SimpleNamespace(
        harvest_job_id='job-cache',
        guid='dataset-guid',
        package_id='package-id',
    )

    with caplog.at_level(logging.INFO, logger=csw.__name__ + '.CSW.fetch'):
        first = harvester._log_fetch_progress(harvest_object, status='change')
        second = harvester._log_fetch_progress(harvest_object, status='change')

    assert first['current'] == 17
    assert second['current'] == 18
    assert second['total'] == 46


def test_log_fetch_completed_logs_position_and_size(caplog):
    harvester = CSWHarvester()
    harvest_object = SimpleNamespace(guid='dataset-guid')
    progress = {'current': 46, 'total': 46, 'status': 'new'}

    with caplog.at_level(logging.INFO, logger=csw.__name__ + '.CSW.fetch'):
        harvester._log_fetch_completed(harvest_object, progress, byte_count=8421)

    assert '[CSW] Fetched 46/46: guid=dataset-guid bytes=8421' in caplog.text


def test_log_fetch_failed_logs_position_and_reason(caplog):
    harvester = CSWHarvester()
    harvest_object = SimpleNamespace(guid='dataset-guid')
    progress = {'current': 17, 'total': 46, 'status': 'new'}

    with caplog.at_level(logging.WARNING, logger=csw.__name__ + '.CSW.fetch'):
        harvester._log_fetch_failed(
            harvest_object,
            progress,
            reason='empty CSW record',
        )

    assert (
        '[CSW] Failed 17/46: guid=dataset-guid reason=empty CSW record'
    ) in caplog.text


def test_log_fetch_progress_failure_does_not_raise(monkeypatch, caplog):
    class BrokenSession:
        @staticmethod
        def query(_model):
            raise RuntimeError('database unavailable')

    monkeypatch.setattr(csw, 'HarvestObject', _HarvestObjectModel)
    monkeypatch.setattr(csw.model, 'Session', BrokenSession())
    harvester = CSWHarvester()
    harvester._job_total_cache = {}
    harvest_object = SimpleNamespace(
        harvest_job_id='job-error',
        guid='dataset-guid',
        package_id=None,
    )

    with caplog.at_level(logging.DEBUG, logger=csw.__name__ + '.CSW.fetch'):
        progress = harvester._log_fetch_progress(harvest_object, status='new')

    assert progress is None
    assert '[CSW] Could not log fetch progress' in caplog.text


def test_fetch_stage_logs_delete_object_before_return(monkeypatch):
    harvester = CSWHarvester()
    harvest_object = SimpleNamespace(guid='deleted-guid')
    calls = []

    monkeypatch.setattr(harvester, '_get_object_extra', lambda *_args: 'delete')
    monkeypatch.setattr(
        harvester,
        '_log_fetch_progress',
        lambda obj, status=None: calls.append((obj.guid, status)),
    )

    assert harvester.fetch_stage(harvest_object) is True
    assert calls == [('deleted-guid', 'delete')]
