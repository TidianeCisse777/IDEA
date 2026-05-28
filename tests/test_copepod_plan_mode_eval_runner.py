import json

import pytest

from core.config import settings
from scripts.evals.run_copepod_plan_mode_eval import (
    _compact_tool_result,
    _live_eval_runtime_context,
    _live_eval_system_prompt,
    main,
    run_live_du_only_eval,
    run_live_eval,
    run_mock_eval,
)

@pytest.mark.workflow
def test_mock_eval_runner_passes_context_workflow():
    report = run_mock_eval(push_langfuse=False)

    assert report["passed"] is True
    assert report["passed_count"] == report["total_count"]
    assert report["dataset"] == "copepod-plan-mode-v1"

    scores = {item["name"]: item for item in report["results"]}
    assert report["total_count"] >= 13
    assert scores["upload_ecotaxa_creates_data_understanding"]["passed"] is True
    assert scores["data_understanding_coverage_is_sufficient"]["passed"] is True
    assert scores["analyse_blocked_before_active_artifacts"]["passed"] is True
    assert scores[
        "graph_context_without_data_understanding_version_is_blocked"
    ]["passed"] is True
    assert scores[
        "phase_gate_blocks_graph_context_before_data_understanding_confirmation"
    ]["passed"] is True
    assert scores["plan_ready_button_not_emitted_before_minimum_turns"]["passed"] is True
    assert scores["backend_phase_gate_blocks_premature_plan_ready_button"]["passed"] is True
    assert scores["data_understanding_confirmation_activates_artifact"]["passed"] is True
    assert scores["graph_context_draft_links_to_active_du"]["passed"] is True
    assert scores["plan_ready_after_graph_context_activation"]["passed"] is True
    assert scores["upload_in_analyse_creates_draft_without_replan"]["passed"] is True
    assert scores[
        "analyse_blocked_when_graph_context_references_stale_data_understanding"
    ]["passed"] is True
    assert scores["artifact_debug_routes_are_copepod_only"]["passed"] is True


@pytest.mark.workflow
def test_live_eval_prompt_keeps_session_context_out_of_static_prefix():
    system_prompt = _live_eval_system_prompt()
    runtime_context = _live_eval_runtime_context("session-abc")

    assert "session-abc" not in system_prompt
    assert "eval-user:session-abc:copepod" in runtime_context


@pytest.mark.tool_contract
def test_compact_inspect_file_keeps_column_metadata_for_infer_column_roles():
    compact = _compact_tool_result(
        "inspect_file",
        {
            "n_rows": 10,
            "n_columns": 2,
            "source_type_guess": {"value": "likely_ecotaxa"},
            "columns": [
                {
                    "name": "depth_m",
                    "dtype": "float64",
                    "semantic_guess": "depth",
                    "unit_guess": "m",
                    "confidence": "high",
                    "missing_rate": 0.0,
                    "missing_count": 0,
                    "sample_values": [1.0],
                },
                {
                    "name": "taxon",
                    "dtype": "string",
                    "semantic_guess": None,
                    "unit_guess": None,
                    "confidence": "low",
                    "missing_rate": 0.1,
                    "missing_count": 1,
                    "sample_values": ["copepod"],
                },
            ],
            "warnings": [],
        },
    )

    assert compact["n_columns"] == 2
    assert compact["columns"][0]["name"] == "depth_m"
    assert compact["columns"][1]["name"] == "taxon"
    assert compact["unknown_columns"] == ["taxon"]
    assert compact["known_by_role"]["depth"] == ["depth_m"]


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }


def _latest_tool_result(messages: list[dict], tool_name: str) -> dict:
    for message in reversed(messages):
        if message.get("role") == "tool" and message.get("name") == tool_name:
            return json.loads(message["content"])
    raise AssertionError(f"Missing tool result for {tool_name}")


@pytest.mark.llm_protocol
def test_live_eval_runner_drives_llm_tool_workflow_without_real_api(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-live-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                _tool_call(
                                    "call-du-draft",
                                    "create_data_understanding_draft",
                                    {
                                        "session_key": "eval-user:ignored:copepod",
                                        "artifact": {
                                            "files": [
                                                {
                                                    "original_filename": "ecotaxa_sample_50.tsv",
                                                    "source_type_guess": {
                                                        "value": "likely_ecotaxa",
                                                        "confidence": "high",
                                                    },
                                                    "columns": [],
                                                    "roles": {},
                                                }
                                            ],
                                            "global": {},
                                            "overrides": [],
                                            "column_catalogue": [
                                                {
                                                    "column": "object_depth_min",
                                                    "role": "depth",
                                                    "role_confidence": "high",
                                                }
                                            ],
                                            "coverage_assessment": {
                                                "status": "sufficient",
                                                "format": "tsv",
                                                "structural_signals": ["format:tsv", "columns:1"],
                                                "semantic_signals": ["source_type:likely_ecotaxa", "roles:1"],
                                                "gaps": [],
                                            },
                                        },
                                    },
                                )
                            ],
                        }
                    }
                ]
            }
        if calls["count"] == 2:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "### Data Understanding\nDraft created. Please confirm.",
                        }
                    }
                ]
            }
        if calls["count"] == 3:
            du = _latest_tool_result(messages, "create_data_understanding_draft")
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                _tool_call(
                                    "call-du-active",
                                    "activate_data_understanding",
                                    {
                                        "session_key": "eval-user:ignored:copepod",
                                        "version_id": du["version_id"],
                                    },
                                ),
                                _tool_call(
                                    "call-gc-draft",
                                    "create_graph_context_draft",
                                    {
                                        "session_key": "eval-user:ignored:copepod",
                                        "artifact": {
                                            "data_understanding_version_id": du["version_id"],
                                            "objective": "Distribution verticale",
                                            "columns": ["object_depth_min"],
                                            "filters": [],
                                            "units": {"depth": "m"},
                                            "chart_type": "vertical distribution",
                                            "language": "Python",
                                            "output_artifacts": ["png"],
                                            "feasibility": "exploratory",
                                            "blockers": [],
                                        },
                                    },
                                ),
                            ],
                        }
                    }
                ]
            }
        if calls["count"] == 4:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "### Graph Context\nDraft created. Please confirm.",
                        }
                    }
                ]
            }
        if calls["count"] == 5:
            gc = _latest_tool_result(messages, "create_graph_context_draft")
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                _tool_call(
                                    "call-gc-active",
                                    "activate_graph_context",
                                    {
                                        "session_key": "eval-user:ignored:copepod",
                                        "version_id": gc["version_id"],
                                    },
                                ),
                                _tool_call(
                                    "call-gc-read",
                                    "get_active_graph_context",
                                    {"session_key": "eval-user:ignored:copepod"},
                                ),
                            ],
                        }
                    }
                ]
            }
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Contexte validé.\n[PLAN_READY]",
                    }
                }
            ]
        }

    report = run_live_eval(
        push_langfuse=False,
        completion_fn=fake_completion,
    )

    assert report["mode"] == "live"
    assert calls["count"] == 6

    scores = {item["name"]: item for item in report["results"]}
    # Core workflow checks — always expected to pass with any LLM
    assert scores["live_llm_created_data_understanding_draft"]["passed"] is True
    assert scores["live_llm_waited_for_data_understanding_confirmation"]["passed"] is True
    assert scores["live_llm_created_graph_context_draft_linked_to_active_du"]["passed"] is True
    assert scores[
        "live_llm_did_not_emit_plan_ready_before_graph_context_confirmation"
    ]["passed"] is True
    assert scores["live_backend_blocked_premature_plan_ready_button"]["passed"] is True
    assert scores["live_llm_waited_for_graph_context_confirmation"]["passed"] is True
    assert scores["live_plan_ready_enables_analyse_mode"]["passed"] is True
    assert scores["live_phase1_efficient"]["passed"] is True
    assert scores["live_du_payload_has_column_catalogue"]["passed"] is True
    assert scores["live_du_payload_has_sufficient_coverage"]["passed"] is True
    assert scores["live_gc_payload_has_all_required_fields"]["passed"] is True
    # The live runner must keep column_catalogue non-empty even in a fake-LLM test.


@pytest.mark.llm_protocol
def test_live_du_only_runner_stops_after_data_understanding(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-live-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                _tool_call(
                                    "call-du-draft",
                                    "create_data_understanding_draft",
                                    {
                                        "session_key": "eval-user:ignored:copepod",
                                        "artifact": {
                                            "files": [
                                                {
                                                    "original_filename": "ecotaxa_sample_50.tsv",
                                                    "source_type_guess": {
                                                        "value": "likely_ecotaxa",
                                                        "confidence": "high",
                                                    },
                                                    "columns": [],
                                                    "roles": {},
                                                }
                                            ],
                                            "global": {},
                                            "overrides": [],
                                            "column_catalogue": [
                                                {
                                                    "column": "object_depth_min",
                                                    "role": "depth",
                                                    "role_confidence": "high",
                                                }
                                            ],
                                            "coverage_assessment": {
                                                "status": "sufficient",
                                                "format": "tsv",
                                                "structural_signals": ["format:tsv", "columns:1"],
                                                "semantic_signals": ["source_type:likely_ecotaxa", "roles:1"],
                                                "gaps": [],
                                            },
                                        },
                                    },
                                )
                            ],
                        }
                    }
                ]
            }
        if calls["count"] == 2:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "### Data Understanding\nDraft created. Please confirm.",
                        }
                    }
                ]
            }
        if calls["count"] == 3:
            du = _latest_tool_result(messages, "create_data_understanding_draft")
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                _tool_call(
                                    "call-du-active",
                                    "activate_data_understanding",
                                    {
                                        "session_key": "eval-user:ignored:copepod",
                                        "version_id": du["version_id"],
                                    },
                                )
                            ],
                        }
                    }
                ]
            }
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Analyse du fichier validée.",
                    }
                }
            ]
        }

    report = run_live_du_only_eval(
        push_langfuse=False,
        completion_fn=fake_completion,
    )

    assert report["mode"] == "live-du-only"
    assert calls["count"] == 4

    scores = {item["name"]: item for item in report["results"]}
    assert scores["live_du_only_created_data_understanding_draft"]["passed"] is True
    assert scores["live_du_only_waited_for_data_understanding_confirmation"]["passed"] is True
    assert scores["live_du_only_activated_data_understanding"]["passed"] is True
    assert scores["live_du_only_no_graph_context_created"]["passed"] is True
    assert scores["live_du_only_phase1_efficient"]["passed"] is True
    assert scores["live_du_only_payload_has_column_catalogue"]["passed"] is True
    assert scores["live_du_only_payload_has_sufficient_coverage"]["passed"] is True
    assert scores["live_du_only_describe_column_covered_all_unmatched"]["passed"] is True
    assert scores["live_du_only_no_internal_terms_in_llm_text"]["passed"] is True


@pytest.mark.tool_contract
def test_cli_dispatches_du_only_mode(monkeypatch):
    import sys

    calls = {"du_only": 0, "live": 0, "mock": 0}

    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_live_du_only_eval",
        lambda **kwargs: calls.__setitem__("du_only", calls["du_only"] + 1) or {
            "dataset": "copepod-plan-mode-v1",
            "mode": "live-du-only",
            "passed": True,
            "passed_count": 1,
            "total_count": 1,
            "results": [],
            "langfuse_trace_url": None,
        },
    )
    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_live_eval",
        lambda **kwargs: calls.__setitem__("live", calls["live"] + 1) or None,
    )
    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_mock_eval",
        lambda **kwargs: calls.__setitem__("mock", calls["mock"] + 1) or None,
    )
    monkeypatch.setattr(sys, "argv", ["run_copepod_plan_mode_eval.py", "--live-du-only"])

    assert main() == 0
    assert calls == {"du_only": 1, "live": 0, "mock": 0}


@pytest.mark.llm_protocol
def test_live_eval_runner_scores_premature_plan_ready_text_but_backend_blocks_button(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-live-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                _tool_call(
                                    "call-du-draft",
                                    "create_data_understanding_draft",
                                    {
                                        "session_key": "eval-user:ignored:copepod",
                                        "artifact": {
                                            "files": [
                                                {
                                                    "original_filename": "ecotaxa_sample_50.tsv",
                                                    "source_type_guess": {
                                                        "value": "likely_ecotaxa",
                                                        "confidence": "high",
                                                    },
                                                    "columns": [],
                                                    "roles": {},
                                                }
                                            ],
                                            "global": {},
                                            "overrides": [],
                                            "column_catalogue": [
                                                {
                                                    "column": "object_depth_min",
                                                    "role": "depth",
                                                    "role_confidence": "high",
                                                }
                                            ],
                                            "coverage_assessment": {
                                                "status": "sufficient",
                                                "format": "tsv",
                                                "structural_signals": ["format:tsv", "columns:1"],
                                                "semantic_signals": ["source_type:likely_ecotaxa", "roles:1"],
                                                "gaps": [],
                                            },
                                        },
                                    },
                                )
                            ],
                        }
                    }
                ]
            }
        if calls["count"] == 2:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "### Data Understanding\nDraft created. Please confirm.",
                        }
                    }
                ]
            }
        if calls["count"] == 3:
            du = _latest_tool_result(messages, "create_data_understanding_draft")
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                _tool_call(
                                    "call-du-active",
                                    "activate_data_understanding",
                                    {
                                        "session_key": "eval-user:ignored:copepod",
                                        "version_id": du["version_id"],
                                    },
                                ),
                                _tool_call(
                                    "call-gc-draft",
                                    "create_graph_context_draft",
                                    {
                                        "session_key": "eval-user:ignored:copepod",
                                        "artifact": {
                                            "data_understanding_version_id": du["version_id"],
                                            "objective": "Distribution verticale",
                                            "columns": ["object_depth_min"],
                                            "filters": [],
                                            "units": {"depth": "m"},
                                            "chart_type": "vertical distribution",
                                            "language": "Python",
                                            "output_artifacts": ["png"],
                                            "feasibility": "exploratory",
                                            "blockers": [],
                                        },
                                    },
                                ),
                            ],
                        }
                    }
                ]
            }
        if calls["count"] == 4:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "### Graph Context\nDraft created too early.\n[PLAN_READY]",
                        }
                    }
                ]
            }
        if calls["count"] == 5:
            gc = _latest_tool_result(messages, "create_graph_context_draft")
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                _tool_call(
                                    "call-gc-active",
                                    "activate_graph_context",
                                    {
                                        "session_key": "eval-user:ignored:copepod",
                                        "version_id": gc["version_id"],
                                    },
                                )
                            ],
                        }
                    }
                ]
            }
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Contexte validé.\n[PLAN_READY]",
                    }
                }
            ]
        }

    report = run_live_eval(
        push_langfuse=False,
        completion_fn=fake_completion,
    )

    scores = {item["name"]: item for item in report["results"]}
    assert scores[
        "live_llm_did_not_emit_plan_ready_before_graph_context_confirmation"
    ]["passed"] is False
    assert scores["live_backend_blocked_premature_plan_ready_button"]["passed"] is True
    assert scores["live_plan_ready_enables_analyse_mode"]["passed"] is True
    assert scores["live_du_payload_has_column_catalogue"]["passed"] is True
    assert scores["live_du_payload_has_sufficient_coverage"]["passed"] is True
    # report["passed"] is False because premature PLAN_READY score failed (expected)
