import json

from scripts.evals.run_copepod_plan_mode_eval import run_live_eval, run_mock_eval


def test_mock_eval_runner_passes_context_workflow():
    report = run_mock_eval(push_langfuse=False)

    assert report["passed"] is True
    assert report["passed_count"] == report["total_count"]
    assert report["dataset"] == "copepod-plan-mode-v1"

    scores = {item["name"]: item for item in report["results"]}
    assert report["total_count"] >= 10
    assert scores["upload_ecotaxa_creates_data_understanding"]["passed"] is True
    assert scores["analyse_blocked_before_active_artifacts"]["passed"] is True
    assert scores[
        "graph_context_without_data_understanding_version_is_blocked"
    ]["passed"] is True
    assert scores["plan_ready_button_not_emitted_before_minimum_turns"]["passed"] is True
    assert scores["data_understanding_confirmation_activates_artifact"]["passed"] is True
    assert scores["graph_context_draft_links_to_active_du"]["passed"] is True
    assert scores["plan_ready_after_graph_context_activation"]["passed"] is True
    assert scores["upload_in_analyse_creates_draft_without_replan"]["passed"] is True
    assert scores[
        "analyse_blocked_when_graph_context_references_stale_data_understanding"
    ]["passed"] is True
    assert scores["artifact_debug_routes_are_copepod_only"]["passed"] is True


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


def test_live_eval_runner_drives_llm_tool_workflow_without_real_api():
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
        model="fake-live-model",
    )

    assert report["passed"] is True
    assert report["mode"] == "live"
    assert calls["count"] == 6

    scores = {item["name"]: item for item in report["results"]}
    assert scores["live_llm_created_data_understanding_draft"]["passed"] is True
    assert scores["live_llm_waited_for_data_understanding_confirmation"]["passed"] is True
    assert scores["live_llm_created_graph_context_draft_linked_to_active_du"]["passed"] is True
    assert scores["live_llm_waited_for_graph_context_confirmation"]["passed"] is True
    assert scores["live_plan_ready_enables_analyse_mode"]["passed"] is True
