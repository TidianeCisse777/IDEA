from __future__ import annotations

import json
from typing import Any, Callable

from .fixtures import ECOTAXA, _stage_fixture, _uploaded_path_label
from .harness import EvalHarness
from .llm_driver import _default_live_completion, _live_tool_impls, _run_llm_turn, _tool_call_to_dict
from .system_messages import _build_eval_system_message

_FORBIDDEN_USER_TERMS = ["graph context", "plan_ready", "analyse mode", "version_id"]


def run_live_du_only_eval(
    *,
    push_langfuse: bool = False,
    completion_fn: Callable[..., Any] | None = None,
) -> dict:
    """Run the live LLM through Data Understanding only, then stop."""
    completion_fn = completion_fn or _default_live_completion

    with EvalHarness(
        suite="du-only",
        log_prefix="live_du_only_eval_",
        tags=["eval", "copepod", "plan-mode", "live", "du-only"],
        mode="live-du-only",
        push_langfuse=push_langfuse,
        lf_file_hint=ECOTAXA.name,
    ) as ctx:
        upload = _stage_fixture(ctx.session_id, ECOTAXA)
        uploaded_ecotaxa_local, uploaded_ecotaxa_canonical = _uploaded_path_label(
            ctx.session_id, upload["filename"]
        )
        tool_impls = _live_tool_impls(ctx.tools, ctx.session_key)
        messages: list[dict] = [
            {"role": "system", "content": _build_eval_system_message(ctx.store, ctx.session_id)},
            {
                "role": "user",
                "content": (
                    f"J'ai chargé un export EcoTaxa de la campagne Green Edge. "
                    f"Chemin réel à utiliser pour `inspect_file` : `{uploaded_ecotaxa_local}`. "
                    f"Chemin canonique du projet : `{uploaded_ecotaxa_canonical}`. "
                    "Je veux explorer comment les organismes planctoniques se répartissent en profondeur. "
                    "Commence par analyser le fichier."
                ),
            },
        ]
        base_metadata = {
            "session_id": ctx.session_key,
            "tags": ctx.tags,
            "dataset": "copepod-plan-mode-v1",
        }

        ctx.log("--- PHASE 1: du-draft ---")
        du_span = ctx.trace.span(name="phase/du-draft", input={"phase": "data-understanding-draft"}) if ctx.trace else None
        first_reply = _run_llm_turn(
            messages=messages,
            tool_impls=tool_impls,
            model=ctx.model_name,
            completion_fn=completion_fn,
            metadata={**base_metadata, "phase": "du-draft", "lf_phase_span": du_span},
            log_fn=ctx.log,
        )
        du_versions = ctx.store.get_artifact_versions(ctx.session_key, "data_understanding")
        du_draft = du_versions[-1] if du_versions else None

        ctx.result(
            "live_du_only_created_data_understanding_draft",
            du_draft is not None and du_draft.get("status") == "draft",
            "LLM created a draft Data Understanding artifact during Phase 1.",
            {"case_type": "live", "model": ctx.model_name, "reply": first_reply[:500]},
        )
        ctx.result(
            "live_du_only_waited_for_data_understanding_confirmation",
            ctx.store.get_active_artifact(ctx.session_key, "data_understanding") is None
            and ctx.store.get_artifact_versions(ctx.session_key, "graph_context") == [],
            "LLM did not activate DU or create Graph Context before user confirmation.",
            {"case_type": "live", "model": ctx.model_name},
        )

        phase1_msgs = messages[2:]
        phase1_rounds = sum(1 for m in phase1_msgs if m.get("role") == "assistant")
        describe_calls = sum(
            1
            for m in phase1_msgs
            if m.get("role") == "assistant"
            for tc in (m.get("tool_calls") or [])
            if (_tool_call_to_dict(tc).get("function") or {}).get("name") == "describe_column"
        )
        unmatched_count = 0
        for m in phase1_msgs:
            if m.get("role") == "tool" and m.get("name") == "infer_column_roles":
                unmatched_count = len(json.loads(m.get("content", "{}")).get("unmatched_columns", []))
                break

        ctx.result(
            "live_du_only_phase1_efficient",
            phase1_rounds <= 10,
            f"Phase 1 completed in {phase1_rounds} rounds (limit: 10).",
            {"case_type": "edge", "rounds": phase1_rounds},
        )
        du_payload = (du_draft.get("payload") or {}) if du_draft else {}
        ctx.result(
            "live_du_only_payload_has_column_catalogue",
            bool(du_payload.get("column_catalogue")),
            f"DU artifact payload contains column_catalogue with {len(du_payload.get('column_catalogue') or [])} entries.",
            {"case_type": "edge"},
        )
        coverage_assessment = du_payload.get("coverage_assessment") or {}
        ctx.result(
            "live_du_only_payload_has_sufficient_coverage",
            coverage_assessment.get("status") == "sufficient",
            f"DU artifact coverage status is {coverage_assessment.get('status')!r}.",
            {"case_type": "edge", "coverage": coverage_assessment},
        )
        ctx.result(
            "live_du_only_describe_column_covered_all_unmatched",
            unmatched_count == 0 or describe_calls >= unmatched_count,
            f"describe_column called {describe_calls}× for {unmatched_count} unmatched columns.",
            {"case_type": "edge", "describe_calls": describe_calls, "unmatched_count": unmatched_count},
        )

        messages.append({"role": "user", "content": "Oui, c'est correct. Je confirme l'analyse du fichier."})
        if du_span is not None:
            du_span.end()

        ctx.log("--- PHASE 2: du-confirmation ---")
        confirm_span = ctx.trace.span(name="phase/du-confirmation", input={"phase": "du-confirmation"}) if ctx.trace else None
        second_reply = _run_llm_turn(
            messages=messages,
            tool_impls=tool_impls,
            model=ctx.model_name,
            completion_fn=completion_fn,
            metadata={**base_metadata, "phase": "du-confirmation", "lf_phase_span": confirm_span},
            log_fn=ctx.log,
        )
        active_du = ctx.store.get_active_artifact(ctx.session_key, "data_understanding")
        ctx.result(
            "live_du_only_activated_data_understanding",
            active_du is not None
            and du_draft is not None
            and active_du.get("version_id") == du_draft.get("version_id"),
            "LLM activated the confirmed Data Understanding.",
            {"case_type": "live", "model": ctx.model_name, "reply": second_reply[:500]},
        )
        ctx.result(
            "live_du_only_no_graph_context_created",
            ctx.store.get_artifact_versions(ctx.session_key, "graph_context") == [],
            "No Graph Context was created in DU-only mode.",
            {"case_type": "edge"},
        )

        all_llm_text = "\n".join([first_reply, second_reply]).lower()
        leaked = [t for t in _FORBIDDEN_USER_TERMS if t in all_llm_text]
        ctx.result(
            "live_du_only_no_internal_terms_in_llm_text",
            not leaked,
            "No forbidden downstream terms in LLM text." if not leaked
            else f"LLM leaked internal terms: {leaked}",
            {"case_type": "edge", "leaked": leaked},
        )

        if confirm_span is not None:
            confirm_span.end()

    return ctx.report
