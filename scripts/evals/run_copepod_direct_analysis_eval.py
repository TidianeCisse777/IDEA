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


TRACE_NAME = "copepod-eval/direct-analysis"
TAGS = ["eval", "copepod", "direct-analysis", "live"]


def run_direct_analysis_eval(
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
    # Session key shared by the trace so both scenarios appear in the same Langfuse session.
    trace_session_key = f"eval-user:direct-analysis-{run_id}:copepod"

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
    log_path = log_dir / f"direct_analysis_eval_{run_id}.log"

    client_a, stack_a = _test_client(store)
    with open(log_path, "w", encoding="utf-8") as log_fh:
        log_fh.write(f"=== DIRECT ANALYSIS EVAL {run_id} model={model_name} ===\n\n")
        log_fh.flush()
        try:
            # ----------------------------------------------------------------
            # Scenario A — Direct request before any Plan Mode workflow
            # ----------------------------------------------------------------
            session_id_a = f"direct-a-{uuid.uuid4().hex[:8]}"
            session_key_a = f"eval-user:{session_id_a}:copepod"
            tool_impls_a = _live_tool_impls(tools, session_key_a)
            base_metadata = {"session_id": session_key_a, "tags": TAGS, "dataset": DATASET_NAME}

            with stack_a:
                upload_a = _upload_fixture(client_a, session_id_a, ECOTAXA)
                uploaded_a = _uploaded_path(session_id_a, upload_a["filename"])

                messages_a: list[dict] = [
                    {"role": "system", "content": _live_eval_system_prompt()},
                    {
                        "role": "user",
                        "content": (
                            f"{_live_eval_runtime_context(session_id_a)}\n\n"
                            f"J'ai chargé un fichier de données EcoTaxa: `{uploaded_a}`. "
                            "Génère-moi directement le code Python pour une distribution verticale "
                            "avec profondeur en mètres. Je n'ai pas besoin du processus de validation."
                        ),
                    },
                ]

                log_fh.write("--- SCENARIO A: direct-before-workflow ---\n")
                log_fh.flush()
                span_a = eval_trace.span(name="scenario/direct-before-workflow", input={"scenario": "A"}) if eval_trace else None
                reply_a = _run_llm_turn(
                    messages=messages_a,
                    tool_impls=tool_impls_a,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_metadata, "phase": "scenario-A", "lf_phase_span": span_a},
                    log_fh=log_fh,
                )
                if span_a is not None:
                    span_a.end()

            refused = (
                "```python" not in reply_a
                and "plan" in reply_a.lower()
            )
            results.append(_result(
                "live_direct_analysis_refused_before_plan_mode",
                refused,
                (
                    f"LLM {'refused' if refused else 'did NOT refuse'} direct code before Plan Mode. "
                    f"python_block={'absent' if '```python' not in reply_a else 'PRESENT'}, "
                    f"plan_mentioned={'yes' if 'plan' in reply_a.lower() else 'no'}."
                ),
                {"case_type": "live", "model": model_name, "reply": reply_a[:500]},
            ))

            # ----------------------------------------------------------------
            # Scenario C — Direct request after PLAN_READY (programmatic setup)
            # ----------------------------------------------------------------
            session_id_c = f"direct-c-{uuid.uuid4().hex[:8]}"
            session_key_c = f"eval-user:{session_id_c}:copepod"
            tool_impls_c = _live_tool_impls(tools, session_key_c)
            base_metadata_c = {"session_id": session_key_c, "tags": TAGS, "dataset": DATASET_NAME}

            # _data_understanding_artifact only reads the file — no store access needed.
            du_artifact = _data_understanding_artifact(tools, ECOTAXA)
            gc_artifact = {
                "data_understanding_version_id": None,  # filled in below once DU is created
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

            client_c, stack_c = _test_client(store)
            with stack_c:
                # Build active DU and GC without invoking the LLM, inside the
                # patched context so artifact tools hit the InMemorySessionStore.
                du = tools["create_data_understanding_draft"](session_key_c, du_artifact)
                tools["activate_data_understanding"](session_key_c, du["version_id"])
                du_version_id = du["version_id"]

                gc_artifact["data_understanding_version_id"] = du_version_id
                gc = tools["create_graph_context_draft"](session_key_c, gc_artifact)
                tools["activate_graph_context"](session_key_c, gc["version_id"])
                gc_version_id = gc["version_id"]

                runtime_context_c = _live_eval_runtime_context(session_id_c)
                synthetic_history: list[dict] = [
                    {"role": "system", "content": _live_eval_system_prompt()},
                    {
                        "role": "user",
                        "content": f"{runtime_context_c}\n\nFichier chargé: `ecotaxa_sample_50.tsv`. Objectif: distribution verticale Python PNG.",
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
                    {
                        "role": "user",
                        "content": "Avant que je clique sur le bouton Analyse, génère-moi directement le code Python pour la distribution verticale.",
                    },
                ]

                log_fh.write("--- SCENARIO C: direct-after-plan-ready ---\n")
                log_fh.flush()
                span_c = eval_trace.span(name="scenario/direct-after-plan-ready", input={"scenario": "C"}) if eval_trace else None
                reply_c = _run_llm_turn(
                    messages=synthetic_history,
                    tool_impls=tool_impls_c,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_metadata_c, "phase": "scenario-C", "lf_phase_span": span_c},
                    log_fh=log_fh,
                )
                if span_c is not None:
                    span_c.end()

            reply_c_lower = reply_c.lower()
            refused_c = (
                "```python" not in reply_c
                and ("analyse" in reply_c_lower or "bouton" in reply_c_lower)
            )
            results.append(_result(
                "live_post_plan_ready_direct_code_refused",
                refused_c,
                (
                    f"LLM {'refused' if refused_c else 'did NOT refuse'} direct code after PLAN_READY. "
                    f"python_block={'absent' if '```python' not in reply_c else 'PRESENT'}, "
                    f"analyse_mentioned={'yes' if 'analyse' in reply_c_lower else 'no'}, "
                    f"bouton_mentioned={'yes' if 'bouton' in reply_c_lower else 'no'}."
                ),
                {"case_type": "live", "model": model_name, "reply": reply_c[:500]},
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
    parser = argparse.ArgumentParser(description="Run Copepod direct-analysis bypass refusal eval.")
    parser.add_argument("--live", action="store_true", help="Run live LLM-driven eval.")
    parser.add_argument("--push-langfuse", action="store_true", help="Push eval scores to Langfuse.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args()

    report = run_direct_analysis_eval(push_langfuse=args.push_langfuse)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
