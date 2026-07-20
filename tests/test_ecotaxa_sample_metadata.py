import pytest


def test_complete_metadata_builds_datetime_time_and_depth_envelopes():
    from core.ecotaxa_browser.sample_metadata import (
        accumulate_metadata_row,
        finalize_metadata,
        new_metadata_aggregate,
    )

    aggregate = new_metadata_aggregate()
    accumulate_metadata_row(aggregate, ["2015-05-22", "14:03:58", 1.8, 2.0])
    accumulate_metadata_row(aggregate, ["2015-05-22", "14:08:01", 3.3, 352.6])

    assert finalize_metadata(
        aggregate, authoritative_total=2, query_total=2
    ) == {
        "date_min": "2015-05-22",
        "date_max": "2015-05-22",
        "time_min": "14:03:58",
        "time_max": "14:08:01",
        "datetime_min": "2015-05-22T14:03:58",
        "datetime_max": "2015-05-22T14:08:01",
        "depth_min": 1.8,
        "depth_max": 352.6,
        "temporal_precision": "datetime",
        "missing_date_count": 0,
        "missing_time_count": 0,
        "missing_depth_min_count": 0,
        "missing_depth_max_count": 0,
        "metadata_objects_scanned": 2,
        "metadata_complete": True,
        "metadata_coverage_pct": 100.0,
        "depth_complete": True,
        "query_total_objects": 2,
        "count_discrepancy": False,
    }


def test_missing_time_keeps_date_precision_without_inventing_datetime():
    from core.ecotaxa_browser.sample_metadata import (
        accumulate_metadata_row,
        finalize_metadata,
        new_metadata_aggregate,
    )

    aggregate = new_metadata_aggregate()
    accumulate_metadata_row(aggregate, ["2015-05-22", None, 1.8, 2.0])

    result = finalize_metadata(aggregate, authoritative_total=1)

    assert result["date_min"] == "2015-05-22"
    assert result["datetime_min"] is None
    assert result["datetime_max"] is None
    assert result["temporal_precision"] == "date"
    assert result["missing_time_count"] == 1


def test_missing_date_makes_temporal_envelope_partial():
    from core.ecotaxa_browser.sample_metadata import (
        accumulate_metadata_row,
        finalize_metadata,
        new_metadata_aggregate,
    )

    aggregate = new_metadata_aggregate()
    accumulate_metadata_row(aggregate, ["2015-05-22", "14:03:58", 1.8, 2.0])
    accumulate_metadata_row(aggregate, [None, "14:04:00", 2.1, None])

    result = finalize_metadata(aggregate, authoritative_total=2)

    assert result["temporal_precision"] == "partial"
    assert result["missing_date_count"] == 1
    assert result["missing_depth_max_count"] == 1
    assert result["depth_complete"] is False


def test_unknown_authoritative_total_keeps_completeness_unknown():
    from core.ecotaxa_browser.sample_metadata import (
        accumulate_metadata_row,
        finalize_metadata,
        new_metadata_aggregate,
    )

    aggregate = new_metadata_aggregate()
    accumulate_metadata_row(aggregate, ["2015-05-22", "14:03:58", 1.8, 2.0])
    result = finalize_metadata(aggregate, authoritative_total=None)

    assert result["metadata_complete"] is None
    assert result["metadata_coverage_pct"] is None
    assert result["depth_complete"] is None


def test_empty_authoritative_sample_is_complete_without_envelope():
    from core.ecotaxa_browser.sample_metadata import (
        finalize_metadata,
        new_metadata_aggregate,
    )

    result = finalize_metadata(
        new_metadata_aggregate(), authoritative_total=0, query_total=0
    )

    assert result["metadata_complete"] is True
    assert result["metadata_coverage_pct"] == 100.0
    assert result["temporal_precision"] == "none"
    assert result["date_min"] is None
    assert result["depth_min"] is None


def test_sample_stats_are_the_only_authoritative_count_source():
    from core.ecotaxa_browser.sample_metadata import normalize_sample_stats

    result = normalize_sample_stats({
        "sample_id": 42,
        "nb_validated": 3,
        "nb_predicted": 4,
        "nb_dubious": 2,
        "nb_unclassified": 1,
        "used_taxa": [25828],
    })

    assert result == {
        "sample_id": 42,
        "nb_validated": 3,
        "nb_predicted": 4,
        "nb_dubious": 2,
        "nb_unclassified": 1,
        "object_count": 10,
        "used_taxa": [25828],
    }
