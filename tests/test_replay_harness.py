"""Contrats TDD du harness de replay — étape 0."""

from __future__ import annotations

import json
import os

import pytest
from langchain_core.messages import ToolMessage


def test_reference_scenarios_are_fixed_and_complete():
    from evals.replay_harness import load_reference_scenarios

    scenarios = load_reference_scenarios()

    assert set(scenarios) == {"SC-LAB", "SC-ENRICH", "SC-ECOTAXA"}
    assert len(scenarios["SC-LAB"].turns) == 7
    assert len(scenarios["SC-ECOTAXA"].turns) == 3
    assert "ecotaxa" not in scenarios["SC-ECOTAXA"].turns[-1].prompt.lower()
    assert all(turn.name and turn.prompt for scenario in scenarios.values() for turn in scenario.turns)


def test_offline_replay_is_identical_after_normalization():
    from evals.replay_harness import build_offline_report, normalize_report

    first = normalize_report(build_offline_report(runs=2))
    second = normalize_report(build_offline_report(runs=2))

    assert first == second
    assert first["lane"] == "offline"
    assert first["run_count_per_scenario"] == 2


def test_report_computes_file_routing_and_tool_density():
    from evals.replay_harness import build_offline_report

    report = build_offline_report(runs=1)
    metrics = report["metrics"]

    assert 0.0 <= metrics["sc_lab_good_file_rate"] <= 1.0
    assert metrics["mean_tools_per_turn"] >= 0.0
    assert metrics["mean_tools_exposed_per_turn"] > 0.0
    assert metrics["fixed_tokens"] > 0


def test_offline_replay_records_dynamic_tool_policy_under_the_per_call_cap():
    from evals.replay_harness import build_offline_report

    report = build_offline_report(runs=1)
    turns = [
        turn
        for scenario in report["scenarios"]
        for turn in scenario["turns"]
    ]

    assert turns
    assert all(len(turn["tools_exposed"]) <= 15 for turn in turns)
    assert all(turn["context"]["tool_exposure_count"] <= 15 for turn in turns)
    assert all("tool_exposure_alert" in turn["context"] for turn in turns)
    assert all("tool_exposure_groups" in turn["context"] for turn in turns)
    assert all("policy_overflow" in turn["context"] for turn in turns)
    assert all(
        turn["context"]["approx_tokens_tool_schemas_after"]
        <= turn["context"]["approx_tokens_tool_schemas_before"]
        for turn in turns
    )


def test_tool_exposure_capture_preserves_each_model_call():
    from evals.replay_harness import ToolExposureCapture

    capture = ToolExposureCapture()
    capture.on_chat_model_start(
        {},
        [[]],
        invocation_params={
            "tools": [{"type": "function", "function": {"name": "load_file"}}]
        },
    )
    capture.on_chat_model_start(
        {},
        [[]],
        invocation_params={
            "tools": [
                {"type": "function", "function": {"name": "run_pandas"}},
                {"type": "function", "function": {"name": "run_graph"}},
            ]
        },
    )

    assert capture.calls == [["load_file"], ["run_pandas", "run_graph"]]
    assert capture.names == ["load_file", "run_pandas", "run_graph"]


def test_level_1_and_2_graders_flag_forbidden_tool_and_wrong_source():
    from evals.replay_harness import grade_turn

    grade = grade_turn(
        expected_source="file",
        forbidden_tools=("query_ecotaxa",),
        tool_calls=[{"name": "query_ecotaxa", "arguments": {"project_id": 17498}}],
        dataset_after={"source": "ecotaxa", "variable_name": "ecotaxa_df"},
    )

    assert grade["level_1_passed"] is False
    assert grade["level_2_passed"] is False
    assert "query_ecotaxa" in grade["forbidden_tools_called"]
    assert grade["source_matches"] is False


def test_grader_normalizes_file_paths_and_distinguishes_required_dataset():
    from evals.replay_harness import grade_turn

    loaded = grade_turn(
        expected_source="file",
        forbidden_tools=(),
        tool_calls=[{"name": "load_file", "arguments": {}}],
        dataset_after={"source": "file:data/demo/table.tsv"},
    )
    availability_only = grade_turn(
        expected_source="amundsen",
        expected_dataset_source_family="amundsen",
        forbidden_tools=(),
        tool_calls=[{"name": "find_amundsen_data_for_table", "arguments": {}}],
        dataset_after={"source": "file:tests/fixtures/d07_amundsen_schema.tsv"},
    )

    assert loaded["level_2_passed"] is True
    assert availability_only["source_matches"] is True
    assert availability_only["dataset_matches"] is False
    assert availability_only["level_2_passed"] is False


def test_isolated_environment_disables_tracing_and_restores_process_env(tmp_path, monkeypatch):
    from evals.replay_harness import isolated_replay_environment

    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("SESSION_STORE_DIR", "/tmp/production-store-sentinel")

    with isolated_replay_environment(tmp_path) as isolation:
        assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
        assert os.environ["LANGCHAIN_API_KEY"] == ""
        assert os.environ["SESSION_STORE_DATABASE_URL"] == ""
        assert os.environ["SESSION_STORE_DIR"] == str(isolation.session_store_dir)
        assert isolation.session_store_dir.is_relative_to(tmp_path)

    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["SESSION_STORE_DIR"] == "/tmp/production-store-sentinel"


@pytest.mark.parametrize("runs", [0, 1, 4])
def test_live_lane_requires_at_least_five_runs(runs):
    from evals.replay_harness import validate_run_count

    with pytest.raises(ValueError, match="au moins 5"):
        validate_run_count("live", runs)


def test_report_serialization_contains_no_environment_secrets(monkeypatch):
    from evals.replay_harness import build_offline_report, serialize_report

    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-test-value")
    rendered = serialize_report(build_offline_report(runs=1))
    parsed = json.loads(rendered)

    assert "super-secret-test-value" not in rendered
    assert parsed["schema_version"] == "1.0"
    assert parsed["rubric"]["level_3"]["automated"] is False


def test_live_report_uses_injected_executor_and_keeps_five_runs():
    from evals.replay_harness import build_live_report, load_reference_scenarios

    class FakeExecutor:
        model = "fake-live-model"
        external_dependencies = ["fake-model"]

        def start_run(self, scenario, run_index):
            return {"scenario": scenario.id, "run_index": run_index}

        def run_turn(self, run_context, turn):
            observation = dict(turn.offline)
            observation["tools_exposed"] = ["load_file", "run_pandas"]
            observation["tool_exposure_calls"] = [
                ["load_file"],
                ["load_file", "run_pandas"],
            ]
            observation["usage"] = {"input_tokens": 10, "output_tokens": 2, "cost_usd": 0.001}
            observation["context"] = {"fixed_tokens": 123}
            return observation

    report = build_live_report(
        runs=5,
        executor=FakeExecutor(),
        scenarios=load_reference_scenarios(),
    )

    assert report["lane"] == "live"
    assert report["run_count_per_scenario"] == 5
    assert len(report["scenarios"]) == 15
    assert report["model"] == "fake-live-model"
    assert report["metrics"]["input_tokens"] == 650
    assert report["metrics"]["output_tokens"] == 130
    assert report["metrics"]["cost_usd"] == pytest.approx(0.065)
    assert report["metrics"]["max_tools_exposed_per_model_call"] == 2


def test_tool_schema_capture_reads_openai_function_specs():
    from evals.replay_harness import ToolExposureCapture

    capture = ToolExposureCapture()
    capture.on_chat_model_start(
        {},
        [[]],
        invocation_params={
            "tools": [
                {"type": "function", "function": {"name": "load_file"}},
                {"type": "function", "function": {"name": "run_pandas"}},
            ]
        },
    )

    assert capture.names == ["load_file", "run_pandas"]


def test_live_report_checkpoints_each_run_and_resumes_without_duplicates(tmp_path):
    from evals.replay_harness import build_live_report, load_reference_scenarios

    checkpoint = tmp_path / "live.json"
    scenarios = load_reference_scenarios()

    class InterruptingExecutor:
        model = "fake-live-model"
        external_dependencies = ["fake-model"]

        def __init__(self, fail_after=None):
            self.fail_after = fail_after
            self.started = 0

        def start_run(self, scenario, run_index):
            if self.fail_after is not None and self.started >= self.fail_after:
                raise KeyboardInterrupt
            self.started += 1
            return {}

        def run_turn(self, run_context, turn):
            return {
                **turn.offline,
                "tools_exposed": ["load_file"],
                "usage": {},
                "context": {"fixed_tokens": 1},
            }

    first = InterruptingExecutor(fail_after=1)
    with pytest.raises(KeyboardInterrupt):
        build_live_report(
            runs=5,
            executor=first,
            scenarios=scenarios,
            checkpoint_path=checkpoint,
        )

    partial = json.loads(checkpoint.read_text())
    assert partial["status"] == "in_progress"
    assert partial["completed_scenario_runs"] == 1
    assert len(partial["scenarios"]) == 1

    resumed = InterruptingExecutor()
    report = build_live_report(
        runs=5,
        executor=resumed,
        scenarios=scenarios,
        checkpoint_path=checkpoint,
    )

    assert report["status"] == "complete"
    assert report["completed_scenario_runs"] == 15
    assert len({(run["scenario_id"], run["run_index"]) for run in report["scenarios"]}) == 15
    assert resumed.started == 14


def test_regrade_report_recomputes_saved_grades_without_model_calls():
    from evals.replay_harness import regrade_report

    report = {
        "scenarios": [{
            "scenario_id": "SC-LAB",
            "run_index": 0,
            "turns": [{
                "name": "upload",
                "tool_calls": [{"name": "load_file", "arguments": {}}],
                "dataset_after": {"source": "file:data/demo/neolabs_taxonomy_2014_2020.tsv"},
                "grade": {"level_2_passed": False},
            }],
        }],
    }

    updated = regrade_report(report)

    assert updated["scenarios"][0]["turns"][0]["grade"]["level_2_passed"] is True
    assert updated["metrics"]["turns"] == 1


def test_replay_status_comes_from_artifact_not_french_content():
    from evals.replay_harness import structured_tool_observation
    from tools.tool_result import success

    _, artifact = success("Résultat valide malgré le mot Erreur dans cette phrase.")
    message = ToolMessage(
        content="Erreur affichée dans un libellé métier, pas un échec.",
        artifact=artifact,
        tool_call_id="call-success",
    )

    observation = structured_tool_observation(message)
    assert observation["status"] == "success"
    assert observation["result"]["summary"].startswith("Résultat valide")


def test_replay_rejects_missing_structured_tool_artifact():
    from evals.replay_harness import structured_tool_observation

    message = ToolMessage(content="ancien retour texte", tool_call_id="legacy")
    with pytest.raises(ValueError, match="structured ToolResult"):
        structured_tool_observation(message)


def test_offline_calls_share_the_structured_result_schema():
    from evals.replay_harness import build_offline_report
    from tools.tool_result import validate_tool_artifact

    report = build_offline_report(runs=1)
    calls = [
        call
        for scenario in report["scenarios"]
        for turn in scenario["turns"]
        for call in turn["tool_calls"]
    ]

    assert calls
    assert all(validate_tool_artifact(call["result"]) for call in calls)
    assert all(call["status"] == call["result"]["status"] for call in calls)
