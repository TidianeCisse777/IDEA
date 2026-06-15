"""Tests for the OGSL LangSmith trajectory evaluators."""

from scripts.evals.run_ogsl_langsmith_eval import (
    ogsl_dataset_created,
    ogsl_query_integrity,
    source_file_preserved,
    trajectory_subsequence,
)


def test_ogsl_langsmith_evaluators_accept_expected_run():
    outputs = {
        "trajectory": [
            "load_file",
            "query_ogsl",
        ],
        "tool_calls": [{
            "name": "query_ogsl",
            "arguments": {
                "station_column": "station",
                "time_column": "sample_date",
                "variables": ["PRES", "TE90"],
            },
        }],
        "datasets": [
            {"source": "ogsl", "rows": 192, "columns": ["stationID", "time"]},
            {
                "source": "ogsl_enrichment",
                "rows": 1,
                "columns": [
                    "station",
                    "sample_date",
                    "ogsl_match_status",
                    "ogsl_time_delta_min",
                ],
            },
        ],
        "raw_file_unchanged": True,
    }
    reference = {
        "expected_trajectory": [
            "load_file",
            "query_ogsl",
        ],
        "expected_station_column": "station",
        "expected_time_column": "sample_date",
        "expected_source": "ogsl",
        "expected_derived_source": "ogsl_enrichment",
        "expected_rows": 1,
    }

    assert trajectory_subsequence(outputs, reference)["score"] == 1
    assert ogsl_query_integrity(outputs, reference)["score"] == 1
    assert ogsl_dataset_created(outputs, reference)["score"] == 1
    assert source_file_preserved(outputs)["score"] == 1


def test_ogsl_langsmith_evaluators_reject_transcribed_stations():
    outputs = {
        "trajectory": ["load_file", "query_ogsl"],
        "tool_calls": [{
            "name": "query_ogsl",
            "arguments": {
                "station_column": "station",
                "stations": ["02M"],
            },
        }],
        "datasets": [],
        "raw_file_unchanged": False,
    }
    reference = {
        "expected_trajectory": [
            "load_file",
            "query_ogsl",
        ],
        "expected_station_column": "station",
        "expected_time_column": "sample_date",
        "expected_source": "ogsl",
        "expected_derived_source": "ogsl_enrichment",
        "expected_rows": 1,
    }

    assert trajectory_subsequence(outputs, reference)["score"] == 1
    assert ogsl_query_integrity(outputs, reference)["score"] == 0
    assert ogsl_dataset_created(outputs, reference)["score"] == 0
    assert source_file_preserved(outputs)["score"] == 0
