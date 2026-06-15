#!/usr/bin/env python3
"""Live agent evaluation for Bio-ORACLE and OGSL file enrichment."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from langchain_core.messages import ToolMessage

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import make_agent  # noqa: E402
from tools.session_store import default_store  # noqa: E402


BIO_PROMPT = """Enrichis ce fichier station par station avec la température
Bio-ORACLE baseline en surface. Utilise les latitude/longitude propres à chaque
ligne. Ne réutilise pas une valeur de zone pour toutes les stations. Exécute
l'enrichissement maintenant et indique le nom de la nouvelle table créée."""

OGSL_PROMPT = """Enrichis ce fichier avec les profils OGSL disponibles pour ces
stations. Récupère la source OGSL, conserve le fichier brut intact, puis effectue
une jointure explicite avec une nouvelle table dérivée. Exécute le flux maintenant
et indique les clés de jointure, les lignes non appariées et la provenance."""


@dataclass
class ToolCall:
    turn: str
    name: str
    arguments: dict[str, Any]
    result_preview: str | None = None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clear_thread(thread_id: str) -> None:
    for key in default_store.keys(thread_id):
        default_store.clear(key)


async def _run_turn(agent, config: dict, prompt: str, turn: str) -> tuple[list[ToolCall], str]:
    calls: list[ToolCall] = []
    call_by_id: dict[str, ToolCall] = {}
    final_text = ""
    async for update in agent.astream(
        {"messages": [{"role": "user", "content": prompt}]},
        config=config,
        stream_mode="updates",
    ):
        for node, state in update.items():
            messages = state.get("messages", []) if isinstance(state, dict) else []
            if node == "agent" and messages:
                message = messages[-1]
                content = getattr(message, "content", "") or ""
                if content:
                    final_text = str(content)
                for raw_call in getattr(message, "tool_calls", []) or []:
                    call = ToolCall(
                        turn=turn,
                        name=str(raw_call.get("name")),
                        arguments=dict(raw_call.get("args") or {}),
                    )
                    calls.append(call)
                    if raw_call.get("id"):
                        call_by_id[str(raw_call["id"])] = call
            elif node == "tools":
                for message in messages:
                    if not isinstance(message, ToolMessage):
                        continue
                    call = call_by_id.get(str(message.tool_call_id))
                    if call is not None:
                        call.result_preview = str(message.content)[:1000]
    return calls, final_text


def _dataset_snapshot(thread_id: str) -> list[dict[str, Any]]:
    datasets = []
    for key in default_store.keys(f"{thread_id}:dataset:"):
        entry = default_store.get(key) or {}
        dataframe = entry.get("df")
        datasets.append({
            "key": key,
            "variable_name": (entry.get("meta") or {}).get("variable_name"),
            "source": (entry.get("meta") or {}).get("source"),
            "rows": len(dataframe) if isinstance(dataframe, pd.DataFrame) else None,
            "columns": list(dataframe.columns) if isinstance(dataframe, pd.DataFrame) else [],
        })
    return datasets


def _evaluate_bio(
    calls: list[ToolCall],
    datasets: list[dict],
    input_records: list[dict[str, Any]],
) -> dict:
    names = [call.name for call in calls]
    coupled = [item for item in datasets if item["source"] == "bio_oracle_coupling"]
    coupling_call = next(
        (call for call in calls if call.name == "couple_zooplankton_bio_oracle"),
        None,
    )
    try:
        submitted_rows = json.loads(
            coupling_call.arguments.get("rows_json", "[]") if coupling_call else "[]"
        )
    except json.JSONDecodeError:
        submitted_rows = []

    def coordinates(rows):
        parsed = set()
        invalid = False
        for row in rows:
            try:
                parsed.add((float(row["latitude"]), float(row["longitude"])))
            except (KeyError, TypeError, ValueError):
                invalid = True
        return parsed, invalid

    source_coordinates, source_coordinates_invalid = coordinates(input_records)
    submitted_coordinates, submitted_coordinates_invalid = coordinates(submitted_rows)
    source_stations = {str(row["station"]) for row in input_records}
    submitted_stations = {
        str(row["station"]) for row in submitted_rows if "station" in row
    }
    source_columns = set(input_records[0]) if input_records else set()
    coupled_columns = set(coupled[0]["columns"]) if coupled else set()
    checks = {
        "loads_file": "load_file" in names,
        "reads_actual_rows": "run_pandas" in names,
        "uses_per_station_tool": "couple_zooplankton_bio_oracle" in names,
        "avoids_zone_tool": "query_bio_oracle_zones" not in names,
        "uses_source_coordinates": (
            not source_coordinates_invalid
            and not submitted_coordinates_invalid
            and submitted_coordinates == source_coordinates
        ),
        "uses_source_station_ids": submitted_stations == source_stations,
        "creates_coupled_table": len(coupled) == 1,
        "preserves_row_count": bool(
            coupled and coupled[0]["rows"] == len(input_records)
        ),
        "preserves_source_columns": source_columns <= coupled_columns,
    }
    return {"passed": all(checks.values()), "checks": checks}


def _evaluate_ogsl(calls: list[ToolCall], datasets: list[dict]) -> dict:
    names = [call.name for call in calls]
    ogsl_source_tools = {"query_ogsl", "fetch_remote_source_dataset"}
    checks = {
        "loads_file": "load_file" in names,
        "calls_ogsl_source": bool(ogsl_source_tools.intersection(names)),
        "loads_environmental_join_skill": any(
            call.name == "load_skill"
            and call.arguments.get("skill_name") == "environmental_join"
            for call in calls
        ),
        "executes_join": "run_pandas" in names,
        "creates_ogsl_dataset": any(item["source"] == "ogsl" for item in datasets),
    }
    missing_capability = not checks["calls_ogsl_source"]
    return {
        "passed": all(checks.values()),
        "missing_capability": missing_capability,
        "checks": checks,
    }


async def run_scenario(name: str, input_path: Path) -> dict:
    thread_id = f"eval-source-enrichment-{name}-{uuid.uuid4().hex[:8]}"
    _clear_thread(thread_id)
    before_hash = _sha256(input_path)
    input_dataframe = pd.read_csv(input_path)
    input_rows = len(input_dataframe)
    input_records = input_dataframe.to_dict(orient="records")
    agent = make_agent(thread_id, user_id="source-enrichment-eval")
    config = {
        "configurable": {"thread_id": thread_id},
        "metadata": {"eval": "source-enrichment", "scenario": name},
        "recursion_limit": 30,
    }
    load_calls, load_response = await _run_turn(
        agent,
        config,
        f"Charge ce fichier sans le modifier : {input_path}",
        "load",
    )
    prompt = BIO_PROMPT if name == "bio-oracle" else OGSL_PROMPT
    enrich_calls, enrich_response = await _run_turn(
        agent, config, prompt, "enrichment"
    )
    calls = load_calls + enrich_calls
    datasets = _dataset_snapshot(thread_id)
    evaluation = (
        _evaluate_bio(calls, datasets, input_records)
        if name == "bio-oracle"
        else _evaluate_ogsl(calls, datasets)
    )
    evaluation["raw_file_unchanged"] = _sha256(input_path) == before_hash
    evaluation["passed"] = evaluation["passed"] and evaluation["raw_file_unchanged"]
    return {
        "scenario": name,
        "thread_id": thread_id,
        "input_file": str(input_path),
        "input_rows": input_rows,
        "tool_calls": [asdict(call) for call in calls],
        "datasets": datasets,
        "load_response": load_response,
        "final_response": enrich_response,
        "evaluation": evaluation,
    }


async def _main(args) -> int:
    scenarios = (
        ["bio-oracle", "ogsl"] if args.scenario == "all" else [args.scenario]
    )
    reports = [await run_scenario(name, args.file.resolve()) for name in scenarios]
    payload = {"reports": reports}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(report["evaluation"]["passed"] for report in reports) else 1


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        choices=["all", "bio-oracle", "ogsl"],
        default="all",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=ROOT / "tests/fixtures/source_enrichment_stations.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output/evals/agent_source_enrichment.json",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(parse_args())))
