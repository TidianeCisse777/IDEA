from __future__ import annotations

import json
from typing import Any, Callable

from core.chat_stream_events import chat_stream_events

from .fixtures import ECOTAXA, _stage_fixture, _uploaded_path_label
from .harness import EvalHarness, _plan_ready_allowed, _post_analyse
from .llm_driver import _default_live_completion, _live_tool_impls, _run_llm_turn, _tool_call_to_dict
from .system_messages import _build_eval_system_message

_FORBIDDEN_USER_TERMS = ["data understanding", "graph context", "version_id", "du-", "gc-"]


def run_live_eval(
    *,
    push_langfuse: bool = False,
    completion_fn: Callable[..., Any] | None = None,
) -> dict:
    """Run the full Plan Mode workflow with a real LLM (DU → GC → PLAN_READY)."""
    completion_fn = completion_fn or _default_live_completion

    with EvalHarness(
        suite="live",
        log_prefix="live_eval_",
        tags=["eval", "copepod", "plan-mode", "live"],
        mode="live",
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

        # --- Phase 1: Data Understanding draft ---
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
            "live_llm_created_data_understanding_draft",
            du_draft is not None and du_draft.get("status") == "draft",
            "LLM created a draft Data Understanding artifact during Phase 1.",
            {"case_type": "live", "model": ctx.model_name, "reply": first_reply[:500]},
        )
        ctx.result(
            "live_llm_waited_for_data_understanding_confirmation",
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
            "live_describe_column_covered_all_unmatched",
            describe_calls >= unmatched_count > 0,
            f"describe_column called {describe_calls}× for {unmatched_count} unmatched columns.",
            {"case_type": "edge", "describe_calls": describe_calls, "unmatched_count": unmatched_count},
        )
        ctx.result(
            "live_phase1_efficient",
            phase1_rounds <= 10,
            f"Phase 1 completed in {phase1_rounds} rounds (limit: 10).",
            {"case_type": "edge", "rounds": phase1_rounds},
        )
        du_payload = (du_draft.get("payload") or {}) if du_draft else {}
        ctx.result(
            "live_du_payload_has_column_catalogue",
            "column_catalogue" in du_payload and bool(du_payload["column_catalogue"]),
            f"DU artifact payload contains column_catalogue with {len(du_payload.get('column_catalogue') or [])} entries.",
            {"case_type": "edge"},
        )
        coverage_assessment = du_payload.get("coverage_assessment") or {}
        ctx.result(
            "live_du_payload_has_sufficient_coverage",
            coverage_assessment.get("status") == "sufficient",
            f"DU artifact coverage status is {coverage_assessment.get('status')!r}.",
            {"case_type": "edge", "coverage": coverage_assessment},
        )

        messages.append({
            "role": "user",
            "content": (
                "Oui, c'est correct. "
                "Je veux explorer la distribution verticale des organismes par profondeur. "
                "Vas-y pour la configuration du graphique."
            ),
        })
        if du_span is not None:
            du_span.end()

        # --- Phase 2: Graph Context draft ---
        ctx.log("--- PHASE 2: gc-draft ---")
        gc_span = ctx.trace.span(name="phase/gc-draft", input={"phase": "graph-context-draft"}) if ctx.trace else None
        second_reply = _run_llm_turn(
            messages=messages,
            tool_impls=tool_impls,
            model=ctx.model_name,
            completion_fn=completion_fn,
            metadata={**base_metadata, "phase": "gc-draft", "lf_phase_span": gc_span},
            log_fn=ctx.log,
        )
        active_du = ctx.store.get_active_artifact(ctx.session_key, "data_understanding")
        gc_versions = ctx.store.get_artifact_versions(ctx.session_key, "graph_context")
        gc_draft = gc_versions[-1] if gc_versions else None

        ctx.result(
            "live_llm_activated_data_understanding",
            active_du is not None and active_du.get("version_id") == du_draft.get("version_id") if du_draft else False,
            "LLM activated the confirmed Data Understanding.",
            {"case_type": "live", "model": ctx.model_name},
        )
        ctx.result(
            "live_llm_created_graph_context_draft_linked_to_active_du",
            active_du is not None
            and gc_draft is not None
            and gc_draft.get("status") == "draft"
            and gc_draft.get("payload", {}).get("data_understanding_version_id") == active_du.get("version_id"),
            "LLM created a Graph Context draft linked to active Data Understanding.",
            {"case_type": "live", "model": ctx.model_name, "reply": second_reply[:500]},
        )
        premature_events = list(chat_stream_events(
            [{"start": True, "end": True, "role": "assistant", "type": "message", "content": second_reply}],
            user_turns=3,
            session_mode="plan",
            plan_ready_allowed=_plan_ready_allowed(ctx.store, ctx.session_key),
        ))
        premature_button_emitted = any(event.get("type") == "action_button" for event in premature_events)
        premature_plan_ready_marker = "[PLAN_READY]" in second_reply

        ctx.result(
            "live_llm_did_not_emit_plan_ready_before_graph_context_confirmation",
            not premature_plan_ready_marker,
            "LLM text did not contain PLAN_READY before Graph Context confirmation.",
            {"case_type": "live", "model": ctx.model_name, "reply": second_reply[:500]},
        )
        ctx.result(
            "live_backend_blocked_premature_plan_ready_button",
            not premature_button_emitted,
            "Backend phase state prevented premature Analyse button exposure.",
            {"case_type": "live", "model": ctx.model_name},
        )
        ctx.result(
            "live_llm_waited_for_graph_context_confirmation",
            ctx.store.get_active_artifact(ctx.session_key, "graph_context") is None
            and not premature_button_emitted,
            "LLM did not activate GC or expose Analyse before graph context confirmation.",
            {"case_type": "live", "model": ctx.model_name},
        )
        gc_payload = (gc_draft.get("payload") or {}) if gc_draft else {}
        required_gc_fields = {
            "data_understanding_version_id", "objective", "columns", "filters",
            "units", "chart_type", "language", "output_artifacts", "feasibility", "blockers",
        }
        missing_gc_fields = required_gc_fields - gc_payload.keys()
        ctx.result(
            "live_gc_payload_has_all_required_fields",
            not missing_gc_fields,
            f"GC artifact has all required fields. Missing: {sorted(missing_gc_fields) or 'none'}.",
            {"case_type": "edge", "missing": sorted(missing_gc_fields)},
        )

        messages.append({"role": "user", "content": "Ok, c'est bon pour moi."})
        if gc_span is not None:
            gc_span.end()

        # --- Phase 3: PLAN_READY ---
        ctx.log("--- PHASE 3: plan-ready ---")
        pr_span = ctx.trace.span(name="phase/plan-ready", input={"phase": "plan-ready"}) if ctx.trace else None
        final_reply = _run_llm_turn(
            messages=messages,
            tool_impls=tool_impls,
            model=ctx.model_name,
            completion_fn=completion_fn,
            metadata={**base_metadata, "phase": "plan-ready", "lf_phase_span": pr_span},
            log_fn=ctx.log,
        )
        active_gc = ctx.store.get_active_artifact(ctx.session_key, "graph_context")
        stream_events = list(chat_stream_events(
            [{"start": True, "end": True, "role": "assistant", "type": "message", "content": final_reply}],
            user_turns=3,
            session_mode="plan",
            plan_ready_allowed=_plan_ready_allowed(ctx.store, ctx.session_key),
        ))
        analyse = _post_analyse(ctx.client, ctx.session_id)

        ctx.result(
            "live_llm_activated_graph_context",
            active_du is not None
            and active_gc is not None
            and active_gc.get("payload", {}).get("data_understanding_version_id") == active_du.get("version_id"),
            "LLM activated Graph Context linked to active Data Understanding.",
            {"case_type": "live", "model": ctx.model_name},
        )
        ctx.result(
            "live_plan_ready_enables_analyse_mode",
            any(event.get("type") == "action_button" for event in stream_events)
            and analyse.status_code == 200,
            f"PLAN_READY emitted Analyse button and /session/mode returned HTTP {analyse.status_code}.",
            {"case_type": "live", "model": ctx.model_name, "reply": final_reply[:500]},
        )

        all_llm_text = "\n".join([first_reply, second_reply, final_reply]).lower()
        leaked = [t for t in _FORBIDDEN_USER_TERMS if t in all_llm_text]
        ctx.result(
            "live_no_internal_terms_in_llm_text",
            not leaked,
            "No internal artifact terms in LLM text." if not leaked
            else f"LLM leaked internal terms: {leaked}",
            {"case_type": "live", "model": ctx.model_name, "leaked": leaked},
        )

        if pr_span is not None:
            pr_span.end()

    return ctx.report
