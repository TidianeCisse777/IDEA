from __future__ import annotations

import uuid

from core.chat_stream_events import chat_stream_events

from .fixtures import ECOTAXA, ECOPART, _data_understanding_artifact, _stage_fixture, _uploaded_path
from .harness import EvalHarness, _plan_ready_allowed, _post_analyse


def run_mock_eval(*, push_langfuse: bool = False) -> dict:
    """Deterministic Plan Mode workflow checks — no LLM required."""
    with EvalHarness(
        suite="mock",
        log_prefix="mock_eval_",
        tags=["eval", "copepod", "plan-mode", "mock"],
        mode="mock",
        push_langfuse=push_langfuse,
    ) as ctx:
        upload = _stage_fixture(ctx.session_id, ECOTAXA)
        uploaded_ecotaxa = _uploaded_path(ctx.session_id, upload["filename"])
        du_artifact = _data_understanding_artifact(ctx.tools, uploaded_ecotaxa)
        du_draft = ctx.tools["create_data_understanding_draft"](ctx.session_key, du_artifact)

        ctx.result(
            "upload_ecotaxa_creates_data_understanding",
            du_draft["status"] == "draft"
            and du_draft["payload"]["files"][0]["source_type_guess"]["value"] == "likely_ecotaxa",
            f"Data Understanding draft {du_draft['version_id']} created after upload.",
            {"case_type": "common", "version_id": du_draft["version_id"]},
        )
        du_coverage = (du_draft.get("payload") or {}).get("coverage_assessment") or {}
        ctx.result(
            "data_understanding_coverage_is_sufficient",
            du_coverage.get("status") == "sufficient",
            f"Data Understanding coverage status is {du_coverage.get('status')!r}.",
            {"case_type": "common", "coverage": du_coverage},
        )

        blocked = _post_analyse(ctx.client, ctx.session_id)
        ctx.result(
            "analyse_blocked_before_active_artifacts",
            blocked.status_code == 409,
            f"Analyse before active artifacts returned HTTP {blocked.status_code}.",
            {"case_type": "edge"},
        )

        missing_du_ref = ctx.tools["create_graph_context_draft"](
            ctx.session_key,
            {"objective": "Distribution verticale sans référence DU"},
        )
        ctx.result(
            "graph_context_without_data_understanding_version_is_blocked",
            missing_du_ref.get("created") is False
            and "data_understanding_version_id" in missing_du_ref.get("blocking_reason", ""),
            "Graph Context draft without DU version reference is rejected by the tool.",
            {"case_type": "edge"},
        )

        premature_gc = ctx.tools["create_graph_context_draft"](
            ctx.session_key,
            {
                "data_understanding_version_id": du_draft["version_id"],
                "objective": "Tentative de saut de validation",
                "columns": ["object_depth_min"],
                "filters": [],
                "units": {"depth": "m"},
                "chart_type": "static vertical distribution",
                "language": "Python",
                "output_artifacts": ["png"],
                "feasibility": "blocked",
                "blockers": ["Data Understanding not confirmed"],
            },
        )
        ctx.result(
            "phase_gate_blocks_graph_context_before_data_understanding_confirmation",
            premature_gc.get("created") is False
            and "graph_context_draft_required" in premature_gc.get("blocking_reason", ""),
            "Graph Context creation is rejected until Data Understanding has been activated.",
            {"case_type": "edge"},
        )

        early_plan_ready_events = list(chat_stream_events(
            [{"start": True, "end": True, "role": "assistant", "type": "message",
              "content": "Contexte scientifique validé trop tôt. [PLAN_READY]"}],
            user_turns=2,
            session_mode="plan",
            plan_ready_allowed=_plan_ready_allowed(ctx.store, ctx.session_key),
        ))
        ctx.result(
            "plan_ready_button_not_emitted_before_minimum_turns",
            not any(event.get("type") == "action_button" for event in early_plan_ready_events),
            "PLAN_READY marker before the minimum user turns does not emit the Analyse button.",
            {"case_type": "edge"},
        )

        premature_plan_ready_events = list(chat_stream_events(
            [{"start": True, "end": True, "role": "assistant", "type": "message",
              "content": "Contexte scientifique validé trop tôt. [PLAN_READY]"}],
            user_turns=3,
            session_mode="plan",
            plan_ready_allowed=_plan_ready_allowed(ctx.store, ctx.session_key),
        ))
        ctx.result(
            "backend_phase_gate_blocks_premature_plan_ready_button",
            not any(event.get("type") == "action_button" for event in premature_plan_ready_events),
            "Backend phase state prevents a premature PLAN_READY marker from exposing Analyse.",
            {"case_type": "edge"},
        )

        du_active = ctx.tools["activate_data_understanding"](ctx.session_key, du_draft["version_id"])
        ctx.result(
            "data_understanding_confirmation_activates_artifact",
            du_active.get("status") == "active"
            and ctx.tools["get_active_data_understanding"](ctx.session_key)["version_id"]
            == du_active["version_id"],
            f"Data Understanding active version is {du_active.get('version_id')}.",
            {"case_type": "common", "version_id": du_active.get("version_id")},
        )

        graph_context = {
            "data_understanding_version_id": du_active["version_id"],
            "objective": "Distribution verticale EcoTaxa",
            "columns": ["object_depth_min", "object_depth_max"],
            "filters": [],
            "units": {"depth": "m"},
            "chart_type": "static vertical distribution",
            "language": "Python",
            "output_artifacts": ["png", "metadata"],
            "feasibility": "exploratory",
            "blockers": [],
        }
        gc_draft = ctx.tools["create_graph_context_draft"](ctx.session_key, graph_context)
        ctx.result(
            "graph_context_draft_links_to_active_du",
            gc_draft["status"] == "draft"
            and gc_draft["payload"]["data_understanding_version_id"] == du_active["version_id"],
            f"Graph Context draft {gc_draft['version_id']} references active DU.",
            {"case_type": "common", "version_id": gc_draft["version_id"]},
        )

        gc_active = ctx.tools["activate_graph_context"](ctx.session_key, gc_draft["version_id"])
        stream_events = list(chat_stream_events(
            [{"start": True, "end": True, "role": "assistant", "type": "message",
              "content": "Contexte scientifique validé. [PLAN_READY]"}],
            user_turns=3,
            session_mode="plan",
            plan_ready_allowed=_plan_ready_allowed(ctx.store, ctx.session_key),
        ))
        analyse = _post_analyse(ctx.client, ctx.session_id)
        ctx.result(
            "plan_ready_after_graph_context_activation",
            gc_active.get("status") == "active"
            and stream_events[-1].get("label") == "Passer en Mode Analyse"
            and analyse.status_code == 200,
            f"Graph Context active, PLAN_READY button emitted, analyse returned HTTP {analyse.status_code}.",
            {"case_type": "common", "version_id": gc_active.get("version_id")},
        )

        upload_ecopart = _stage_fixture(ctx.session_id, ECOPART)
        uploaded_ecopart = _uploaded_path(ctx.session_id, upload_ecopart["filename"])
        new_du_draft = ctx.tools["create_data_understanding_draft"](
            ctx.session_key,
            _data_understanding_artifact(ctx.tools, uploaded_ecopart),
        )
        active_du_after_upload = ctx.tools["get_active_data_understanding"](ctx.session_key)
        active_gc_after_upload = ctx.tools["get_active_graph_context"](ctx.session_key)
        ctx.result(
            "upload_in_analyse_creates_draft_without_replan",
            new_du_draft["status"] == "draft"
            and active_du_after_upload["version_id"] == du_active["version_id"]
            and active_gc_after_upload["version_id"] == gc_active["version_id"],
            "Upload in Analyse created a new DU draft without changing active DU or GC.",
            {"case_type": "common", "new_draft_version_id": new_du_draft["version_id"]},
        )

        mismatch_session_id = f"eval-edge-{uuid.uuid4().hex[:8]}"
        mismatch_session_key = f"eval-user:{mismatch_session_id}:copepod"
        old_du = ctx.store.create_artifact_version(
            mismatch_session_key, "data_understanding",
            {"files": [{"original_filename": "old.tsv"}]},
        )
        current_du = ctx.store.create_artifact_version(
            mismatch_session_key, "data_understanding",
            {"files": [{"original_filename": "current.tsv"}]},
        )
        stale_gc = ctx.store.create_artifact_version(
            mismatch_session_key, "graph_context",
            {"data_understanding_version_id": old_du["version_id"]},
        )
        ctx.store.activate_artifact_version(mismatch_session_key, "data_understanding", current_du["version_id"])
        ctx.store.activate_artifact_version(mismatch_session_key, "graph_context", stale_gc["version_id"])
        mismatch_response = _post_analyse(ctx.client, mismatch_session_id)
        ctx.result(
            "analyse_blocked_when_graph_context_references_stale_data_understanding",
            mismatch_response.status_code == 409,
            f"Stale Graph Context linkage returned HTTP {mismatch_response.status_code}.",
            {"case_type": "edge"},
        )

        generic_debug = ctx.client.get(
            "/session/artifacts/data-understanding",
            headers={"x-session-id": ctx.session_id, "x-agent-type": "generic"},
        )
        ctx.result(
            "artifact_debug_routes_are_copepod_only",
            generic_debug.status_code == 404,
            f"Generic agent artifact debug route returned HTTP {generic_debug.status_code}.",
            {"case_type": "edge"},
        )

    return ctx.report
