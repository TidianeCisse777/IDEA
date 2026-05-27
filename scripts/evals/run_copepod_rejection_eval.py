from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_EVALS_DIR = Path(__file__).resolve().parent
if str(_EVALS_DIR) not in sys.path:
    sys.path.insert(0, str(_EVALS_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from run_copepod_plan_mode_eval import (
    _configure_local_langfuse_host,
    _load_tools,
    _test_client,
    _upload_fixture,
    _uploaded_path,
    _tool_specs,
    _live_tool_impls,
    _run_llm_turn,
    _default_live_completion,
    _make_eval_trace,
    _close_eval_trace,
    _result,
    _json_dumps,
    _message_to_dict,
    _tool_call_to_dict,
    _completion_message,
    _compact_tool_result,
    _live_eval_system_prompt,
    _live_eval_runtime_context,
    _data_understanding_artifact,
    ECOTAXA,
    DATASET_NAME,
)

from core.config import settings
from core.session_store import InMemorySessionStore


TRACE_NAME = "copepod-eval/rejection"
TAGS = ["eval", "copepod", "rejection", "live"]


def _minimal_gc_artifact(du_version_id: str) -> dict:
    return {
        "data_understanding_version_id": du_version_id,
        "objective": "Distribution verticale EcoTaxa",
        "columns": ["object_depth_min", "object_depth_max"],
        "filters": [],
        "units": {"depth": "m"},
        "chart_type": "static vertical distribution",
        "language": "Python",
        "output_artifacts": ["png"],
        "feasibility": "exploratory",
        "blockers": [],
    }


def _synthetic_history_post_plan_ready(
    session_id: str,
    du_version_id: str,
    gc_version_id: str,
) -> list[dict]:
    runtime_context = _live_eval_runtime_context(session_id)
    return [
        {"role": "system", "content": _live_eval_system_prompt()},
        {"role": "system", "content": runtime_context},
        {
            "role": "user",
            "content": "Fichier chargé: `ecotaxa_sample_50.tsv`. Objectif: distribution verticale Python PNG.",
        },
        {
            "role": "assistant",
            "content": "J'ai inspecté le fichier et créé le Data Understanding draft. Voici le résumé...",
        },
        {"role": "user", "content": "Ouais ça m'a l'air bien. Vas-y pour la suite."},
        {
            "role": "assistant",
            "content": f"J'ai activé le Data Understanding (version {du_version_id}) et créé le Graph Context draft.",
        },
        {"role": "user", "content": "Ok, c'est bon pour moi."},
        {
            "role": "assistant",
            "content": f"J'ai activé le Graph Context (version {gc_version_id}). Le contexte scientifique est validé.\n\n[PLAN_READY]",
        },
    ]


def run_rejection_eval(
    *,
    push_langfuse: bool = False,
    completion_fn: Callable[..., Any] | None = None,
) -> dict:
    store = InMemorySessionStore()
    tools = _load_tools()
    model_name = settings.LLM_MODEL
    completion_fn = completion_fn or _default_live_completion
    results: list[dict] = []

    run_id = uuid.uuid4().hex[:10]
    # Session key shared by the trace so all scenarios appear in the same Langfuse session.
    trace_session_key = f"eval-user:rejection-{run_id}:copepod"

    lf, eval_trace = None, None
    if push_langfuse:
        try:
            from langfuse import Langfuse
            _configure_local_langfuse_host()
            lf = Langfuse()
            eval_trace = lf.trace(
                name=TRACE_NAME,
                user_id="eval-user",
                session_id=trace_session_key,
                tags=TAGS,
                input={"model": model_name, "file": ECOTAXA.name},
            )
        except Exception:
            pass

    log_dir = ROOT / "logs" / "evals"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"rejection_eval_{run_id}.log"

    with open(log_path, "w", encoding="utf-8") as log_fh:
        log_fh.write(f"=== REJECTION EVAL {run_id} model={model_name} ===\n\n")
        log_fh.flush()
        try:
            # ----------------------------------------------------------------
            # Scenario A-DU — Explicit DU rejection
            # ----------------------------------------------------------------
            session_id_adu = f"reject-adu-{uuid.uuid4().hex[:8]}"
            session_key_adu = f"eval-user:{session_id_adu}:copepod"
            tool_impls_adu = _live_tool_impls(tools, session_key_adu)
            base_adu = {"session_id": session_key_adu, "tags": TAGS, "dataset": DATASET_NAME}

            client_adu, stack_adu = _test_client(store)
            with stack_adu:
                upload_adu = _upload_fixture(client_adu, session_id_adu, ECOTAXA)
                uploaded_adu = _uploaded_path(session_id_adu, upload_adu["filename"])
                messages_adu: list[dict] = [
                    {"role": "system", "content": _live_eval_system_prompt()},
                    {"role": "system", "content": _live_eval_runtime_context(session_id_adu)},
                    {
                        "role": "user",
                        "content": (
                            f"Fichier chargé: `{uploaded_adu}`. Objectif final: produire une distribution "
                            "verticale EcoTaxa en Python, en PNG, avec profondeur en metres. Commence par la "
                            "Phase 1. Tu dois appeler les outils maintenant avant de répondre."
                        ),
                    },
                ]

                log_fh.write("--- SCENARIO A-DU: du-rejection ---\n")
                log_fh.flush()
                span_adu = eval_trace.span(name="scenario/du-rejection", input={"scenario": "A-DU"}) if eval_trace else None
                _run_llm_turn(
                    messages=messages_adu,
                    tool_impls=tool_impls_adu,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_adu, "phase": "scenario-ADU-phase1", "lf_phase_span": span_adu},
                    log_fh=log_fh,
                )

                messages_adu.append(
                    {
                        "role": "user",
                        "content": (
                            "Non, ce n'est pas correct. "
                            "La colonne object_depth_min est mal catégorisée. Refais l'analyse du fichier complètement."
                        ),
                    }
                )

                _run_llm_turn(
                    messages=messages_adu,
                    tool_impls=tool_impls_adu,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_adu, "phase": "scenario-ADU-rejection", "lf_phase_span": span_adu},
                    log_fh=log_fh,
                )
                if span_adu is not None:
                    span_adu.end()

            du_versions_adu = store.get_artifact_versions(session_key_adu, "data_understanding")
            active_du_adu = store.get_active_artifact(session_key_adu, "data_understanding")
            results.append(_result(
                "live_llm_creates_new_du_draft_on_rejection",
                len(du_versions_adu) >= 2 and active_du_adu is None,
                (
                    f"DU versions={len(du_versions_adu)} (need >=2), "
                    f"active_du={'None (correct)' if active_du_adu is None else 'SET (wrong)'}."
                ),
                {"case_type": "live", "model": model_name, "du_version_count": len(du_versions_adu)},
            ))

            # ----------------------------------------------------------------
            # Scenario A-GC — Explicit GC rejection (2 real LLM phases)
            # ----------------------------------------------------------------
            session_id_agc = f"reject-agc-{uuid.uuid4().hex[:8]}"
            session_key_agc = f"eval-user:{session_id_agc}:copepod"
            tool_impls_agc = _live_tool_impls(tools, session_key_agc)
            base_agc = {"session_id": session_key_agc, "tags": TAGS, "dataset": DATASET_NAME}

            client_agc, stack_agc = _test_client(store)
            with stack_agc:
                upload_agc = _upload_fixture(client_agc, session_id_agc, ECOTAXA)
                uploaded_agc = _uploaded_path(session_id_agc, upload_agc["filename"])
                messages_agc: list[dict] = [
                    {"role": "system", "content": _live_eval_system_prompt()},
                    {"role": "system", "content": _live_eval_runtime_context(session_id_agc)},
                    {
                        "role": "user",
                        "content": (
                            f"Fichier chargé: `{uploaded_agc}`. Objectif final: produire une distribution "
                            "verticale EcoTaxa en Python, en PNG, avec profondeur en metres. Commence par la "
                            "Phase 1. Tu dois appeler les outils maintenant avant de répondre."
                        ),
                    },
                ]

                log_fh.write("--- SCENARIO A-GC: gc-rejection (phase 1) ---\n")
                log_fh.flush()
                span_agc = eval_trace.span(name="scenario/gc-rejection", input={"scenario": "A-GC"}) if eval_trace else None
                _run_llm_turn(
                    messages=messages_agc,
                    tool_impls=tool_impls_agc,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_agc, "phase": "scenario-AGC-phase1", "lf_phase_span": span_agc},
                    log_fh=log_fh,
                )

                messages_agc.append(
                    {"role": "user", "content": "Ouais ça m'a l'air bien, vas-y pour la suite."}
                )

                log_fh.write("--- SCENARIO A-GC: gc-rejection (phase 2) ---\n")
                log_fh.flush()
                _run_llm_turn(
                    messages=messages_agc,
                    tool_impls=tool_impls_agc,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_agc, "phase": "scenario-AGC-phase2", "lf_phase_span": span_agc},
                    log_fh=log_fh,
                )

                du_active_agc = store.get_active_artifact(session_key_agc, "data_understanding")
                du_active_version_id_agc = du_active_agc["version_id"] if du_active_agc else None

                messages_agc.append(
                    {
                        "role": "user",
                        "content": (
                            "Non, ça ne convient pas. "
                            "Il manque les colonnes taxonomiques. "
                            "Refais la configuration du graphique en incluant les colonnes de classification."
                        ),
                    }
                )

                log_fh.write("--- SCENARIO A-GC: gc-rejection (rejection turn) ---\n")
                log_fh.flush()
                _run_llm_turn(
                    messages=messages_agc,
                    tool_impls=tool_impls_agc,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_agc, "phase": "scenario-AGC-rejection", "lf_phase_span": span_agc},
                    log_fh=log_fh,
                )
                if span_agc is not None:
                    span_agc.end()

            gc_versions_agc = store.get_artifact_versions(session_key_agc, "graph_context")
            active_gc_agc = store.get_active_artifact(session_key_agc, "graph_context")
            du_still_active_agc = store.get_active_artifact(session_key_agc, "data_understanding")
            du_unchanged = (
                du_still_active_agc is not None
                and du_active_version_id_agc is not None
                and du_still_active_agc["version_id"] == du_active_version_id_agc
            )
            results.append(_result(
                "live_llm_creates_new_gc_draft_on_rejection",
                len(gc_versions_agc) >= 2 and active_gc_agc is None and du_unchanged,
                (
                    f"GC versions={len(gc_versions_agc)} (need >=2), "
                    f"active_gc={'None (correct)' if active_gc_agc is None else 'SET (wrong)'}, "
                    f"du_unchanged={'yes' if du_unchanged else 'NO'}."
                ),
                {
                    "case_type": "live",
                    "model": model_name,
                    "gc_version_count": len(gc_versions_agc),
                    "du_active_version_id": du_active_version_id_agc,
                },
            ))

            # ----------------------------------------------------------------
            # Scenario C-DU — DU retraction after PLAN_READY (programmatic setup)
            # ----------------------------------------------------------------
            session_id_cdu = f"retract-cdu-{uuid.uuid4().hex[:8]}"
            session_key_cdu = f"eval-user:{session_id_cdu}:copepod"
            tool_impls_cdu = _live_tool_impls(tools, session_key_cdu)
            base_cdu = {"session_id": session_key_cdu, "tags": TAGS, "dataset": DATASET_NAME}

            # _data_understanding_artifact only reads the file — no store access.
            du_artifact = _data_understanding_artifact(tools, ECOTAXA)

            client_cdu, stack_cdu = _test_client(store)
            with stack_cdu:
                du_cdu = tools["create_data_understanding_draft"](session_key_cdu, du_artifact)
                tools["activate_data_understanding"](session_key_cdu, du_cdu["version_id"])
                du_active_version_id_cdu = du_cdu["version_id"]

                gc_cdu = tools["create_graph_context_draft"](
                    session_key_cdu, _minimal_gc_artifact(du_active_version_id_cdu)
                )
                tools["activate_graph_context"](session_key_cdu, gc_cdu["version_id"])
                gc_active_version_id_cdu = gc_cdu["version_id"]

                messages_cdu = _synthetic_history_post_plan_ready(
                    session_id_cdu, du_active_version_id_cdu, gc_active_version_id_cdu
                )
                messages_cdu.append(
                    {
                        "role": "user",
                        "content": (
                            "Finalement, je veux revoir l'analyse du fichier. "
                            "Il y a une erreur dans l'interprétation des colonnes."
                        ),
                    }
                )

                log_fh.write("--- SCENARIO C-DU: du-retraction ---\n")
                log_fh.flush()
                span_cdu = eval_trace.span(name="scenario/du-retraction", input={"scenario": "C-DU"}) if eval_trace else None
                _run_llm_turn(
                    messages=messages_cdu,
                    tool_impls=tool_impls_cdu,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_cdu, "phase": "scenario-CDU-retraction", "lf_phase_span": span_cdu},
                    log_fh=log_fh,
                )
                if span_cdu is not None:
                    span_cdu.end()

            du_versions_cdu = store.get_artifact_versions(session_key_cdu, "data_understanding")
            active_du_cdu = store.get_active_artifact(session_key_cdu, "data_understanding")
            active_gc_cdu = store.get_active_artifact(session_key_cdu, "graph_context")
            du_active_unchanged_cdu = (
                active_du_cdu is not None
                and active_du_cdu["version_id"] == du_active_version_id_cdu
            )
            gc_active_unchanged_cdu = (
                active_gc_cdu is not None
                and active_gc_cdu["version_id"] == gc_active_version_id_cdu
            )
            results.append(_result(
                "live_llm_creates_new_du_draft_on_retraction",
                len(du_versions_cdu) >= 2 and du_active_unchanged_cdu and gc_active_unchanged_cdu,
                (
                    f"DU versions={len(du_versions_cdu)} (need >=2), "
                    f"active_du_unchanged={'yes' if du_active_unchanged_cdu else 'NO'}, "
                    f"active_gc_unchanged={'yes' if gc_active_unchanged_cdu else 'NO'}."
                ),
                {
                    "case_type": "live",
                    "model": model_name,
                    "du_version_count": len(du_versions_cdu),
                    "du_active_version_id": du_active_version_id_cdu,
                    "gc_active_version_id": gc_active_version_id_cdu,
                },
            ))

            # ----------------------------------------------------------------
            # Scenario C-GC — GC retraction after PLAN_READY (programmatic setup)
            # ----------------------------------------------------------------
            session_id_cgc = f"retract-cgc-{uuid.uuid4().hex[:8]}"
            session_key_cgc = f"eval-user:{session_id_cgc}:copepod"
            tool_impls_cgc = _live_tool_impls(tools, session_key_cgc)
            base_cgc = {"session_id": session_key_cgc, "tags": TAGS, "dataset": DATASET_NAME}

            client_cgc, stack_cgc = _test_client(store)
            with stack_cgc:
                du_cgc = tools["create_data_understanding_draft"](session_key_cgc, du_artifact)
                tools["activate_data_understanding"](session_key_cgc, du_cgc["version_id"])
                du_active_version_id_cgc = du_cgc["version_id"]

                gc_cgc = tools["create_graph_context_draft"](
                    session_key_cgc, _minimal_gc_artifact(du_active_version_id_cgc)
                )
                tools["activate_graph_context"](session_key_cgc, gc_cgc["version_id"])
                gc_active_version_id_cgc = gc_cgc["version_id"]

                messages_cgc = _synthetic_history_post_plan_ready(
                    session_id_cgc, du_active_version_id_cgc, gc_active_version_id_cgc
                )
                messages_cgc.append(
                    {
                        "role": "user",
                        "content": (
                            "Finalement, je veux changer la configuration du graphique. "
                            "Je veux utiliser la biomasse (mg/m³) en axe Y au lieu de l'abondance, "
                            "et garder la profondeur en axe X. Même fichier EcoTaxa, même type de graphique. "
                            "Refais ça."
                        ),
                    }
                )

                log_fh.write("--- SCENARIO C-GC: gc-retraction ---\n")
                log_fh.flush()
                span_cgc = eval_trace.span(name="scenario/gc-retraction", input={"scenario": "C-GC"}) if eval_trace else None
                _run_llm_turn(
                    messages=messages_cgc,
                    tool_impls=tool_impls_cgc,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_cgc, "phase": "scenario-CGC-retraction", "lf_phase_span": span_cgc},
                    log_fh=log_fh,
                )
                if span_cgc is not None:
                    span_cgc.end()

            gc_versions_cgc = store.get_artifact_versions(session_key_cgc, "graph_context")
            active_gc_cgc = store.get_active_artifact(session_key_cgc, "graph_context")
            active_du_cgc = store.get_active_artifact(session_key_cgc, "data_understanding")
            gc_active_unchanged_cgc = (
                active_gc_cgc is not None
                and active_gc_cgc["version_id"] == gc_active_version_id_cgc
            )
            du_active_unchanged_cgc = (
                active_du_cgc is not None
                and active_du_cgc["version_id"] == du_active_version_id_cgc
            )
            results.append(_result(
                "live_llm_creates_new_gc_draft_on_retraction",
                len(gc_versions_cgc) >= 2 and gc_active_unchanged_cgc and du_active_unchanged_cgc,
                (
                    f"GC versions={len(gc_versions_cgc)} (need >=2), "
                    f"active_gc_unchanged={'yes' if gc_active_unchanged_cgc else 'NO'}, "
                    f"active_du_unchanged={'yes' if du_active_unchanged_cgc else 'NO'}."
                ),
                {
                    "case_type": "live",
                    "model": model_name,
                    "gc_version_count": len(gc_versions_cgc),
                    "du_active_version_id": du_active_version_id_cgc,
                    "gc_active_version_id": gc_active_version_id_cgc,
                },
            ))

        except Exception as exc:
            import traceback
            log_fh.write(f"\n[CRASH] {type(exc).__name__}: {exc}\n")
            log_fh.write(traceback.format_exc())
            log_fh.flush()
            raise
        finally:
            passed_count = sum(1 for r in results if r["passed"])
            log_fh.write(f"\n=== SCORES {passed_count}/{len(results)} ===\n")
            for r in results:
                log_fh.write(f"  {'PASS' if r['passed'] else 'FAIL'} {r['name']}\n")
                if not r["passed"]:
                    log_fh.write(f"       {r['detail']}\n")
            log_fh.write(f"\nlog: {log_path}\n")
            log_fh.flush()

    passed_count = sum(1 for r in results if r["passed"])
    trace_url = _close_eval_trace(lf, eval_trace, results, push_scores=push_langfuse)
    print(f"eval log → {log_path}")
    report = {
        "dataset": DATASET_NAME,
        "mode": "live",
        "model": model_name,
        "passed": passed_count == len(results),
        "passed_count": passed_count,
        "total_count": len(results),
        "results": results,
        "langfuse_trace_url": trace_url,
    }
    return report


def _print_report(report: dict) -> None:
    print(f"{report['dataset']} ({report['mode']})")
    print()
    for result in report["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{status} {result['name']}")
        print(f"     {result['detail']}")
    print()
    print(f"{report['passed_count']}/{report['total_count']} passed")
    if report.get("langfuse_trace_url"):
        print(f"Langfuse trace: {report['langfuse_trace_url']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Copepod artifact rejection and retraction eval.")
    parser.add_argument("--live", action="store_true", help="Run live LLM-driven eval.")
    parser.add_argument("--push-langfuse", action="store_true", help="Push eval scores to Langfuse.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args()

    report = run_rejection_eval(push_langfuse=args.push_langfuse)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
