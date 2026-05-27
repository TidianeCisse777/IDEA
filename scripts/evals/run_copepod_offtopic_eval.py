from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
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
    _build_eval_system_message,
    _live_eval_runtime_context,
    ECOTAXA,
    DATASET_NAME,
)

from core.config import settings
from core.session_store import InMemorySessionStore


TRACE_NAME = "copepod-eval/off-topic"
TAGS = ["eval", "copepod", "off-topic", "live"]


def run_offtopic_eval(
    *,
    push_langfuse: bool = False,
    completion_fn: Callable[..., Any] | None = None,
) -> dict:
    store = InMemorySessionStore()
    tools = _load_tools()
    session_id = f"offtopic-eval-{uuid.uuid4().hex[:10]}"
    session_key = f"eval-user:{session_id}:copepod"
    model_name = settings.LLM_MODEL
    completion_fn = completion_fn or _default_live_completion
    results: list[dict] = []

    lf, eval_trace = None, None
    if push_langfuse:
        try:
            from langfuse import Langfuse
            _configure_local_langfuse_host()
            lf = Langfuse()
            eval_trace = lf.trace(
                name=TRACE_NAME,
                user_id="eval-user",
                session_id=session_key,
                tags=TAGS,
                input={"model": model_name, "file": ECOTAXA.name, "session_id": session_id},
            )
        except Exception:
            pass

    log_dir = ROOT / "logs" / "evals"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"offtopic_eval_{session_id}.log"

    client, stack = _test_client(store)
    with open(log_path, "w", encoding="utf-8") as log_fh:
        log_fh.write(f"=== OFFTOPIC EVAL {session_id} model={model_name} ===\n")
        log_fh.write(f"    file={ECOTAXA.name}  session={session_key}\n\n")
        log_fh.flush()
        try:
            with stack:
                upload = _upload_fixture(client, session_id, ECOTAXA)
                uploaded_ecotaxa = _uploaded_path(session_id, upload["filename"])
                tool_impls = _live_tool_impls(tools, session_key)
                runtime_context = _live_eval_runtime_context(session_id)
                messages: list[dict] = [
                    {
                        "role": "system",
                        "content": _build_eval_system_message(store, session_id),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"{runtime_context}\n\n"
                            f"Fichier chargé: `{uploaded_ecotaxa}`. Objectif final: produire une distribution "
                            f"verticale EcoTaxa en Python, en PNG, avec profondeur en metres. Commence par la "
                            "Phase 1. Tu dois appeler les outils maintenant avant de répondre."
                        ),
                    },
                ]
                base_metadata = {
                    "session_id": session_key,
                    "tags": TAGS,
                    "dataset": DATASET_NAME,
                }

                log_fh.write("--- PHASE 1: du-draft ---\n")
                log_fh.flush()
                du_span = eval_trace.span(name="phase/du-draft", input={"phase": "data-understanding-draft"}) if eval_trace else None
                _run_llm_turn(
                    messages=messages,
                    tool_impls=tool_impls,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_metadata, "phase": "du-draft", "lf_phase_span": du_span},
                    log_fh=log_fh,
                )
                if du_span is not None:
                    du_span.end()

                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Ouais ça m'a l'air bien, vas-y pour la suite. Au fait, c'est quoi exactement "
                            "la différence entre un copépode calanoïde et un cyclopoïde, et pourquoi EcoTaxa "
                            "distingue-t-il ces deux ordres dans sa taxonomie ?"
                        ),
                    }
                )

                log_fh.write("--- PHASE 2: offtopic-confirmation ---\n")
                log_fh.flush()
                offtopic_span = eval_trace.span(name="phase/offtopic-confirmation", input={"phase": "offtopic-confirmation"}) if eval_trace else None
                reply = _run_llm_turn(
                    messages=messages,
                    tool_impls=tool_impls,
                    model=model_name,
                    completion_fn=completion_fn,
                    metadata={**base_metadata, "phase": "offtopic-confirmation", "lf_phase_span": offtopic_span},
                    log_fh=log_fh,
                )
                if offtopic_span is not None:
                    offtopic_span.end()

                active_du = store.get_active_artifact(session_key, "data_understanding")
                gc_versions = store.get_artifact_versions(session_key, "graph_context")
                gc_draft = gc_versions[-1] if gc_versions else None

                scientific_terms = {"calanoïde", "cyclopoïde", "copépode", "ordre", "antenne", "plancton", "taxonom"}
                reply_lower = reply.lower()
                scientific_question_answered = (
                    len(reply) > 100
                    and any(term in reply_lower for term in scientific_terms)
                )
                results.append(_result(
                    "live_offtopic_answered_scientific_question",
                    scientific_question_answered,
                    f"LLM answered the off-topic question (reply length={len(reply)}, terms matched={[t for t in scientific_terms if t in reply_lower]}).",
                    {"case_type": "live", "model": model_name, "reply": reply[:500]},
                ))

                workflow_continued = (
                    active_du is not None
                    and gc_draft is not None
                    and gc_draft.get("status") == "draft"
                )
                results.append(_result(
                    "live_offtopic_workflow_continued_after_question",
                    workflow_continued,
                    (
                        f"Workflow continued: active_du={'set' if active_du else 'None'}, "
                        f"gc_draft={'set' if gc_draft else 'None'} "
                        f"status={gc_draft.get('status') if gc_draft else 'N/A'}."
                    ),
                    {"case_type": "live", "model": model_name},
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
        "session_id": session_id,
        "session_key": session_key,
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
    parser = argparse.ArgumentParser(description="Run Copepod off-topic question resilience eval.")
    parser.add_argument("--live", action="store_true", help="Run live LLM-driven eval.")
    parser.add_argument("--push-langfuse", action="store_true", help="Push eval scores to Langfuse.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args()

    report = run_offtopic_eval(push_langfuse=args.push_langfuse)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
