#!/usr/bin/env python3
"""Run a bounded OGSL agent trajectory evaluation in LangSmith."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from langsmith import Client

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import make_agent  # noqa: E402
from scripts.evals.run_agent_source_enrichment_eval import (  # noqa: E402
    _clear_thread,
    _dataset_snapshot,
    _run_turn,
)


DATASET_NAME = "copepod-ogsl-enrichment-trajectory-v1"
EXPERIMENT_PREFIX = "ogsl-enrichment-agent"
EVAL_MAX_OUTPUT_TOKENS = "1000"
DEFAULT_INPUTS = {
    "records": [
        {
            "station": "02M",
            "sample_date": "2022-10-09T22:03:37Z",
            "abundance": 120,
        }
    ],
    "prompt": (
        "Enrichis ce fichier avec les profils OGSL pour les stations présentes, "
        "en utilisant la colonne sample_date pour le temps. Charge PRES et TE90, "
        "conserve la table brute et crée la table enrichie standard."
    ),
}
DEFAULT_OUTPUTS = {
    "expected_trajectory": [
        "load_file",
        "query_ogsl",
    ],
    "expected_station_column": "station",
    "expected_time_column": "sample_date",
    "expected_source": "ogsl",
    "expected_derived_source": "ogsl_enrichment",
    "expected_rows": 1,
}


def _ensure_dataset(client: Client, dataset_name: str) -> None:
    if client.has_dataset(dataset_name=dataset_name):
        examples = list(client.list_examples(dataset_name=dataset_name, limit=1))
        if examples:
            client.update_example(
                examples[0].id,
                inputs=DEFAULT_INPUTS,
                outputs=DEFAULT_OUTPUTS,
                metadata={"case": "ogsl-station-02m-bounded"},
            )
            return
    else:
        client.create_dataset(
            dataset_name,
            description=(
                "One bounded OGSL trajectory case using a real ismerSgdeCtd "
                "station and deterministic code evaluators."
            ),
            metadata={"type": "trajectory", "source": "ogsl"},
        )

    client.create_examples(
        dataset_name=dataset_name,
        examples=[{
            "inputs": DEFAULT_INPUTS,
            "outputs": DEFAULT_OUTPUTS,
            "metadata": {"case": "ogsl-station-02m-bounded"},
        }],
    )


async def _run_target_async(inputs: dict[str, Any]) -> dict[str, Any]:
    thread_id = f"langsmith-ogsl-eval-{uuid.uuid4().hex[:10]}"
    _clear_thread(thread_id)
    records = list(inputs["records"])

    with tempfile.TemporaryDirectory(prefix="ogsl-langsmith-eval-") as tmp:
        input_path = Path(tmp) / "ogsl_eval_stations.csv"
        pd.DataFrame(records).to_csv(input_path, index=False)
        before_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()

        agent = make_agent(thread_id, user_id="langsmith-ogsl-eval")
        config = {
            "configurable": {"thread_id": thread_id},
            "metadata": {
                "eval": "ogsl-source-enrichment",
                "dataset": DATASET_NAME,
            },
            "recursion_limit": 30,
        }
        load_calls, _ = await _run_turn(
            agent,
            config,
            f"Charge ce fichier sans le modifier : {input_path}",
            "load",
        )
        enrichment_calls, final_response = await _run_turn(
            agent,
            config,
            str(inputs["prompt"]),
            "enrichment",
        )
        calls = load_calls + enrichment_calls
        datasets = _dataset_snapshot(thread_id)
        after_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()

    result = {
        "trajectory": [call.name for call in calls],
        "tool_calls": [
            {
                "name": call.name,
                "arguments": call.arguments,
                "result_preview": call.result_preview,
            }
            for call in calls
        ],
        "datasets": datasets,
        "final_response": final_response,
        "raw_file_unchanged": before_hash == after_hash,
    }
    _clear_thread(thread_id)
    return result


def run_target(inputs: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_run_target_async(inputs))


def trajectory_subsequence(outputs: dict, reference_outputs: dict) -> dict:
    expected = reference_outputs["expected_trajectory"]
    actual = outputs.get("trajectory", [])
    cursor = 0
    for tool_name in actual:
        if cursor < len(expected) and tool_name == expected[cursor]:
            cursor += 1
    return {
        "key": "ogsl_trajectory",
        "score": cursor / len(expected),
        "comment": f"Expected {expected}; observed {actual}",
    }


def ogsl_query_integrity(outputs: dict, reference_outputs: dict) -> dict:
    query_call = next(
        (
            call
            for call in outputs.get("tool_calls", [])
            if call.get("name") == "query_ogsl"
        ),
        None,
    )
    expected_column = reference_outputs["expected_station_column"]
    expected_time_column = reference_outputs["expected_time_column"]
    passed = bool(
        query_call
        and query_call.get("arguments", {}).get("station_column")
        == expected_column
        and query_call.get("arguments", {}).get("time_column")
        == expected_time_column
        and "stations" not in query_call.get("arguments", {})
    )
    return {
        "key": "ogsl_query_integrity",
        "score": int(passed),
        "comment": json.dumps(query_call, ensure_ascii=False)[:1000],
    }


def ogsl_dataset_created(outputs: dict, reference_outputs: dict) -> dict:
    expected_source = reference_outputs["expected_source"]
    expected_derived_source = reference_outputs["expected_derived_source"]
    expected_rows = reference_outputs["expected_rows"]
    datasets = outputs.get("datasets", [])
    raw_matches = [
        dataset for dataset in datasets if dataset.get("source") == expected_source
    ]
    derived_matches = [
        dataset
        for dataset in datasets
        if dataset.get("source") == expected_derived_source
    ]
    derived_columns = (
        set(derived_matches[0].get("columns", [])) if derived_matches else set()
    )
    passed = bool(
        raw_matches
        and raw_matches[0].get("rows", 0) > 0
        and derived_matches
        and derived_matches[0].get("rows") == expected_rows
        and {
            "ogsl_match_status",
            "ogsl_time_delta_min",
        } <= derived_columns
    )
    return {
        "key": "ogsl_dataset_created",
        "score": int(passed),
        "comment": json.dumps(
            raw_matches + derived_matches,
            ensure_ascii=False,
        )[:1000],
    }


def source_file_preserved(outputs: dict) -> dict:
    passed = outputs.get("raw_file_unchanged") is True
    return {
        "key": "source_file_preserved",
        "score": int(passed),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=DATASET_NAME)
    parser.add_argument("--experiment-prefix", default=EXPERIMENT_PREFIX)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.environ["LLM_MAX_OUTPUT_TOKENS"] = EVAL_MAX_OUTPUT_TOKENS
    client = Client()
    _ensure_dataset(client, args.dataset)
    if args.dry_run:
        print(json.dumps({"dataset": args.dataset, "status": "ready"}))
        return 0

    results = client.evaluate(
        run_target,
        data=args.dataset,
        evaluators=[
            trajectory_subsequence,
            ogsl_query_integrity,
            ogsl_dataset_created,
            source_file_preserved,
        ],
        experiment_prefix=args.experiment_prefix,
        description="Bounded OGSL acquisition and join trajectory evaluation.",
        max_concurrency=1,
        num_repetitions=1,
        metadata={
            "models": [str(__import__("os").getenv("LLM_MODEL", "default"))],
            "tools": ["load_file", "query_ogsl"],
            "source": "ogsl:ismerSgdeCtd",
        },
    )
    dataframe = results.to_pandas()
    columns = [
        column
        for column in dataframe.columns
        if column.startswith("feedback.") or column in {"error"}
    ]
    print(dataframe.loc[:, columns].to_string(index=False))
    return int(bool(dataframe.get("error", pd.Series(dtype=object)).notna().any()))


if __name__ == "__main__":
    raise SystemExit(main())
