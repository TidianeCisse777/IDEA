from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .fixtures import (
    AMUNDSEN_CTD,
    BIO_ORACLE,
    ECOTAXA,
    ECOPART,
    NEOLABS_LOKI,
    NEOLABS_TAXON,
    OGSL,
    _stage_fixture,
    _uploaded_path_label,
)
from .harness import EvalHarness
from .llm_driver import (
    _default_live_completion,
    _live_tool_impls,
    _run_llm_turn,
    _tool_call_to_dict,
)
from .system_messages import _build_eval_system_message

_FORBIDDEN_USER_TERMS = ["graph context", "plan_ready", "analyse mode", "version_id"]

_GLOBAL_REQUIRED_FIELDS = ["possible_joins", "complementarity", "temporal_coverage", "spatial_coverage"]


@dataclass
class DuMultiScenario:
    """Declares expected LLM behaviour for one multi-file Data Understanding eval scenario.

    The assertion engine in run_live_du_multi_eval reads these fields to generate
    checks — adding a scenario means adding one entry to _DU_MULTI_SCENARIOS only.
    """
    slug: str
    label: str
    fixture_paths: list[Path]
    user_message: str
    # Expected artifact outcomes
    expect_joins: bool = False           # possible_joins should be non-empty
    expect_temporal_spatial: bool = False  # temporal/spatial coverage should not be "non applicable"


_DU_MULTI_SCENARIOS: list[DuMultiScenario] = [
    DuMultiScenario(
        slug="ecotaxa_ecopart",
        label="EcoTaxa + EcoPart",
        fixture_paths=[ECOTAXA, ECOPART],
        user_message=(
            "J'ai chargé deux fichiers de la campagne Green Edge : un export EcoTaxa "
            "(objets individuels classifiés) et un export EcoPart UVP5 (profils de particules). "
            "Je veux comprendre la répartition verticale des copépodes. "
            "Commence par analyser les deux fichiers."
        ),
        expect_joins=True,
        expect_temporal_spatial=True,
    ),
    DuMultiScenario(
        slug="ecotaxa_amundsen",
        label="EcoTaxa + CTD Amundsen",
        fixture_paths=[ECOTAXA, AMUNDSEN_CTD],
        user_message=(
            "J'ai chargé deux fichiers : un export EcoTaxa de la campagne Green Edge "
            "et des mesures CTD de la mission Amundsen 2018. "
            "Je veux coupler les abondances de copépodes avec les profils physico-chimiques. "
            "Commence par analyser les deux fichiers."
        ),
        expect_joins=True,
        expect_temporal_spatial=False,
    ),
    DuMultiScenario(
        slug="ecotaxa_neolabs",
        label="EcoTaxa + NeoLabs taxon",
        fixture_paths=[ECOTAXA, NEOLABS_TAXON],
        user_message=(
            "J'ai chargé deux fichiers : un export EcoTaxa de la campagne Green Edge "
            "et des données de comptages taxonomiques du laboratoire NeoLabs. "
            "Je veux comparer les abondances issues des deux méthodes. "
            "Commence par analyser les deux fichiers."
        ),
        expect_joins=False,
        expect_temporal_spatial=False,
    ),
    DuMultiScenario(
        slug="ecotaxa_bio_oracle",
        label="EcoTaxa + Bio-Oracle",
        fixture_paths=[ECOTAXA, BIO_ORACLE],
        user_message=(
            "J'ai chargé deux fichiers : un export EcoTaxa de la campagne Green Edge "
            "et un extrait Bio-Oracle avec la concentration en silicates (SSP126, 2020). "
            "Je veux explorer l'influence des conditions environnementales sur la distribution "
            "des copépodes. Commence par analyser les deux fichiers."
        ),
        expect_joins=False,
        expect_temporal_spatial=True,
    ),
    DuMultiScenario(
        slug="ecotaxa_ogsl",
        label="EcoTaxa + OGSL CTD",
        fixture_paths=[ECOTAXA, OGSL],
        user_message=(
            "J'ai chargé deux fichiers : un export EcoTaxa de la campagne Green Edge "
            "et des profils CTD de biodiversité OGSL 2024 (température, salinité, oxygène, fluorescence). "
            "Je veux coupler les abondances de copépodes avec les variables physico-chimiques. "
            "Commence par analyser les deux fichiers."
        ),
        expect_joins=False,
        expect_temporal_spatial=True,
    ),
    DuMultiScenario(
        slug="neolabs_loki_taxon",
        label="NeoLabs LOKI profils + NeoLabs taxon",
        fixture_paths=[NEOLABS_LOKI, NEOLABS_TAXON],
        user_message=(
            "J'ai chargé deux fichiers du laboratoire NeoLabs : les métadonnées de déploiement "
            "LOKI (profils, stations, dates de collecte) et les comptages taxonomiques de zooplancton. "
            "Je veux analyser les abondances par profil de déploiement. "
            "Commence par analyser les deux fichiers."
        ),
        expect_joins=True,
        expect_temporal_spatial=True,
    ),
]


def run_live_du_multi_eval(
    *,
    push_langfuse: bool = False,
    completion_fn: Callable[..., Any] | None = None,
    scenario_slugs: list[str] | None = None,
) -> dict:
    """Run the live LLM through multi-file Data Understanding, one scenario at a time."""
    completion_fn = completion_fn or _default_live_completion

    scenarios = _DU_MULTI_SCENARIOS
    if scenario_slugs:
        wanted = {slug.strip() for slug in scenario_slugs if slug.strip()}
        scenarios = [s for s in _DU_MULTI_SCENARIOS if s.slug in wanted]
        if not scenarios:
            available = [s.slug for s in _DU_MULTI_SCENARIOS]
            raise ValueError(
                f"No DU-multi scenarios matched {sorted(wanted)!r}. "
                f"Available: {available}."
            )

    with EvalHarness(
        suite="du-multi",
        log_prefix="live_du_multi_eval_",
        tags=["eval", "copepod", "plan-mode", "live", "du-multi"],
        mode="live-du-multi",
        push_langfuse=push_langfuse,
        lf_file_hint="multi-file",
    ) as ctx:
        ctx.log(f"    scenarios={[s.slug for s in scenarios]}\n")

        def _run_scenario(scenario: DuMultiScenario, session_id: str, session_key: str) -> dict[str, Any]:
            # Stage all fixtures and build file path entries for the user message
            path_lines: list[str] = []
            for fixture in scenario.fixture_paths:
                upload = _stage_fixture(session_id, fixture)
                local_path, canonical_path = _uploaded_path_label(session_id, upload["filename"])
                path_lines.append(
                    f"  - Fichier : `{fixture.name}`\n"
                    f"    Chemin local (pour `inspect_file`) : `{local_path}`\n"
                    f"    Chemin canonique : `{canonical_path}`"
                )

            full_user_message = (
                scenario.user_message
                + "\n\nFichiers chargés :\n"
                + "\n".join(path_lines)
            )

            tool_impls = _live_tool_impls(ctx.tools, session_key)
            messages: list[dict] = [
                {
                    "role": "system",
                    "content": _build_eval_system_message(ctx.store, session_id),
                },
                {"role": "user", "content": full_user_message},
            ]
            base_metadata = {
                "session_id": session_key,
                "tags": ctx.tags + [scenario.slug],
                "dataset": "copepod-plan-mode-v1",
                "scenario": scenario.slug,
            }

            ctx.log(f"--- SCENARIO: {scenario.slug} — Phase 1 (DU draft) ---")
            span = ctx.trace.span(name=f"phase/du-multi/{scenario.slug}/phase1", input={"phase": "du-draft"}) if ctx.trace else None
            phase1_reply = _run_llm_turn(
                messages=messages,
                tool_impls=tool_impls,
                model=ctx.model_name,
                completion_fn=completion_fn,
                metadata={**base_metadata, "phase": "du-draft", "lf_phase_span": span},
                log_fn=ctx.log,
            )
            if span is not None:
                span.end()

            du_versions = ctx.store.get_artifact_versions(session_key, "data_understanding")
            du_draft = du_versions[-1] if du_versions else None
            active_du_before_confirm = ctx.store.get_active_artifact(session_key, "data_understanding")

            confirm_index = len(messages)
            messages.append({"role": "user", "content": "Oui, c'est correct. Je confirme l'analyse des fichiers."})

            ctx.log(f"--- SCENARIO: {scenario.slug} — Phase 2 (confirmation) ---")
            confirm_span = ctx.trace.span(name=f"phase/du-multi/{scenario.slug}/phase2", input={"phase": "du-confirm"}) if ctx.trace else None
            confirm_reply = _run_llm_turn(
                messages=messages,
                tool_impls=tool_impls,
                model=ctx.model_name,
                completion_fn=completion_fn,
                metadata={**base_metadata, "phase": "du-confirm", "lf_phase_span": confirm_span},
                log_fn=ctx.log,
            )
            if confirm_span is not None:
                confirm_span.end()

            active_du = ctx.store.get_active_artifact(session_key, "data_understanding")
            post_confirm_msgs = messages[confirm_index + 1:]

            return {
                "session_key": session_key,
                "phase1_messages": messages[2:confirm_index],
                "post_confirm_messages": post_confirm_msgs,
                "phase1_reply": phase1_reply,
                "confirm_reply": confirm_reply,
                "du_draft": du_draft,
                "active_du_before_confirm": active_du_before_confirm,
                "active_du": active_du,
            }

        # ── run all scenarios, then assert ────────────────────────────────────
        scenario_states: list[tuple[DuMultiScenario, dict]] = []
        for scenario in scenarios:
            sub_session_id = f"{ctx.session_id}-{scenario.slug}"
            sub_session_key = f"eval-user:{sub_session_id}:copepod"
            state = _run_scenario(scenario, sub_session_id, sub_session_key)
            scenario_states.append((scenario, state))

            slug = scenario.slug
            n_files = len(scenario.fixture_paths)
            phase1_msgs = state["phase1_messages"]
            post_confirm_msgs = state["post_confirm_messages"]
            du_draft = state["du_draft"]
            du_payload = (du_draft.get("payload") or {}) if du_draft else {}

            # ── protocol: inspect_file called N times ─────────────────────────
            inspect_calls = [
                m for m in phase1_msgs
                if m.get("role") == "tool" and m.get("name") == "inspect_file"
            ]
            ctx.result(
                f"du_multi_{slug}_inspect_called_for_each_file",
                len(inspect_calls) == n_files,
                f"inspect_file called {len(inspect_calls)}× for {n_files} files.",
                {"case_type": "common", "scenario": slug, "inspect_count": len(inspect_calls), "expected": n_files},
            )

            # ── protocol: summarize_understanding called N times ──────────────
            summarize_calls = [
                m for m in phase1_msgs
                if m.get("role") == "tool" and m.get("name") == "summarize_understanding"
            ]
            ctx.result(
                f"du_multi_{slug}_summarize_called_for_each_file",
                len(summarize_calls) == n_files,
                f"summarize_understanding called {len(summarize_calls)}× for {n_files} files.",
                {"case_type": "common", "scenario": slug, "summarize_count": len(summarize_calls), "expected": n_files},
            )

            # ── protocol: synthesize_file_understanding called ────────────────
            synthesize_calls = [
                m for m in phase1_msgs
                if m.get("role") == "tool" and m.get("name") == "synthesize_file_understanding"
            ]
            ctx.result(
                f"du_multi_{slug}_synthesize_called",
                len(synthesize_calls) >= 1,
                f"synthesize_file_understanding called {len(synthesize_calls)}× (expected ≥1).",
                {"case_type": "common", "scenario": slug, "synthesize_count": len(synthesize_calls)},
            )

            # ── protocol: create_data_understanding_draft called ─────────────
            # Read status from the phase-1 tool message, before phase-2 activation changes it.
            _draft_tool_msg = next(
                (m for m in phase1_msgs
                 if m.get("role") == "tool" and m.get("name") == "create_data_understanding_draft"),
                None,
            )
            _draft_status_at_creation = None
            if _draft_tool_msg:
                try:
                    _draft_status_at_creation = json.loads(_draft_tool_msg.get("content", "{}")).get("status")
                except Exception:
                    pass
            ctx.result(
                f"du_multi_{slug}_draft_created",
                _draft_status_at_creation == "draft",
                f"create_data_understanding_draft returned status={_draft_status_at_creation!r} at creation time (expected 'draft').",
                {"case_type": "common", "scenario": slug},
            )

            # ── protocol: no PLAN_READY before confirmation ───────────────────
            plan_ready_in_phase1 = any(
                "[PLAN_READY]" in (m.get("content") or "")
                for m in phase1_msgs if m.get("role") == "assistant"
            )
            ctx.result(
                f"du_multi_{slug}_no_plan_ready_before_confirmation",
                not plan_ready_in_phase1,
                "[PLAN_READY] not emitted before user confirmation." if not plan_ready_in_phase1
                else "LLM emitted [PLAN_READY] prematurely in Phase 1.",
                {"case_type": "edge", "scenario": slug},
            )

            # ── artifact: payload has N files[] entries ───────────────────────
            payload_files = du_payload.get("files") or []
            ctx.result(
                f"du_multi_{slug}_payload_has_n_files",
                len(payload_files) == n_files,
                f"DU payload has {len(payload_files)} files[] entries (expected {n_files}).",
                {"case_type": "common", "scenario": slug, "file_count": len(payload_files), "expected": n_files},
            )

            # ── artifact: global block has all required fields ─────────────────
            global_block = du_payload.get("global") or {}
            missing_global = [f for f in _GLOBAL_REQUIRED_FIELDS if f not in global_block]
            ctx.result(
                f"du_multi_{slug}_global_block_complete",
                not missing_global,
                f"global block has all required fields." if not missing_global
                else f"global block missing: {missing_global}",
                {"case_type": "common", "scenario": slug, "missing": missing_global, "global_keys": list(global_block.keys())},
            )

            # ── artifact: possible_joins non-empty when expected ──────────────
            if scenario.expect_joins:
                possible_joins = global_block.get("possible_joins") or []
                ctx.result(
                    f"du_multi_{slug}_possible_joins_non_empty",
                    bool(possible_joins),
                    f"possible_joins has {len(possible_joins)} entries." if possible_joins
                    else "possible_joins is empty — LLM did not detect any join.",
                    {"case_type": "common", "scenario": slug, "joins": possible_joins},
                )

            # ── artifact: temporal/spatial coverage set when expected ──────────
            if scenario.expect_temporal_spatial:
                temporal = global_block.get("temporal_coverage") or ""
                spatial = global_block.get("spatial_coverage") or ""
                ctx.result(
                    f"du_multi_{slug}_temporal_coverage_set",
                    bool(temporal) and temporal.strip().lower() != "non applicable",
                    f"temporal_coverage={temporal!r}",
                    {"case_type": "edge", "scenario": slug, "temporal_coverage": temporal},
                )
                ctx.result(
                    f"du_multi_{slug}_spatial_coverage_set",
                    bool(spatial) and spatial.strip().lower() != "non applicable",
                    f"spatial_coverage={spatial!r}",
                    {"case_type": "edge", "scenario": slug, "spatial_coverage": spatial},
                )

            # ── artifact: merged column_catalogue present and non-empty ───────
            column_catalogue = du_payload.get("column_catalogue") or []
            ctx.result(
                f"du_multi_{slug}_merged_column_catalogue_present",
                bool(column_catalogue),
                f"column_catalogue has {len(column_catalogue)} entries.",
                {"case_type": "common", "scenario": slug, "catalogue_size": len(column_catalogue)},
            )

            # ── no DU activated before confirmation ───────────────────────────
            ctx.result(
                f"du_multi_{slug}_no_activation_before_confirmation",
                state["active_du_before_confirm"] is None,
                "DU not activated before user confirmation.",
                {"case_type": "edge", "scenario": slug},
            )

            # ── confirmation: DU activated after confirmation ─────────────────
            ctx.result(
                f"du_multi_{slug}_activated_after_confirmation",
                state["active_du"] is not None
                and du_draft is not None
                and (state["active_du"].get("version_id") == du_draft.get("version_id")),
                "LLM activated the confirmed Data Understanding.",
                {"case_type": "common", "scenario": slug},
            )

            # ── confirmation: first tool after confirmation = activate_data_understanding ──
            _first_tool_after_confirm: str | None = None
            for _m in post_confirm_msgs:
                if _m.get("role") == "assistant":
                    for _tc in (_m.get("tool_calls") or []):
                        _call = _tool_call_to_dict(_tc)
                        _name = (_call.get("function") or {}).get("name")
                        if _name:
                            _first_tool_after_confirm = _name
                            break
                if _first_tool_after_confirm:
                    break
            ctx.result(
                f"du_multi_{slug}_first_tool_after_confirmation_is_activate",
                _first_tool_after_confirm == "activate_data_understanding",
                f"First tool after confirmation was {_first_tool_after_confirm!r} (expected activate_data_understanding).",
                {"case_type": "common", "scenario": slug, "first_tool": _first_tool_after_confirm},
            )

        # ── cross-scenario: no internal terms leaked ──────────────────────────
        all_llm_text = "\n".join(
            "\n".join([state["phase1_reply"], state["confirm_reply"]])
            for _, state in scenario_states
        ).lower()
        leaked = [t for t in _FORBIDDEN_USER_TERMS if t in all_llm_text]
        ctx.result(
            "du_multi_no_internal_terms_in_llm_text",
            not leaked,
            "No forbidden downstream terms in LLM text." if not leaked
            else f"LLM leaked internal terms: {leaked}",
            {"case_type": "edge", "leaked": leaked},
        )

    return ctx.report
