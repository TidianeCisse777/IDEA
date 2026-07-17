"""Reference contract for the EcoTaxa exploration scenario matrix."""

import json
from pathlib import Path


MATRIX = Path("evals/scenarios/ecotaxa_exploration_matrix.json")


def test_exploration_matrix_has_expected_and_gap_scenarios():
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    scenarios = payload["scenarios"]

    assert len(scenarios) >= 10
    assert {scenario["status"] for scenario in scenarios} == {"expected", "gap"}
    assert sum(scenario["status"] == "expected" for scenario in scenarios) >= 6
    assert sum(scenario["status"] == "gap" for scenario in scenarios) >= 3


def test_exploration_matrix_ids_and_contracts_are_unique_and_complete():
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    scenarios = payload["scenarios"]
    ids = [scenario["id"] for scenario in scenarios]

    assert len(ids) == len(set(ids))
    for scenario in scenarios:
        assert scenario["prompt"]
        assert scenario["expected_sequence"]
        assert isinstance(scenario["required_args"], dict)
        assert isinstance(scenario["forbidden_tools"], list)
        assert scenario["checks"]
        if scenario["status"] == "gap":
            assert scenario.get("gap")


def test_priority_exploration_scenarios_protect_read_only_behavior():
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    priority = [
        scenario for scenario in payload["scenarios"]
        if scenario["id"] in {
            "EXP-01-zone-samples",
            "EXP-02-zone-time-samples",
            "EXP-03-zones-covered",
            "EXP-04-regional-ranking",
            "EXP-05-interannual-coverage",
            "EXP-06-taxon-zone",
        }
    ]

    assert len(priority) == 6
    assert all(
        forbidden in scenario["forbidden_tools"]
        for scenario in priority
        for forbidden in ("query_ecotaxa", "export_ecotaxa_samples")
    )
