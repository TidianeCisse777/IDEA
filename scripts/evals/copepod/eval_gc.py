from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .fixtures import ECOTAXA, ECOPART, _seed_active_data_understanding
from .harness import EvalHarness
from .llm_driver import (
    _default_live_completion,
    _gc_only_tool_impls,
    _gc_only_tool_specs,
    _run_llm_turn,
)
from .system_messages import _build_gc_only_system_message

_FORBIDDEN_TERMS = ["data understanding", "graph context", "version_id", "du-", "gc-"]

_PHASE1_TOOL_NAMES = {
    "inspect_file", "infer_column_roles", "describe_column",
    "summarize_understanding", "create_data_understanding_draft",
}


@dataclass
class GcScenario:
    """Declares expected LLM behaviour for one GC-only eval scenario.

    The assertion engine in run_live_gc_only_eval reads these fields to
    generate the right checks — adding a scenario means adding one entry
    to _GC_SCENARIOS, nothing else.
    """
    slug: str
    label: str
    seed_paths: list[Path]
    user_messages: list[str]
    should_confirm_gc: bool = False
    # Expected artifact outcomes
    expect_gc_draft: bool = False
    expect_gc_activated: bool = False
    expect_plan_ready: bool = False
    # Expected conversational behaviour
    expect_targeted_question: bool = False
    question_fallback_keywords: list[str] = field(default_factory=list)
    strict_no_self_intro: bool = False   # extra check: LLM must not self-introduce
    expect_analysis_refusal: bool = False
    # Technical quirk: GC draft may be created during turn-1 and only visible after turn-2
    check_tool_calls_for_draft: bool = False


_GC_SCENARIOS: list[GcScenario] = [
    GcScenario(
        slug="rich",
        label="Contexte riche",
        seed_paths=[ECOTAXA, ECOPART],
        user_messages=[
            (
                "Le DU est déjà validé. Je veux une distribution verticale "
                "de la biomasse des copépodes sur EcoTaxa + EcoPart, en mètres, "
                "avec un histogramme vertical en Python, sortie png + csv. "
                "Prépare le contexte scientifique."
            ),
            "Oui, c'est correct. Tu peux activer le contexte graphique.",
        ],
        should_confirm_gc=True,
        expect_gc_draft=True,
        expect_gc_activated=True,
        expect_plan_ready=True,
        check_tool_calls_for_draft=True,
    ),
    GcScenario(
        slug="poor",
        label="Contexte pauvre",
        seed_paths=[ECOTAXA, ECOPART],
        user_messages=[
            "Je veux faire un graphe de la campagne, "
            "mais je n'ai pas encore fixé les unités ni le type de graphique."
        ],
        expect_targeted_question=True,
        question_fallback_keywords=["quelle"],
    ),
    GcScenario(
        slug="offtopic",
        label="Hors sujet",
        seed_paths=[ECOTAXA, ECOPART],
        user_messages=["Parle-moi plutôt des copépodes en général, sans graphique."],
        expect_targeted_question=True,
        strict_no_self_intro=True,
        question_fallback_keywords=["contexte"],
    ),
    GcScenario(
        slug="analysis-jump",
        label="Saut vers analyse",
        seed_paths=[ECOTAXA, ECOPART],
        user_messages=["Fais directement le code Python pour l'analyse et le graphique."],
        expect_analysis_refusal=True,
    ),
]


def run_live_gc_only_eval(
    *,
    push_langfuse: bool = False,
    completion_fn: Callable[..., Any] | None = None,
    scenario_slugs: list[str] | None = None,
) -> dict:
    """Run the live LLM through Graph Context only, starting from an already active DU."""
    completion_fn = completion_fn or _default_live_completion

    scenarios = _GC_SCENARIOS
    if scenario_slugs:
        wanted = {slug.strip() for slug in scenario_slugs if slug.strip()}
        scenarios = [s for s in _GC_SCENARIOS if s.slug in wanted]
        if not scenarios:
            available = [s.slug for s in _GC_SCENARIOS]
            raise ValueError(
                f"No GC-only scenarios matched {sorted(wanted)!r}. "
                f"Available: {available}."
            )

    with EvalHarness(
        suite="gc-only",
        log_prefix="live_gc_only_eval_",
        tags=["eval", "copepod", "plan-mode", "live", "gc-only"],
        mode="live-gc-only",
        push_langfuse=push_langfuse,
        lf_file_hint="EcoTaxa+EcoPart",
    ) as ctx:
        ctx.log("    seeds=EcoTaxa+EcoPart  scope=GraphContext-only\n")

        def _looks_like_self_introduction(text: str) -> bool:
            lowered = text.lower()
            return any(
                phrase in lowered
                for phrase in [
                    "je suis le copepod graphing assistant",
                    "je suis un assistant",
                    "je suis l'assistant",
                    "spécialisé dans",
                    "specialisé dans",
                    "i am the",
                    "i'm the",
                    "i am an assistant",
                ]
            )

        def _looks_like_targeted_context_question(text: str) -> bool:
            lowered = text.lower()
            return any(
                phrase in lowered
                for phrase in [
                    "objectif", "contexte", "question", "précision", "precision",
                    "graphe", "graphique", "explorer", "clarifier", "cadrer", "quelle",
                ]
            )

        def _run_scenario(scenario: GcScenario, scenario_session_id: str, scenario_session_key: str) -> dict[str, Any]:
            seed = _seed_active_data_understanding(
                client=ctx.client,
                tools=ctx.tools,
                session_id=scenario_session_id,
                session_key=scenario_session_key,
                fixture_paths=scenario.seed_paths,
            )
            messages: list[dict] = [
                {
                    "role": "system",
                    "content": _build_gc_only_system_message(ctx.store, scenario_session_id),
                }
            ]
            replies: list[str] = []
            phase1_attempts = 0
            phase1_blocked = 0
            base_metadata = {
                "session_id": scenario_session_key,
                "tags": ctx.tags + [scenario.slug],
                "dataset": "copepod-plan-mode-v1",
                "scenario": scenario.slug,
            }

            def _run_turn(turn_label: str, user_text: str, span_name: str) -> str:
                messages.append({"role": "user", "content": user_text})
                span = ctx.trace.span(name=span_name, input={"scenario": scenario.slug, "turn": turn_label}) if ctx.trace else None
                reply = _run_llm_turn(
                    messages=messages,
                    tool_impls=_gc_only_tool_impls(ctx.tools, scenario_session_key),
                    model=ctx.model_name,
                    completion_fn=completion_fn,
                    metadata={**base_metadata, "phase": turn_label, "lf_phase_span": span},
                    tool_specs=_gc_only_tool_specs(),
                    log_fn=ctx.log,
                )
                if span is not None:
                    span.end()
                replies.append(reply)
                return reply

            try:
                _run_turn("gc-only-turn-1", scenario.user_messages[0], f"phase/gc-only/{scenario.slug}/turn-1")
                if scenario.should_confirm_gc and len(scenario.user_messages) > 1:
                    _run_turn("gc-only-turn-2", scenario.user_messages[1], f"phase/gc-only/{scenario.slug}/turn-2")
                for message in messages:
                    if message.get("role") == "tool" and message.get("name") in _PHASE1_TOOL_NAMES:
                        phase1_attempts += 1
                        if message.get("content") and "blocking_reason" in message["content"]:
                            phase1_blocked += 1
                gc_versions = ctx.store.get_artifact_versions(scenario_session_key, "graph_context")
                active_gc = ctx.store.get_active_artifact(scenario_session_key, "graph_context")
                return {
                    "session_key": scenario_session_key,
                    "replies": replies,
                    "messages": messages,
                    "active_du": seed["active"] if isinstance(seed, dict) else None,
                    "active_gc": active_gc,
                    "gc_versions": gc_versions,
                    "phase1_attempts": phase1_attempts,
                    "phase1_blocked": phase1_blocked,
                }
            except Exception as exc:
                raise RuntimeError(f"GC-only scenario {scenario.label} failed: {exc}") from exc

        # ── run all scenarios, then assert ────────────────────────────────────
        scenario_states: list[tuple[GcScenario, dict]] = []
        for scenario in scenarios:
            scenario_session_id = f"{ctx.session_id}-{scenario.slug}"
            scenario_session_key = f"eval-user:{scenario_session_id}:copepod"
            ctx.log(f"--- SCENARIO: {scenario.slug} ---")
            state = _run_scenario(scenario, scenario_session_id, scenario_session_key)
            scenario_states.append((scenario, state))

            slug = scenario.slug
            first_reply = state["replies"][0] if state["replies"] else ""
            gc_draft_created = bool(state["gc_versions"])
            if scenario.check_tool_calls_for_draft and len(state["replies"]) > 1:
                gc_draft_created = gc_draft_created or "create_graph_context_draft" in "".join(
                    m.get("name", "") for m in state["messages"] if m.get("role") == "tool"
                )
            gc_activated = bool(state["active_gc"])
            plan_ready_emitted = any("[PLAN_READY]" in reply for reply in state["replies"])
            phase1_reopened = any(
                m.get("role") == "tool" and m.get("name") in _PHASE1_TOOL_NAMES
                for m in state["messages"]
            )

            # universal: never reopened Phase 1
            ctx.result(
                f"gc_only_{slug}_never_reopened_phase1",
                not phase1_reopened,
                f"Scenario {slug} did not reopen Phase 1.",
                {"case_type": "edge", "scenario": slug, "phase1_attempts": state["phase1_attempts"]},
            )

            # gc draft and activation
            ctx.result(
                f"gc_only_{slug}_created_graph_context_draft",
                gc_draft_created == scenario.expect_gc_draft,
                f"Scenario {slug} {'created' if scenario.expect_gc_draft else 'did not create'} a Graph Context draft.",
                {"case_type": "common" if scenario.expect_gc_draft else "edge", "scenario": slug},
            )
            if scenario.expect_gc_draft:
                ctx.result(
                    f"gc_only_{slug}_activated_graph_context",
                    gc_activated == scenario.expect_gc_activated,
                    (
                        "Rich-context scenario activated the Graph Context after confirmation."
                        if scenario.expect_gc_activated
                        else f"Scenario {slug} did not activate Graph Context."
                    ),
                    {"case_type": "common" if scenario.expect_gc_activated else "edge", "scenario": slug},
                )
                ctx.result(
                    f"gc_only_plan_ready_after_gc_activation",
                    gc_activated and plan_ready_emitted,
                    "PLAN_READY was emitted only after Graph Context activation.",
                    {"case_type": "common", "scenario": slug},
                )
            else:
                ctx.result(
                    f"gc_only_{slug}_did_not_emit_plan_ready",
                    not plan_ready_emitted,
                    f"Scenario {slug} did not emit PLAN_READY.",
                    {"case_type": "edge", "scenario": slug},
                )
                ctx.result(
                    f"gc_only_{slug}_did_not_activate_graph_context",
                    not gc_activated,
                    f"Scenario {slug} did not activate Graph Context.",
                    {"case_type": "edge", "scenario": slug},
                )

            # targeted question check
            if scenario.expect_targeted_question:
                offtopic_reply = first_reply.lower()
                targeted_question = (
                    "?" in first_reply or _looks_like_targeted_context_question(first_reply)
                ) and not gc_draft_created
                base_ok = (
                    (
                        targeted_question
                        or "objectif scientifique" in offtopic_reply
                        or any(kw in offtopic_reply for kw in scenario.question_fallback_keywords)
                    )
                    and first_reply.count("?") <= 2
                )
                intro_ok = (not _looks_like_self_introduction(first_reply)) if scenario.strict_no_self_intro else True
                ctx.result(
                    f"gc_only_{slug}_asked_single_targeted_question_when_missing_fields",
                    base_ok and intro_ok,
                    f"Scenario {slug} replied with a targeted question: {first_reply[:200]!r}",
                    {"case_type": "common", "scenario": slug},
                )

            # analysis refusal check
            if scenario.expect_analysis_refusal:
                analysis_refusal = (
                    "Plan Mode" in first_reply
                    or "plan mode" in first_reply.lower()
                    or "Je suis en Plan Mode" in first_reply
                )
                ctx.result(
                    "gc_only_refused_direct_analysis_request_before_gc",
                    analysis_refusal and not state["phase1_attempts"],
                    f"Scenario analysis-jump refused direct analysis: {first_reply[:240]!r}",
                    {"case_type": "edge", "scenario": slug},
                )

        # cross-scenario: no internal terms leaked
        all_llm_text = "\n".join(
            reply for _, state in scenario_states for reply in state["replies"]
        ).lower()
        leaked = [term for term in _FORBIDDEN_TERMS if term in all_llm_text]
        ctx.result(
            "gc_only_no_internal_terms_in_llm_text",
            not leaked,
            "No forbidden downstream terms in LLM text." if not leaked
            else f"LLM leaked internal terms: {leaked}",
            {"case_type": "edge", "leaked": leaked},
        )

    return ctx.report
