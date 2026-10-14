import datetime
from types import SimpleNamespace

import pytest

from ckanext.qa.model import aggregate_qa_for_a_dataset


def _qa(
        openness_score=None,
        openness_score_reason=None,
        updated=None,
        mqa_score=None,
        mqa_findability_score=None,
        mqa_accessibility_score=None,
        mqa_interoperability_score=None,
        mqa_reusability_score=None,
        mqa_contextuality_score=None):
    return SimpleNamespace(
        openness_score=openness_score,
        openness_score_reason=openness_score_reason,
        updated=updated,
        mqa_score=mqa_score,
        mqa_findability_score=mqa_findability_score,
        mqa_accessibility_score=mqa_accessibility_score,
        mqa_interoperability_score=mqa_interoperability_score,
        mqa_reusability_score=mqa_reusability_score,
        mqa_contextuality_score=mqa_contextuality_score,
    )


@pytest.mark.parametrize(
    'qa_objs',
    [
        [_qa(openness_score=2), _qa(openness_score=None)],
        [_qa(openness_score=None), _qa(openness_score=2)],
    ],
)
def test_aggregate_openness_score_ignores_none_regardless_of_order(qa_objs):
    result = aggregate_qa_for_a_dataset(qa_objs)

    assert result['openness_score'] == 2


def test_aggregate_keeps_reason_for_highest_numeric_openness_score():
    qa_objs = [
        _qa(openness_score=1, openness_score_reason='score one'),
        _qa(openness_score=3, openness_score_reason='score three'),
        _qa(openness_score=None, openness_score_reason='not scored'),
        _qa(openness_score=2, openness_score_reason='score two'),
    ]

    result = aggregate_qa_for_a_dataset(qa_objs)

    assert result['openness_score'] == 3
    assert result['openness_score_reason'] == 'score three'


def test_aggregate_leaves_openness_score_empty_when_all_scores_are_none():
    qa_objs = [
        _qa(openness_score=None, openness_score_reason='not scored'),
        _qa(openness_score=None),
    ]

    result = aggregate_qa_for_a_dataset(qa_objs)

    assert result['openness_score'] is None
    assert result['openness_score_reason'] is None


def test_aggregate_ignores_none_updated_value_after_timestamp():
    timestamp = datetime.datetime(2026, 10, 13, 9, 26, 10)
    qa_objs = [
        _qa(openness_score=2, updated=timestamp),
        _qa(openness_score=None, updated=None),
    ]

    result = aggregate_qa_for_a_dataset(qa_objs)

    assert result['updated'] == timestamp.isoformat()


def test_aggregate_combines_numeric_openness_with_mqa_only_record():
    openness_updated = datetime.datetime(2026, 10, 13, 9, 26, 10)
    mqa_updated = datetime.datetime(2026, 10, 13, 9, 26, 9)
    qa_objs = [
        _qa(
            openness_score=2,
            openness_score_reason='XLSX receives score 2',
            updated=openness_updated,
        ),
        _qa(
            openness_score=None,
            updated=mqa_updated,
            mqa_score=92,
            mqa_findability_score=90,
            mqa_accessibility_score=94,
            mqa_interoperability_score=91,
            mqa_reusability_score=93,
            mqa_contextuality_score=92,
        ),
    ]

    result = aggregate_qa_for_a_dataset(qa_objs)

    assert result == {
        'openness_score': 2,
        'openness_score_reason': 'XLSX receives score 2',
        'mqa_score': 92,
        'mqa_findability_score': 90,
        'mqa_accessibility_score': 94,
        'mqa_interoperability_score': 91,
        'mqa_reusability_score': 93,
        'mqa_contextuality_score': 92,
        'updated': openness_updated.isoformat(),
    }
