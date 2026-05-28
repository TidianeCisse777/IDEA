"""CLI entry point for Copepod Plan Mode evals.

All logic lives in scripts/evals/copepod/. This file is kept for
backward compatibility (Docker commands, pytest imports) and exposes
every name that external callers and tests depend on.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

# --- public re-exports (tests and external scripts import from here) ---
from scripts.evals.copepod.eval_du import run_live_du_only_eval  # noqa: F401
from scripts.evals.copepod.eval_gc import run_live_gc_only_eval  # noqa: F401
from scripts.evals.copepod.eval_live import run_live_eval  # noqa: F401
from scripts.evals.copepod.eval_mock import run_mock_eval  # noqa: F401
from scripts.evals.copepod.eval_smoke import run_langfuse_trace_smoke  # noqa: F401
from scripts.evals.copepod.fixtures import (  # noqa: F401
    ECOTAXA,
    ECOPART,
    _data_understanding_artifact,
    _upload_fixture,
    _uploaded_path,
    _uploaded_path_label,
)
from scripts.evals.copepod.harness import (  # noqa: F401
    DATASET_NAME,
    _cleanup_old_logs,
    _close_eval_trace,
    _configure_local_langfuse_host,
    _json_dumps,
    _load_tools,
    _make_eval_trace,
    _make_test_client as _test_client,
    _result,
)
from scripts.evals.copepod.llm_driver import (  # noqa: F401
    _compact_tool_result,
    _completion_message,
    _default_live_completion,
    _live_tool_impls,
    _message_to_dict,
    _run_llm_turn,
    _tool_call_to_dict,
    _tool_specs,
)
from scripts.evals.copepod.system_messages import (  # noqa: F401
    _build_eval_system_message,
    _live_eval_runtime_context,
    _live_eval_system_prompt,
)


def _print_report(report: dict) -> None:
    print(f"{report['dataset']} ({report['mode']})")
    print()
    if report["mode"] == "trace-smoke":
        status = "PASS" if report["passed"] else "FAIL"
        print(f"{status} trace_smoke_prompt_returned_output")
        print(f"     {report['response']}")
        if report.get("langfuse_trace_url"):
            print(f"Langfuse trace: {report['langfuse_trace_url']}")
        return
    for result in report["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{status} {result['name']}")
        print(f"     {result['detail']}")
    print()
    print(f"{report['passed_count']}/{report['total_count']} passed")
    if report.get("langfuse_trace_url"):
        print(f"Langfuse trace: {report['langfuse_trace_url']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Copepod Plan Mode workflow evals.")
    parser.add_argument("--mock", action="store_true", help="Run deterministic no-LLM evals.")
    parser.add_argument("--live-gc-only", action="store_true", help="Run live LLM evals through Graph Context only.")
    parser.add_argument("--live-du-only", action="store_true", help="Run live LLM evals through Data Understanding only.")
    parser.add_argument("--live", action="store_true", help="Run live LLM-driven evals.")
    parser.add_argument("--trace-smoke", action="store_true", help="Send one prompt and verify Langfuse trace/level/score.")
    parser.add_argument(
        "--prompt",
        default="Dis simplement que la trace Langfuse fonctionne.",
        help="Prompt for --trace-smoke.",
    )
    parser.add_argument("--push-langfuse", action="store_true", help="Push eval scores to Langfuse.")
    parser.add_argument(
        "--gc-scenarios",
        default="",
        help="Comma-separated GC-only scenario slugs to run (rich,poor,offtopic,analysis-jump).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args()

    if args.trace_smoke:
        report = run_langfuse_trace_smoke(prompt=args.prompt)
    elif args.live_gc_only:
        scenario_slugs = [slug.strip() for slug in args.gc_scenarios.split(",") if slug.strip()]
        report = run_live_gc_only_eval(
            push_langfuse=args.push_langfuse,
            scenario_slugs=scenario_slugs or None,
        )
    elif args.live_du_only:
        report = run_live_du_only_eval(push_langfuse=args.push_langfuse)
    elif args.live:
        report = run_live_eval(push_langfuse=args.push_langfuse)
    else:
        report = run_mock_eval(push_langfuse=args.push_langfuse)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
