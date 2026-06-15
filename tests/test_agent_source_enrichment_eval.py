from scripts.evals.run_agent_source_enrichment_eval import (
    ToolCall,
    _evaluate_bio,
    _evaluate_ogsl,
)


def test_bio_evaluator_requires_per_station_tool_and_derived_table():
    calls = [
        ToolCall("load", "load_file", {"path": "stations.csv"}),
        ToolCall(
            "enrichment",
            "couple_zooplankton_bio_oracle",
            {
                "latitude_column": "latitude",
                "longitude_column": "longitude",
                "variable": "temperature",
                "scenario": "baseline",
                "depth_layer": "surface",
            },
        ),
    ]
    datasets = [{
        "source": "bio_oracle_coupling",
        "rows": 1,
        "columns": [
            "station", "latitude", "longitude", "sample_date", "abundance",
            "temperature_baseline",
        ],
        "records": [{
            "station": "A",
            "latitude": 48.7,
            "longitude": -68.5,
            "sample_date": "2024-06-01",
            "abundance": 120,
            "temperature_baseline": 4.2,
        }],
    }]

    result = _evaluate_bio(
        calls,
        datasets,
        [{
            "station": "A",
            "latitude": 48.7,
            "longitude": -68.5,
            "sample_date": "2024-06-01",
            "abundance": 120,
        }],
    )

    assert result["passed"] is True


def test_bio_evaluator_rejects_fabricated_coordinates():
    calls = [
        ToolCall("load", "load_file", {"path": "stations.csv"}),
        ToolCall(
            "enrichment",
            "couple_zooplankton_bio_oracle",
            {
                "latitude_column": "latitude",
                "longitude_column": "longitude",
                "variable": "temperature",
                "scenario": "baseline",
                "depth_layer": "surface",
            },
        ),
    ]
    datasets = [{
        "source": "bio_oracle_coupling",
        "rows": 1,
        "columns": ["station", "latitude", "longitude"],
        "records": [{"station": "station_1", "latitude": 0, "longitude": 0}],
    }]

    result = _evaluate_bio(
        calls,
        datasets,
        [{"station": "IML4", "latitude": 48.7, "longitude": -68.5}],
    )

    assert result["passed"] is False
    assert result["checks"]["uses_source_coordinates"] is False
    assert result["checks"]["uses_source_station_ids"] is False


def test_ogsl_evaluator_reports_missing_agent_capability():
    calls = [
        ToolCall("load", "load_file", {"path": "stations.csv"}),
        ToolCall("enrichment", "load_skill", {"skill_name": "environmental_join"}),
        ToolCall("enrichment", "run_pandas", {"code": "result = df"}),
    ]

    result = _evaluate_ogsl(
        calls,
        datasets=[],
        input_records=[{
            "station": "02M",
            "sample_date": "2022-10-09T22:03:37Z",
        }],
    )

    assert result["passed"] is False
    assert result["missing_capability"] is True


def test_ogsl_evaluator_accepts_standard_tool_enrichment():
    calls = [
        ToolCall("load", "load_file", {"path": "stations.csv"}),
        ToolCall(
            "enrichment",
            "query_ogsl",
            {
                "station_column": "station",
                "time_column": "sample_date",
                "variables": ["PRES", "TE90"],
            },
        ),
    ]
    input_records = [{
        "station": "02M",
        "sample_date": "2022-10-09T22:03:37Z",
        "abundance": 120,
    }]
    datasets = [
        {
            "source": "ogsl",
            "rows": 10,
            "columns": ["stationID", "time", "PRES", "TE90"],
            "records": [],
        },
        {
            "source": "ogsl_enrichment",
            "rows": 1,
            "columns": [
                "station",
                "sample_date",
                "abundance",
                "ogsl_te90",
                "ogsl_time_delta_min",
                "ogsl_match_status",
            ],
            "records": [],
        },
    ]

    result = _evaluate_ogsl(calls, datasets, input_records)

    assert result["passed"] is True
