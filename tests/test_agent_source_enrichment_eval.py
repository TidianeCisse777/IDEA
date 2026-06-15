from scripts.evals.run_agent_source_enrichment_eval import (
    ToolCall,
    _evaluate_bio,
    _evaluate_ogsl,
)


def test_bio_evaluator_requires_per_station_tool_and_derived_table():
    calls = [
        ToolCall("load", "load_file", {"path": "stations.csv"}),
        ToolCall("enrichment", "run_pandas", {"code": "result = df"}),
        ToolCall(
            "enrichment",
            "couple_zooplankton_bio_oracle",
            {
                "rows_json": (
                    '[{"station":"A","latitude":48.7,"longitude":-68.5,'
                    '"sample_date":"2024-06-01","abundance":120}]'
                )
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
                "rows_json": (
                    '[{"station":"station_1","latitude":0,"longitude":0}]'
                )
            },
        ),
    ]
    datasets = [{
        "source": "bio_oracle_coupling",
        "rows": 1,
        "columns": ["station", "latitude", "longitude"],
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

    result = _evaluate_ogsl(calls, datasets=[])

    assert result["passed"] is False
    assert result["missing_capability"] is True
