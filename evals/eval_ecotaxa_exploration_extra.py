"""Extra EcoTaxa exploration evals — gaps not covered by the main suite.

Mirrors the UI tests E0, E3, E4, E7, E12 and E13 documented in
``docs/ecotaxa_exploration_ui_tests.md``. Kept in a separate file because
``eval_ecotaxa_exploration.py`` is already large; runners and evaluators are
reused from there.

Run a subset:
    EVAL_CASE_IDS=EX-24-list-projects python evals/eval_ecotaxa_exploration_extra.py

Run all extra cases:
    python evals/eval_ecotaxa_exploration_extra.py
"""

from __future__ import annotations

import os
import sys
import uuid
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

from agent import invoke_verbose, make_agent
from evals.eval_ecotaxa_exploration import (
    SCORE_KEYS,
    _apply_quick_defaults,
    _capture_tool_calls,
    _chunks,
    _final_text,
    evaluator_final_answer_contains,
    evaluator_forbidden_tool_args_absent,
    evaluator_forbidden_tools_absent,
    evaluator_required_tool_args_present,
    evaluator_trajectory_subsequence,
    parse_args,
    run_one_case,
)
from evals.runner import print_scores, run_eval_suite

load_dotenv()

DATASET_NAME = "copepod-ecotaxa-exploration-extra-evals"


def _run_multi_turn_case(inputs: dict[str, Any]) -> dict[str, Any]:
    """Drive the agent through multiple user turns on the same thread_id.

    The checkpointer keeps history, so the final state's messages contain
    the full transcript. Tool calls and final answer are extracted from
    that aggregated state.
    """
    thread_id = f"ecotaxa-exploration-mt-eval-{uuid.uuid4().hex[:10]}"
    agent = make_agent(thread_id, user_id="eval-bot")
    config = {
        "configurable": {"thread_id": thread_id},
        "metadata": {
            "user_id": "eval-bot",
            "eval": "ecotaxa-exploration-extra",
            "dataset": DATASET_NAME,
            "multi_turn": True,
        },
        "recursion_limit": 30,
    }
    final_state: dict[str, Any] = {}
    for turn in inputs.get("turns", []):
        final_state = invoke_verbose(
            agent,
            {"messages": [{"role": "user", "content": turn["question"]}]},
            config,
        )
    tool_calls = _capture_tool_calls(final_state)
    return {
        "trajectory": [call["name"] for call in tool_calls],
        "tool_calls": tool_calls,
        "final_answer": _final_text(final_state)[:1500],
    }


def _run_case_dispatch(inputs: dict[str, Any]) -> dict[str, Any]:
    if "turns" in inputs:
        return _run_multi_turn_case(inputs)
    return run_one_case(inputs)


EXTRA_CASES: list[dict[str, Any]] = [
    {
        "id": "EX-24-list-projects",
        "inputs": {"question": "Quels projets EcoTaxa sont accessibles ?"},
        "outputs": {
            "expected_sequence": ["list_ecotaxa_projects"],
            "required_tool_args": [
                {"name": "list_ecotaxa_projects", "args": {}},
            ],
            "forbidden_tools": [
                "query_ecotaxa",
                "find_ecotaxa_samples_in_region",
                "find_ecotaxa_projects_in_region",
                "run_pandas",
                "run_graph",
            ],
            "category": "list_projects",
        },
    },
    {
        "id": "EX-25-projects-by-title",
        "inputs": {
            "question": (
                "Cherche les projets EcoTaxa qui contiennent LOKI dans le titre."
            )
        },
        "outputs": {
            "expected_sequence": ["find_ecotaxa_projects"],
            "required_tool_args": [
                {
                    "name": "find_ecotaxa_projects",
                    "args": {
                        "title": {"__any__": ["LOKI", "Loki", "loki"]},
                    },
                },
            ],
            "forbidden_tools": [
                "find_ecotaxa_samples_in_region",
                "find_ecotaxa_projects_in_region",
                "list_ecotaxa_projects",
                "query_ecotaxa",
                "run_pandas",
                "run_graph",
            ],
            "category": "projects_by_title",
        },
    },
    {
        "id": "EX-26-multi-project-summary-mixed-cache",
        "inputs": {
            "question": (
                "Fais un tableau de stats pour les projets EcoTaxa 14853, "
                "2331 et 4042 avant export."
            )
        },
        "outputs": {
            "expected_sequence": ["load_skill", "summarize_ecotaxa_projects"],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "summarize_ecotaxa_projects",
                    "args": {"project_ids": [14853, 2331, 4042]},
                },
            ],
            "forbidden_tools": ["query_ecotaxa", "run_pandas", "run_graph"],
            "final_answer_contains": ["2331", "4042", "cache"],
            "category": "multi_project_summary_mixed",
        },
    },
    {
        "id": "EX-27-multi-project-taxon-count",
        "inputs": {
            "question": (
                "Compare les comptes V/P/D/U de Copepoda dans les projets "
                "EcoTaxa 14853, 17498 et 14859."
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
                    "args": {
                        "project_ids": [14853, 17498, 14859],
                        "taxa": ["Copepoda"],
                    },
                },
            ],
            "forbidden_tools": [
                "query_copepod_knowledge_base",
                "query_ecotaxa",
                "run_pandas",
                "run_graph",
            ],
            "final_answer_contains": ["2063", "994", "182"],
            "category": "multi_project_taxon_count",
        },
    },
    {
        "id": "EX-28-schema-inspection",
        "inputs": {
            "question": (
                "Quelles colonnes sont disponibles dans le projet EcoTaxa 14853 ?"
            )
        },
        "outputs": {
            "expected_sequence": [
                "load_skill",
                "inspect_ecotaxa_project_schema",
            ],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "inspect_ecotaxa_project_schema",
                    "args": {"project_id": 14853},
                },
            ],
            "forbidden_tools": [
                "preview_ecotaxa_project",
                "summarize_ecotaxa_project",
                "summarize_ecotaxa_projects",
                "query_ecotaxa",
                "run_pandas",
                "run_graph",
            ],
            "final_answer_contains": ["sample", "object"],
            "category": "schema_inspection",
        },
    },
    {
        "id": "EX-29-preview-light-overview",
        "inputs": {
            "question": "Présente-moi rapidement le projet EcoTaxa 14853."
        },
        "outputs": {
            "expected_sequence": ["preview_ecotaxa_project"],
            "required_tool_args": [
                {
                    "name": "preview_ecotaxa_project",
                    "args": {"project_id": 14853},
                },
            ],
            "forbidden_tools": [
                "summarize_ecotaxa_project",
                "summarize_ecotaxa_projects",
                "inspect_ecotaxa_project_schema",
                "query_ecotaxa",
                "run_pandas",
                "run_graph",
            ],
            "category": "preview_light",
        },
    },
    {
        "id": "EX-30-ranking-non-annotated",
        "inputs": {
            "question": (
                "Parmi les projets EcoTaxa 14853, 2331 et 4042, lesquels "
                "contiennent le plus d'images non annotées (P + D + U) ?"
            )
        },
        "outputs": {
            "expected_sequence": ["load_skill", "summarize_ecotaxa_projects"],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "summarize_ecotaxa_projects",
                    "args": {"project_ids": [14853, 2331, 4042]},
                },
            ],
            "forbidden_tools": ["query_ecotaxa", "run_pandas", "run_graph"],
            "final_answer_contains": ["515419", "14853"],
            "category": "ranking_non_annotated",
        },
    },
    {
        "id": "EX-31-instrument-routing-loki",
        "inputs": {
            "question": "Liste les samples LOKI dans la Baie de Baffin en 2024."
        },
        "outputs": {
            "expected_sequence": [
                "load_skill",
                "get_zone_info",
                "find_ecotaxa_samples_in_region",
            ],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "get_zone_info",
                    "args": {"zone_name": "Baie de Baffin"},
                },
                {
                    "name": "find_ecotaxa_samples_in_region",
                    "args": {
                        "zone_name": "Baie de Baffin",
                        "instrument": "Loki",
                        "date_range": {"from": "2024-01-01", "to": "2024-12-31"},
                    },
                },
            ],
            "forbidden_tools": [
                "find_ecotaxa_projects",
                "find_ecotaxa_projects_in_region",
                "query_ecotaxa",
                "run_pandas",
                "run_graph",
            ],
            "forbidden_tool_args": [
                {"name": "find_ecotaxa_samples_in_region", "args": ["polygon_wkt"]},
            ],
            "category": "instrument_routing",
        },
    },
    {
        "id": "EX-32-cache-status",
        "inputs": {
            "question": (
                "Le cache EcoTaxa est-il à jour ? Combien de samples sont "
                "indexés ?"
            )
        },
        "outputs": {
            "expected_sequence": ["get_ecotaxa_cache_status"],
            "required_tool_args": [
                {"name": "get_ecotaxa_cache_status", "args": {}},
            ],
            "forbidden_tools": [
                "find_ecotaxa_samples_in_region",
                "find_ecotaxa_projects_in_region",
                "list_ecotaxa_projects",
                "query_ecotaxa",
                "run_pandas",
                "run_graph",
            ],
            "category": "cache_status",
        },
    },
    {
        "id": "EX-33-sample-metadata-raw",
        "inputs": {
            "question": (
                "Donne-moi les métadonnées brutes du sample EcoTaxa "
                "14853000001 (identifiants, station, volume filtré, free "
                "fields), pas les V/P/D/U."
            )
        },
        "outputs": {
            "expected_sequence": ["get_ecotaxa_sample"],
            "required_tool_args": [
                {
                    "name": "get_ecotaxa_sample",
                    "args": {"sample_id": 14853000001},
                },
            ],
            "forbidden_tools": [
                "summarize_ecotaxa_sample",
                "summarize_ecotaxa_samples",
                "summarize_ecotaxa_sample_deployment",
                "query_ecotaxa_sample",
                "query_ecotaxa",
                "run_pandas",
                "run_graph",
            ],
            "category": "sample_metadata_raw",
        },
    },
    {
        "id": "EX-34-query-ecotaxa-explicit-download",
        "inputs": {
            "question": (
                "Charge tout le projet EcoTaxa 14853 dans la session, j'ai "
                "besoin des objets pour les manipuler ensuite."
            )
        },
        "outputs": {
            "expected_sequence": ["query_ecotaxa"],
            "required_tool_args": [
                {
                    "name": "query_ecotaxa",
                    "args": {"project_id": 14853},
                },
            ],
            "forbidden_tools": [
                "summarize_ecotaxa_project",
                "summarize_ecotaxa_projects",
                "preview_ecotaxa_project",
                "export_ecotaxa_samples",
                "find_ecotaxa_samples_in_region",
                "run_pandas",
                "run_graph",
            ],
            "category": "explicit_download",
        },
    },
    {
        "id": "EX-35-query-ecotaxa-sample-explicit",
        "inputs": {
            "question": (
                "Exporte le sample EcoTaxa 14853000001 dans la session, "
                "j'ai besoin de tous ses objets."
            )
        },
        "outputs": {
            "expected_sequence": ["query_ecotaxa_sample"],
            "required_tool_args": [
                {
                    "name": "query_ecotaxa_sample",
                    "args": {"sample_id": 14853000001},
                },
            ],
            "forbidden_tools": [
                "query_ecotaxa",
                "export_ecotaxa_samples",
                "summarize_ecotaxa_sample",
                "summarize_ecotaxa_samples",
                "get_ecotaxa_sample",
                "run_pandas",
                "run_graph",
            ],
            "category": "explicit_sample_download",
        },
    },
    {
        "id": "EX-36-clarification-scope-present",
        "inputs": {
            "question": (
                "Parmi les samples présents, lesquels contiennent le plus de "
                "copépodes ?"
            )
        },
        "outputs": {
            "expected_sequence": [],
            "required_tool_args": [],
            "forbidden_tools": [
                "find_ecotaxa_samples_in_region",
                "find_ecotaxa_observations",
                "find_ecotaxa_projects_in_region",
                "summarize_ecotaxa_samples",
                "count_ecotaxa_taxa",
                "query_ecotaxa",
                "run_pandas",
                "run_graph",
            ],
            "final_answer_contains": ["?"],
            "category": "clarification_scope",
        },
    },
    {
        "id": "EX-37-synthesis-winner-named",
        "inputs": {
            "question": (
                "Quel projet a le plus de samples parmi les projets EcoTaxa "
                "14853, 2331 et 4042 ? Donne-moi le projet gagnant cité "
                "explicitement, pas juste un tableau."
            )
        },
        "outputs": {
            "expected_sequence": ["load_skill", "summarize_ecotaxa_projects"],
            "required_tool_args": [
                {
                    "name": "load_skill",
                    "args": {"skill_name": "ecotaxa_navigation"},
                },
                {
                    "name": "summarize_ecotaxa_projects",
                    "args": {"project_ids": [14853, 2331, 4042]},
                },
            ],
            "forbidden_tools": ["query_ecotaxa", "run_pandas", "run_graph"],
            "final_answer_contains": ["14853"],
            "category": "synthesis_winner",
        },
    },
    {
        "id": "EX-38-multi-turn-followup-sample-reuse",
        "inputs": {
            "turns": [
                {
                    "question": (
                        "Résume les samples EcoTaxa 14853000001, "
                        "14853000002 et 14853000003 avant de choisir "
                        "lesquels exporter."
                    )
                },
                {
                    "question": (
                        "Parmi ceux-là, lesquels contiennent le plus "
                        "d'objets ?"
                    )
                },
            ]
        },
        "outputs": {
            "expected_sequence": [
                "load_skill",
                "summarize_ecotaxa_samples",
                "summarize_ecotaxa_samples",
            ],
            "required_tool_args": [
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
            "forbidden_tools": [
                "find_ecotaxa_samples_in_region",
                "find_ecotaxa_observations",
                "find_ecotaxa_projects_in_region",
                "query_ecotaxa",
                "run_pandas",
                "run_graph",
            ],
            "final_answer_contains": ["14853000003"],
            "category": "multi_turn_followup",
        },
    },
    {
        "id": "EX-39-export-failed-live-loop",
        "inputs": {
            "question": (
                "Charge le projet EcoTaxa 999999 dans la session — j'en ai "
                "besoin pour mes analyses."
            )
        },
        "outputs": {
            "expected_sequence": ["query_ecotaxa"],
            "required_tool_args": [
                {
                    "name": "query_ecotaxa",
                    "args": {"project_id": 999999},
                },
            ],
            "forbidden_tools": [
                "find_ecotaxa_samples_in_region",
                "find_ecotaxa_observations",
                "run_pandas",
                "run_graph",
            ],
            "final_answer_contains": ["999999"],
            "category": "export_failed_live",
        },
    },
]


def _filter_cases(case_ids: str | None) -> list[dict[str, Any]]:
    if not case_ids:
        env_ids = os.getenv("EVAL_CASE_IDS")
        if env_ids:
            wanted = {item.strip() for item in env_ids.split(",") if item.strip()}
            return [case for case in EXTRA_CASES if case["id"] in wanted]
        return EXTRA_CASES
    wanted = {item.strip() for item in case_ids.split(",") if item.strip()}
    return [case for case in EXTRA_CASES if case["id"] in wanted]


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
        f"Running {len(cases)} extra EcoTaxa eval case(s) "
        f"in {len(batches)} batch(es)."
    )
    print(
        "Settings: "
        f"tokens={args.output_tokens}, concurrency={args.max_concurrency}, "
        f"case_delay={args.case_delay}, retry_delay={args.retry_delay}, "
        f"max_attempts={args.max_attempts}, batch_size={args.batch_size or 'all'}"
    )

    if args.list_cases:
        print("\n=== Extra EcoTaxa exploration cases ===")
        for case in cases:
            outputs = case["outputs"]
            sequence = " -> ".join(str(step) for step in outputs.get("expected_sequence", []))
            print(f"- {case['id']} [{outputs.get('category', 'uncategorized')}]")
            inputs = case["inputs"]
            if "turns" in inputs:
                for idx, turn in enumerate(inputs["turns"], start=1):
                    print(f"  turn {idx}: {turn['question']}")
            else:
                print(f"  question: {inputs['question']}")
            print(f"  expected: {sequence or 'none'}")
            forbidden = outputs.get("forbidden_tools", [])
            if forbidden:
                print(f"  forbidden: {', '.join(forbidden)}")
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
            run_fn=_run_case_dispatch,
            evaluators=[
                evaluator_trajectory_subsequence,
                evaluator_forbidden_tools_absent,
                evaluator_required_tool_args_present,
                evaluator_forbidden_tool_args_absent,
                evaluator_final_answer_contains,
            ],
            dataset_name=f"{DATASET_NAME}{suffix}",
            experiment_prefix=f"ecotaxa-exploration-extra{suffix}",
            metadata={
                "suite": "ecotaxa-exploration-extra",
                "model": os.getenv("LLM_MODEL", "openai/gpt-5.4-mini"),
                "max_concurrency": args.max_concurrency,
                "batch": batch_index,
                "batches_total": len(batches),
            },
            max_concurrency=args.max_concurrency,
        )
        rows.extend(batch_rows)

    print("\n=== Combined score summary ===")
    print_scores(rows, score_keys=SCORE_KEYS, threshold=args.threshold)


if __name__ == "__main__":
    main()
