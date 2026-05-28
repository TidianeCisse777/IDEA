from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from pathlib import Path
import json

from .harness import EvalHarness
from .llm_driver import _default_live_completion, _live_tool_impls, _run_llm_turn, _tool_call_to_dict
from .system_messages import _build_eval_system_message

_SOURCE_TOOL_NAMES = {"list_available_sources", "describe_source", "plan_remote_source_request", "fetch_remote_source_dataset"}


@dataclass
class OnlineModeScenario:
    slug: str
    label: str
    online_mode_enabled: bool
    user_message: str
    expect_source_plan: bool = False
    expect_single_clarification: bool = False
    expect_allowed_alternative: bool = False
    expect_fetch: bool = False


_ONLINE_MODE_SCENARIOS: list[OnlineModeScenario] = [
    OnlineModeScenario(
        slug="online-off-explicit-request",
        label="Online mode off, explicit remote request",
        online_mode_enabled=False,
        user_message=(
            "Va me chercher Bio-ORACLE pour le scénario SSP126 de 2020 à 2050 "
            "sur la variable si_mean."
        ),
        expect_allowed_alternative=True,
    ),
    OnlineModeScenario(
        slug="online-on-incomplete-request",
        label="Online mode on, incomplete Bio-ORACLE request",
        online_mode_enabled=True,
        user_message=(
            "Va me chercher Bio-ORACLE pour le scénario SSP126 de 2020 à 2050 "
            "sur la variable si_mean."
        ),
        expect_source_plan=True,
        expect_single_clarification=True,
    ),
    OnlineModeScenario(
        slug="online-on-complete-request",
        label="Online mode on, complete OGSL request",
        online_mode_enabled=True,
        user_message=(
            "Va me chercher OGSL pour la station 12 entre 2024-01-01 et 2024-03-31 "
            "avec TE90 et PSAL, pour la mission 2024_06 BioDiv."
        ),
        expect_source_plan=True,
    ),
    OnlineModeScenario(
        slug="online-on-complete-request-fetch",
        label="Online mode on, complete Bio-ORACLE request with fetch",
        online_mode_enabled=True,
        user_message=(
            "Va me chercher Bio-ORACLE pour le scénario SSP126 de 2020 à 2030 "
            "sur la variable si_mean aux coordonnées 48.2, -68.4."
        ),
        expect_source_plan=True,
        expect_fetch=True,
    ),
]


def _extract_tool_names(messages: list[dict]) -> list[str]:
    names: list[str] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for raw_call in message.get("tool_calls") or []:
            call = _tool_call_to_dict(raw_call)
            name = (call.get("function") or {}).get("name")
            if name:
                names.append(name)
    return names


def _latest_tool_result(messages: list[dict], tool_name: str) -> dict:
    for message in reversed(messages):
        if message.get("role") == "tool" and message.get("name") == tool_name:
            content = message.get("content")
            if isinstance(content, str):
                return json.loads(content)
            if isinstance(content, dict):
                return content
    raise AssertionError(f"Missing tool result for {tool_name}")


def run_live_online_mode_eval(
    *,
    push_langfuse: bool = False,
    completion_fn: Callable[..., Any] | None = None,
    scenario_slugs: list[str] | None = None,
) -> dict:
    """Run the live LLM against online-mode policy scenarios."""
    completion_fn = completion_fn or _default_live_completion

    scenarios = _ONLINE_MODE_SCENARIOS
    if scenario_slugs:
        wanted = {slug.strip() for slug in scenario_slugs if slug.strip()}
        scenarios = [s for s in _ONLINE_MODE_SCENARIOS if s.slug in wanted]
        if not scenarios:
            available = [s.slug for s in _ONLINE_MODE_SCENARIOS]
            raise ValueError(
                f"No online-mode scenarios matched {sorted(wanted)!r}. "
                f"Available: {available}."
            )

    with EvalHarness(
        suite="online-mode",
        log_prefix="live_online_mode_eval_",
        tags=["eval", "copepod", "online-mode", "live"],
        mode="live-online-mode",
        push_langfuse=push_langfuse,
        lf_file_hint="Mode En Ligne",
    ) as ctx:
        ctx.log("    scope=OnlineMode-only\n")

        def _run_scenario(scenario: OnlineModeScenario, scenario_session_id: str, scenario_session_key: str) -> dict[str, Any]:
            ctx.store.set_online_mode(scenario_session_key, scenario.online_mode_enabled)
            messages: list[dict] = [
                {
                    "role": "system",
                    "content": _build_eval_system_message(ctx.store, scenario_session_id),
                },
                {"role": "user", "content": scenario.user_message},
            ]
            base_metadata = {
                "session_id": scenario_session_key,
                "tags": ctx.tags + [scenario.slug],
                "dataset": "copepod-plan-mode-v1",
                "scenario": scenario.slug,
            }

            span = ctx.trace.span(name=f"phase/online-mode/{scenario.slug}", input={"scenario": scenario.slug}) if ctx.trace else None
            reply = _run_llm_turn(
                messages=messages,
                tool_impls=_live_tool_impls(ctx.tools, scenario_session_key),
                model=ctx.model_name,
                completion_fn=completion_fn,
                metadata={**base_metadata, "phase": "online-turn", "lf_phase_span": span},
                log_fn=ctx.log,
            )
            if span is not None:
                span.end()

            tool_names = _extract_tool_names(messages)
            return {
                "session_key": scenario_session_key,
                "reply": reply,
                "messages": messages,
                "tool_names": tool_names,
            }

        scenario_states: list[tuple[OnlineModeScenario, dict[str, Any]]] = []
        for scenario in scenarios:
            scenario_session_id = f"{ctx.session_id}-{scenario.slug}"
            scenario_session_key = f"eval-user:{scenario_session_id}:copepod"
            ctx.log(f"--- SCENARIO: {scenario.slug} ---")
            state = _run_scenario(scenario, scenario_session_id, scenario_session_key)
            scenario_states.append((scenario, state))

            tool_names = set(state["tool_names"])
            reply = state["reply"]
            lowered = reply.lower()

            if scenario.online_mode_enabled:
                source_tool_ok = bool(tool_names & _SOURCE_TOOL_NAMES)
            else:
                source_tool_ok = not bool(tool_names & _SOURCE_TOOL_NAMES)

            ctx.result(
                "live_online_mode_source_tool_policy_respected",
                source_tool_ok,
                (
                    "Scenario respected the source-tool policy."
                    if source_tool_ok
                    else f"Unexpected source-tool use: {sorted(tool_names & _SOURCE_TOOL_NAMES)}"
                ),
                {"case_type": "common", "scenario": scenario.slug, "tool_names": sorted(tool_names)},
            )

            if scenario.expect_allowed_alternative:
                allowed_alternative = (
                    "mode en ligne" in lowered
                    or "local" in lowered
                    or "rag" in lowered
                    or "alternative" in lowered
                    or "activer" in lowered
                )
                no_source_call = not bool(tool_names & _SOURCE_TOOL_NAMES)
                ctx.result(
                    "live_online_mode_disabled_replies_with_allowed_alternative",
                    allowed_alternative and no_source_call,
                    f"Disabled online mode reply: {reply[:240]!r}",
                    {"case_type": "edge", "scenario": scenario.slug, "tool_names": sorted(tool_names)},
                )

            if scenario.expect_single_clarification:
                question_count = reply.count("?")
                clarification_ok = question_count == 1 or (
                    "?" in reply and question_count <= 2
                )
                ctx.result(
                    "live_online_mode_incomplete_request_asks_one_clarification",
                    clarification_ok,
                    f"Incomplete request reply: {reply[:240]!r}",
                    {"case_type": "common", "scenario": scenario.slug, "question_count": question_count},
                )

            if scenario.expect_source_plan:
                planned = "plan_remote_source_request" in tool_names
                ctx.result(
                    "live_online_mode_incomplete_request_calls_source_planner"
                    if scenario.expect_single_clarification
                    else "live_online_mode_complete_request_calls_source_planner",
                    planned,
                    f"Remote-source planner was {'used' if planned else 'not used'} for scenario {scenario.slug}.",
                    {"case_type": "common", "scenario": scenario.slug, "tool_names": sorted(tool_names)},
                )

                if scenario.slug == "online-on-complete-request":
                    no_question = "?" not in reply
                    ctx.result(
                        "live_online_mode_complete_request_does_not_ask_clarification",
                        no_question,
                        f"Complete request reply: {reply[:240]!r}",
                        {"case_type": "common", "scenario": scenario.slug},
                    )

            if scenario.expect_fetch:
                fetched = "fetch_remote_source_dataset" in tool_names
                ctx.result(
                    "live_online_mode_complete_request_calls_fetch_tool",
                    fetched,
                    f"Fetch tool was {'used' if fetched else 'not used'} for scenario {scenario.slug}.",
                    {"case_type": "common", "scenario": scenario.slug, "tool_names": sorted(tool_names)},
                )
                if fetched:
                    fetch_result = _latest_tool_result(state["messages"], "fetch_remote_source_dataset")
                    file_path = fetch_result.get("file_path")
                    file_exists = bool(file_path) and Path(file_path).exists()
                    ctx.result(
                        "live_online_mode_complete_request_persists_derived_csv",
                        fetch_result.get("status") == "persisted" and file_exists,
                        f"Fetch tool result: {fetch_result!r}",
                        {"case_type": "common", "scenario": scenario.slug, "file_path": file_path},
                    )

        # Keep the pack lean and explicit.
        ctx.result(
            "live_online_mode_pack_has_expected_number_of_scenarios",
            len(scenario_states) == len(scenarios),
            f"Ran {len(scenario_states)} scenario(s).",
            {"case_type": "edge"},
        )

    return ctx.report
