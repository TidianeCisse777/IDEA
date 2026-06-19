"""EcoTaxa exploration evals focused on tool trajectory and arguments.

This suite complements ``eval_ecotaxa_vision.py``. The older suite checks
high-level routing; this one checks whether the agent uses the right EcoTaxa
exploration workflow and preserves critical parameters.

Run a small subset:
    EVAL_CASE_IDS=EX-01-project-summary python evals/eval_ecotaxa_exploration.py

Run all cases:
    python evals/eval_ecotaxa_exploration.py
"""

from __future__ import annotations

import json
import os
import sys
import uuid
import argparse
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

from agent import invoke_verbose, make_agent
from evals.runner import print_scores, run_eval_suite

load_dotenv()

DATASET_NAME = "copepod-ecotaxa-exploration-evals"
DEFAULT_PASS_THRESHOLD = 0.8
SCORE_KEYS = [
    "trajectory_subsequence",
    "forbidden_tools_absent",
    "required_tool_args_present",
]


EXPLORATION_CASES = [
    {
        "id": "EX-01-project-summary",
        "inputs": {
            "question": "Dans EcoTaxa, résume le projet 14853 avant export."
        },
        "outputs": {
            "expected_sequence": [
                "load_skill",
                "summarize_ecotaxa_project",
            ],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "summarize_ecotaxa_project",
                    "args": {"project_id": 14853},
                },
            ],
            "forbidden_tools": ["query_ecotaxa", "run_pandas", "run_graph"],
            "category": "project_summary",
        },
    },
    {
        "id": "EX-02-taxon-count",
        "inputs": {
            "question": (
                "Combien de copépodes validés dans le projet EcoTaxa 14853 ? "
                "Je veux les stats taxonomiques, pas un export."
            )
        },
        "outputs": {
            "expected_sequence": ["load_skill", "count_ecotaxa_taxa"],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "count_ecotaxa_taxa",
                    "args": {"project_ids": [14853]},
                },
            ],
            "forbidden_tools": ["query_ecotaxa", "run_pandas", "run_graph"],
            "category": "taxon_count",
        },
    },
    {
        "id": "EX-03-zone-samples",
        "inputs": {
            "question": (
                "Quels samples EcoTaxa sont dans la Baie de Baffin entre "
                "2024-10-01 et 2024-10-31 ?"
            )
        },
        "outputs": {
            "expected_sequence": [
                "load_skill",
                "find_ecotaxa_samples_in_region",
            ],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "find_ecotaxa_samples_in_region",
                    "args": {"zone_name": "Baie de Baffin"},
                },
            ],
            "forbidden_tools": ["query_ecotaxa", "run_pandas", "run_graph"],
            "category": "zone_samples",
        },
    },
    {
        "id": "EX-04-projects-by-region",
        "inputs": {
            "question": (
                "Quels projets EcoTaxa ont des samples UVP6 entre 70N et 75N, "
                "-80W et -60W ?"
            )
        },
        "outputs": {
            "expected_sequence": [
                "load_skill",
                "find_ecotaxa_projects_in_region",
            ],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "find_ecotaxa_projects_in_region",
                    "args": {
                        "bbox": {
                            "south": 70,
                            "west": -80,
                            "north": 75,
                            "east": -60,
                        },
                    },
                },
            ],
            "forbidden_tools": ["query_ecotaxa", "run_pandas", "run_graph"],
            "category": "projects_region",
        },
    },
    {
        "id": "EX-05-sample-deployment",
        "inputs": {
            "question": (
                "Pour le sample EcoTaxa 14853000001, donne date, lieu, "
                "profondeur min/max et infos UVP du déploiement."
            )
        },
        "outputs": {
            "expected_sequence": [
                "load_skill",
                "summarize_ecotaxa_sample_deployment",
            ],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "summarize_ecotaxa_sample_deployment",
                    "args": {"sample_id": 14853000001},
                },
            ],
            "forbidden_tools": ["query_ecotaxa", "run_pandas", "run_graph"],
            "category": "sample_deployment",
        },
    },
    {
        "id": "EX-06-sample-batch-summary",
        "inputs": {
            "question": (
                "Résume les samples EcoTaxa 14853000001, 14853000002 et "
                "14853000003 avant de choisir lesquels exporter."
            )
        },
        "outputs": {
            "expected_sequence": ["load_skill", "summarize_ecotaxa_samples"],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "summarize_ecotaxa_samples",
                    "args": {
                        "sample_ids": [
                            14853000001,
                            14853000002,
                            14853000003,
                        ],
                    },
                },
            ],
            "forbidden_tools": ["query_ecotaxa", "run_pandas", "run_graph"],
            "category": "sample_summary",
        },
    },
    {
        "id": "EX-07-column-inspection",
        "inputs": {
            "question": (
                "Dans le projet EcoTaxa 14853, inspecte la distribution de "
                "la colonne depth_min."
            )
        },
        "outputs": {
            "expected_sequence": ["load_skill", "inspect_ecotaxa_column"],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "inspect_ecotaxa_column",
                    "args": {"project_id": 14853, "column_name": "depth_min"},
                },
            ],
            "forbidden_tools": [
                "inspect_ecotaxa_project_schema",
                "query_ecotaxa",
                "run_pandas",
                "run_graph",
            ],
            "category": "column_inspection",
        },
    },
    {
        "id": "EX-08-compare-projects",
        "inputs": {
            "question": (
                "Compare les projets EcoTaxa 14853 et 2331 avant un export "
                "combiné : schéma, colonnes communes et conflits."
            )
        },
        "outputs": {
            "expected_sequence": ["load_skill", "compare_ecotaxa_projects"],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "compare_ecotaxa_projects",
                    "args": {"project_ids": [14853, 2331]},
                },
            ],
            "forbidden_tools": ["query_ecotaxa", "run_pandas", "run_graph"],
            "category": "project_compare",
        },
    },
    {
        "id": "EX-09-export-dry-run",
        "inputs": {
            "question": (
                "Prépare l'export des samples EcoTaxa 14853000001 et "
                "14853000002, mais ne lance rien tant que je n'ai pas confirmé."
            )
        },
        "outputs": {
            "expected_sequence": ["load_skill", "export_ecotaxa_samples"],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "export_ecotaxa_samples",
                    "args": {
                        "sample_ids": [14853000001, 14853000002],
                        "confirmed": False,
                    },
                },
            ],
            "forbidden_tools": ["query_ecotaxa", "run_pandas", "run_graph"],
            "category": "export_dry_run",
        },
    },
    {
        "id": "EX-10-knowledge-not-ecotaxa",
        "inputs": {
            "question": "Dans le contexte NeoLab, que signifie copépodes ?"
        },
        "outputs": {
            "expected_sequence": ["query_copepod_knowledge_base"],
            "required_tool_args": [],
            "forbidden_tools": [
                "load_skill",
                "find_ecotaxa_samples_in_region",
                "query_ecotaxa",
            ],
            "category": "non_ecotaxa",
        },
    },
]


def _tool_call_name(tool_call: Any) -> str | None:
    if isinstance(tool_call, dict):
        return tool_call.get("name")
    return getattr(tool_call, "name", None)


def _tool_call_args(tool_call: Any) -> dict[str, Any]:
    if isinstance(tool_call, dict):
        return dict(tool_call.get("args") or {})
    return dict(getattr(tool_call, "args", None) or {})


def _capture_tool_calls(state: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for msg in state.get("messages", []):
        for tool_call in getattr(msg, "tool_calls", None) or []:
            name = _tool_call_name(tool_call)
            if name:
                calls.append({"name": name, "arguments": _tool_call_args(tool_call)})
    return calls


def _final_text(state: dict[str, Any]) -> str:
    messages = state.get("messages", [])
    if not messages:
        return ""
    content = getattr(messages[-1], "content", "") or ""
    return str(content)


def run_one_case(inputs: dict[str, Any]) -> dict[str, Any]:
    thread_id = f"ecotaxa-exploration-eval-{uuid.uuid4().hex[:10]}"
    agent = make_agent(thread_id, user_id="eval-bot")
    config = {
        "configurable": {"thread_id": thread_id},
        "metadata": {
            "user_id": "eval-bot",
            "eval": "ecotaxa-exploration",
            "dataset": DATASET_NAME,
        },
        "recursion_limit": 30,
    }
    case_delay = float(os.getenv("EVAL_CASE_DELAY_SECONDS", "0"))
    if case_delay > 0:
        time.sleep(case_delay)

    max_attempts = int(os.getenv("EVAL_MAX_ATTEMPTS", "3"))
    retry_delay = float(os.getenv("EVAL_RETRY_DELAY_SECONDS", "20"))
    final_state: dict[str, Any] = {}
    for attempt in range(1, max_attempts + 1):
        try:
            final_state = invoke_verbose(
                agent,
                {"messages": [{"role": "user", "content": inputs["question"]}]},
                config,
            )
            break
        except Exception as exc:
            if attempt >= max_attempts or not _is_rate_limit_error(exc):
                raise
            wait_seconds = retry_delay * attempt
            print(
                f"Rate limit during case; retrying in {wait_seconds:.1f}s "
                f"({attempt}/{max_attempts})"
            )
            time.sleep(wait_seconds)
    tool_calls = _capture_tool_calls(final_state)
    return {
        "trajectory": [call["name"] for call in tool_calls],
        "tool_calls": tool_calls,
        "final_answer": _final_text(final_state)[:1500],
    }


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "rate limit" in text
        or "rate_limit_exceeded" in text
        or exc.__class__.__name__ == "RateLimitError"
    )


def _matches_expected(expected: Any, actual: Any) -> bool:
    """Return True when expected is a recursive subset of actual.

    Numeric comparisons are tolerant to int/float differences. Lists are
    compared as order-insensitive when both sides contain only scalars.
    """
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(
            key in actual and _matches_expected(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        if all(not isinstance(item, (dict, list)) for item in expected + actual):
            return sorted(expected) == sorted(actual)
        if len(expected) != len(actual):
            return False
        return all(
            _matches_expected(exp_item, act_item)
            for exp_item, act_item in zip(expected, actual, strict=False)
        )
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) < 1e-9
    return expected == actual


def _expected_step_matches(expected_step: Any, actual_tool: str) -> bool:
    if isinstance(expected_step, str):
        return actual_tool == expected_step
    if isinstance(expected_step, list):
        return actual_tool in expected_step
    return False


def _format_expected_step(expected_step: Any) -> str:
    if isinstance(expected_step, list):
        return " | ".join(str(item) for item in expected_step)
    return str(expected_step)


def trajectory_subsequence(outputs: dict, reference_outputs: dict) -> dict:
    expected = reference_outputs.get("expected_sequence", [])
    actual = outputs.get("trajectory", [])
    if not expected:
        return {
            "key": "trajectory_subsequence",
            "score": 1,
            "comment": "No expected trajectory.",
        }
    cursor = 0
    matched_indexes: list[int] = []
    for tool_name in actual:
        for idx in range(cursor, len(expected)):
            if _expected_step_matches(expected[idx], tool_name):
                matched_indexes.append(idx)
                cursor = idx + 1
                break
    missing = [
        _format_expected_step(step)
        for idx, step in enumerate(expected)
        if idx not in matched_indexes
    ]
    return {
        "key": "trajectory_subsequence",
        "score": len(matched_indexes) / len(expected),
        "comment": (
            f"Expected {expected}; observed {actual}"
            + (f"; missing {missing}" if missing else "")
        ),
    }


def forbidden_tools_absent(outputs: dict, reference_outputs: dict) -> dict:
    actual = outputs.get("trajectory", [])
    forbidden = set(reference_outputs.get("forbidden_tools", []))
    violations = [tool_name for tool_name in actual if tool_name in forbidden]
    return {
        "key": "forbidden_tools_absent",
        "score": int(not violations),
        "comment": f"Forbidden tools called: {violations}" if violations else "",
    }


def required_tool_args_present(outputs: dict, reference_outputs: dict) -> dict:
    calls = outputs.get("tool_calls", [])
    missing: list[str] = []
    requirements = reference_outputs.get("required_tool_args", [])
    if not requirements:
        return {
            "key": "required_tool_args_present",
            "score": 1,
            "comment": "No required tool arguments.",
        }
    for requirement in reference_outputs.get("required_tool_args", []):
        name = requirement["name"]
        expected_args = requirement.get("args", {})
        matched = any(
            call.get("name") == name
            and _matches_expected(expected_args, call.get("arguments", {}))
            for call in calls
        )
        if not matched:
            missing.append(f"{name} args subset {expected_args}")

    passed = len(requirements) - len(missing)
    score = passed / len(requirements)
    return {
        "key": "required_tool_args_present",
        "score": score,
        "comment": (
            "Missing: "
            + "; ".join(missing)
            + " | observed="
            + json.dumps(calls, ensure_ascii=False)[:1000]
            if missing
            else ""
        ),
    }


def evaluator_trajectory_subsequence(run, example) -> dict:
    return trajectory_subsequence(run.outputs or {}, example.outputs or {})


def evaluator_forbidden_tools_absent(run, example) -> dict:
    return forbidden_tools_absent(run.outputs or {}, example.outputs or {})


def evaluator_required_tool_args_present(run, example) -> dict:
    return required_tool_args_present(run.outputs or {}, example.outputs or {})


def _selected_cases() -> list[dict[str, Any]]:
    only_ids = os.getenv("EVAL_CASE_IDS")
    if not only_ids:
        return EXPLORATION_CASES
    wanted = {item.strip() for item in only_ids.split(",") if item.strip()}
    return [case for case in EXPLORATION_CASES if case["id"] in wanted]


def _filter_cases(case_ids: str | None) -> list[dict[str, Any]]:
    if not case_ids:
        return _selected_cases()
    wanted = {item.strip() for item in case_ids.split(",") if item.strip()}
    return [case for case in EXPLORATION_CASES if case["id"] in wanted]


def _print_case_catalog(cases: list[dict[str, Any]]) -> None:
    print("\n=== EcoTaxa exploration cases ===")
    for case in cases:
        outputs = case["outputs"]
        sequence = " -> ".join(
            _format_expected_step(step)
            for step in outputs.get("expected_sequence", [])
        )
        print(f"- {case['id']} [{outputs.get('category', 'uncategorized')}]")
        print(f"  question: {case['inputs']['question']}")
        print(f"  expected: {sequence or 'none'}")
        forbidden = outputs.get("forbidden_tools", [])
        if forbidden:
            print(f"  forbidden: {', '.join(forbidden)}")


def _print_detailed_report(rows: list[tuple], cases: list[dict[str, Any]]) -> None:
    by_id = {case["id"]: case for case in cases}
    print("\n=== Detailed EcoTaxa eval report ===")
    for row in rows:
        case_id, scores = row[0], row[1]
        comments = row[2] if len(row) > 2 else {}
        case = by_id.get(case_id, {})
        category = case.get("outputs", {}).get("category", "?")
        print(f"\n{case_id} [{category}]")
        for key, value in scores.items():
            print(f"  {key}: {value:.2f}")
            comment = comments.get(key)
            if comment:
                print(f"    {comment}")


def _chunks(items: list[dict[str, Any]], size: int | None) -> list[list[dict[str, Any]]]:
    if not size or size <= 0 or size >= len(items):
        return [items]
    return [items[index:index + size] for index in range(0, len(items), size)]


def _apply_quick_defaults(args: argparse.Namespace) -> None:
    if not args.quick:
        return
    args.max_concurrency = 1
    args.case_delay = 5.0
    args.retry_delay = 20.0
    args.max_attempts = 2
    args.output_tokens = min(args.output_tokens, 900)
    if args.batch_size is None:
        args.batch_size = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        dest="case_ids",
        help="Comma-separated case ids. Overrides EVAL_CASE_IDS.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.getenv("EVAL_PASS_THRESHOLD", DEFAULT_PASS_THRESHOLD)),
        help="Average score threshold used for the final pass/fail summary.",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="Print cases and expected criteria without running LangSmith.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help=(
            "Use faster stable defaults: max_concurrency=1, case_delay=5, "
            "retry_delay=20, max_attempts=2, output_tokens<=900, batch_size=3."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help=(
            "Split selected cases into mini LangSmith runs. Useful to avoid "
            "long full-suite runs and isolate failures."
        ),
    )
    parser.add_argument(
        "--output-tokens",
        type=int,
        default=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "1200")),
        help="LLM_MAX_OUTPUT_TOKENS value used for eval agent calls.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=os.getenv("EVAL_VERBOSE", "").lower() in {"1", "true", "yes"},
        help="Print criteria before run and detailed evaluator comments after run.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=int(os.getenv("EVAL_MAX_CONCURRENCY", "1")),
        help="LangSmith evaluate concurrency. Keep at 1 to avoid OpenAI TPM 429s.",
    )
    parser.add_argument(
        "--case-delay",
        type=float,
        default=float(os.getenv("EVAL_CASE_DELAY_SECONDS", "0")),
        help="Seconds to wait before each case. Useful for TPM-limited models.",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=float(os.getenv("EVAL_RETRY_DELAY_SECONDS", "20")),
        help="Base seconds to wait before retrying a rate-limited case.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=int(os.getenv("EVAL_MAX_ATTEMPTS", "3")),
        help="Maximum attempts for a rate-limited case.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    _apply_quick_defaults(args)
    os.environ["LLM_MAX_OUTPUT_TOKENS"] = str(args.output_tokens)
    os.environ["EVAL_CASE_DELAY_SECONDS"] = str(args.case_delay)
    os.environ["EVAL_RETRY_DELAY_SECONDS"] = str(args.retry_delay)
    os.environ["EVAL_MAX_ATTEMPTS"] = str(args.max_attempts)
    cases = _filter_cases(args.case_ids)
    batches = _chunks(cases, args.batch_size)
    print(
        f"Running {len(cases)} EcoTaxa exploration eval case(s) "
        f"in {len(batches)} batch(es)."
    )
    print(
        "Settings: "
        f"tokens={args.output_tokens}, concurrency={args.max_concurrency}, "
        f"case_delay={args.case_delay}, retry_delay={args.retry_delay}, "
        f"max_attempts={args.max_attempts}, batch_size={args.batch_size or 'all'}"
    )
    if args.verbose or args.list_cases:
        _print_case_catalog(cases)
    if args.list_cases:
        return

    rows = []
    for batch_index, batch_cases in enumerate(batches, start=1):
        suffix = f"-batch-{batch_index:02d}" if len(batches) > 1 else ""
        print(
            f"\n=== Running batch {batch_index}/{len(batches)}: "
            f"{[case['id'] for case in batch_cases]} ==="
        )
        batch_rows = run_eval_suite(
            cases=batch_cases,
            run_fn=run_one_case,
            evaluators=[
                evaluator_trajectory_subsequence,
                evaluator_forbidden_tools_absent,
                evaluator_required_tool_args_present,
            ],
            dataset_name=f"{DATASET_NAME}{suffix}",
            experiment_prefix=f"ecotaxa-exploration{suffix}",
            metadata={
                "suite": "ecotaxa-exploration",
                "model": os.getenv("LLM_MODEL", "openai/gpt-5.4-mini"),
                "max_concurrency": args.max_concurrency,
                "batch": batch_index,
                "batches_total": len(batches),
            },
            max_concurrency=args.max_concurrency,
        )
        rows.extend(batch_rows)

    print("\n=== Combined score summary ===")
    print_scores(
        rows,
        score_keys=SCORE_KEYS,
        threshold=args.threshold,
    )
    if args.verbose:
        _print_detailed_report(rows, cases)


if __name__ == "__main__":
    main()
