import json

import pytest

from core.config import settings
from scripts.evals.run_copepod_plan_mode_eval import main, run_live_online_mode_eval


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _latest_tool_result(messages: list[dict], tool_name: str) -> dict:
    for message in reversed(messages):
        if message.get("role") == "tool" and message.get("name") == tool_name:
            return json.loads(message["content"])
    raise AssertionError(f"Missing tool result for {tool_name}")


@pytest.mark.llm_protocol
def test_live_online_mode_runner_handles_disabled_and_explicit_requests(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-live-model")
    calls = {"count": 0}

    def fake_completion(*, messages, metadata=None, **kwargs):
        calls["count"] += 1
        scenario = (metadata or {}).get("scenario")
        phase = (metadata or {}).get("phase")
        round_index = (metadata or {}).get("round")

        if scenario == "online-off-explicit-request":
            return {
                "choices": [
                    {"message": {"role": "assistant", "content": (
                        "Mode En Ligne est désactivé pour cette session. "
                        "Je peux rester sur les données locales ou vous pouvez activer le mode en ligne."
                    )}}
                ]
            }

        if scenario == "online-on-incomplete-request":
            if phase == "online-turn" and round_index == 1:
                return {
                    "choices": [
                        {"message": {"role": "assistant", "content": None, "tool_calls": [
                            _tool_call(
                                "call-plan",
                                "plan_remote_source_request",
                                {
                                    "request_text": (
                                        "Va me chercher Bio-ORACLE pour le scénario SSP126 "
                                        "sur la variable si_mean."
                                    ),
                                    "source_hint": "bio_oracle",
                                },
                            )
                        ]}}
                    ]
                }
            return {
                "choices": [
                    {"message": {"role": "assistant", "content": (
                        "Quelle zone géographique voulez-vous utiliser pour Bio-ORACLE ?"
                    )}}
                ]
            }

        if scenario == "online-on-complete-request":
            if phase == "online-turn" and round_index == 1:
                return {
                    "choices": [
                        {"message": {"role": "assistant", "content": None, "tool_calls": [
                            _tool_call(
                                "call-plan",
                                "plan_remote_source_request",
                                {
                                    "request_text": (
                                        "Va me chercher OGSL pour la station 12 "
                                        "entre 2024-01-01 et 2024-03-31 avec TE90 et PSAL."
                                    ),
                                    "source_hint": "ogsl",
                                },
                            )
                        ]}}
                    ]
                }
            plan = _latest_tool_result(messages, "plan_remote_source_request")
            return {
                "choices": [
                    {"message": {"role": "assistant", "content": (
                        f"Je peux poursuivre avec {plan['source_id']}. "
                        "Je n'ai pas besoin d'une clarification supplémentaire."
                    )}}
                ]
            }

        if scenario == "online-on-complete-request-fetch":
            if phase == "online-turn" and round_index == 1:
                return {
                    "choices": [
                        {"message": {"role": "assistant", "content": None, "tool_calls": [
                            _tool_call(
                                "call-plan",
                                "plan_remote_source_request",
                                {
                                    "request_text": (
                                        "Va me chercher Bio-ORACLE pour le scénario SSP126 "
                                        "de 2020 à 2030 sur la variable si_mean aux coordonnées 48.2, -68.4."
                                    ),
                                    "source_hint": "bio_oracle",
                                },
                            )
                        ]}}
                    ]
                }
            if phase == "online-turn" and round_index == 2:
                plan = _latest_tool_result(messages, "plan_remote_source_request")
                return {
                    "choices": [
                        {"message": {"role": "assistant", "content": None, "tool_calls": [
                            _tool_call(
                                "call-fetch",
                                "fetch_remote_source_dataset",
                                {
                                    "session_key": f"eval-user:{scenario}:copepod",
                                    "source_id": plan["source_id"],
                                    "parameters": {
                                        **plan["parameters"],
                                        "zone": {"latitude": 48.2, "longitude": -68.4},
                                    },
                                },
                            )
                        ]}}
                    ]
                }
            fetch = _latest_tool_result(messages, "fetch_remote_source_dataset")
            return {
                "choices": [
                    {"message": {"role": "assistant", "content": (
                        f"Je peux poursuivre avec {fetch['source_id']} et le fichier dérivé {fetch['original_filename']}."
                    )}}
                ]
            }

        raise AssertionError(f"Unexpected scenario: {scenario}")

    report = run_live_online_mode_eval(push_langfuse=False, completion_fn=fake_completion)

    assert report["mode"] == "live-online-mode"
    assert report["total_count"] >= 5
    assert calls["count"] >= 4

    scores = {item["name"]: item for item in report["results"]}
    assert scores["live_online_mode_disabled_replies_with_allowed_alternative"]["passed"] is True
    assert scores["live_online_mode_incomplete_request_asks_one_clarification"]["passed"] is True
    assert scores["live_online_mode_incomplete_request_calls_source_planner"]["passed"] is True
    assert scores["live_online_mode_complete_request_calls_source_planner"]["passed"] is True
    assert scores["live_online_mode_complete_request_does_not_ask_clarification"]["passed"] is True
    assert scores["live_online_mode_complete_request_calls_fetch_tool"]["passed"] is True
    assert scores["live_online_mode_complete_request_persists_derived_csv"]["passed"] is True
    assert report["passed"] is True


@pytest.mark.tool_contract
def test_cli_dispatches_online_mode(monkeypatch):
    import sys

    calls = {"online": 0, "du_only": 0, "gc_only": 0, "live": 0, "mock": 0}

    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_live_online_mode_eval",
        lambda **kwargs: calls.__setitem__("online", calls["online"] + 1) or {
            "dataset": "copepod-plan-mode-v1",
            "mode": "live-online-mode",
            "passed": True,
            "passed_count": 1,
            "total_count": 1,
            "results": [],
            "langfuse_trace_url": None,
        },
    )
    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_live_du_only_eval",
        lambda **kwargs: calls.__setitem__("du_only", calls["du_only"] + 1) or None,
    )
    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_live_gc_only_eval",
        lambda **kwargs: calls.__setitem__("gc_only", calls["gc_only"] + 1) or None,
    )
    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_live_eval",
        lambda **kwargs: calls.__setitem__("live", calls["live"] + 1) or None,
    )
    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_mock_eval",
        lambda **kwargs: calls.__setitem__("mock", calls["mock"] + 1) or None,
    )
    monkeypatch.setattr(sys, "argv", ["run_copepod_plan_mode_eval.py", "--live-online-mode"])

    assert main() == 0
    assert calls == {"online": 1, "du_only": 0, "gc_only": 0, "live": 0, "mock": 0}
