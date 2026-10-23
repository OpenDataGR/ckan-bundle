from ckanext.scheming.plugins import expand_form_composite


def test_expand_form_composite_scopes_indexes_to_each_repeating_field():
    """An index gap in one repeating field must not corrupt another field."""
    data = {
        "creator-0-name": "Creator 1",
        "creator-1-name": "Creator 2",
        # Simulate removing creator index 2 and adding another creator. The
        # browser keeps the removed group wrapper, so the new index is 3.
        "creator-3-name": "Creator 4",
        "temporal_coverage-0-start": "2020-01-01",
        "temporal_coverage-0-end": "2020-12-31",
        "temporal_coverage-1-start": "2021-01-01",
        "temporal_coverage-1-end": "2021-12-31",
        "temporal_coverage-2-start": "2022-01-01",
        "temporal_coverage-2-end": "2022-12-31",
    }

    expand_form_composite(data, {"creator", "temporal_coverage"})

    assert data == {
        "creator": [
            {"name": "Creator 1"},
            {"name": "Creator 2"},
            {"name": "Creator 4"},
        ],
        "temporal_coverage": [
            {"start": "2020-01-01", "end": "2020-12-31"},
            {"start": "2021-01-01", "end": "2021-12-31"},
            {"start": "2022-01-01", "end": "2022-12-31"},
        ],
    }


def test_expand_form_composite_preserves_numeric_repeating_field_order():
    """Double-digit indexes must not be ordered lexicographically."""
    data = {
        "creator-{}-name".format(index): "Creator {}".format(index)
        for index in range(20)
    }

    expand_form_composite(data, {"creator"})

    assert data == {
        "creator": [
            {"name": "Creator {}".format(index)}
            for index in range(20)
        ]
    }
