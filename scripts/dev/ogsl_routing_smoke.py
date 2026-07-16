"""Real-agent smoke for the 4C OGSL routing rule.

Drives the real ReAct agent (real LLM, tracing off, isolated store) across
several turns and records which OGSL tool the model selects for a given table
shape. It proves the single deterministic rule of `environmental_join.md`:

- a table with a station id + sampling time -> `query_ogsl`
- a table with only latitude/longitude       -> `enrich_with_ogsl`

The OGSL remote layer is stubbed so no network call is made: the routing
decision is captured from the streamed tool calls, not from a completed fetch.

Usage:
    PYTHONPATH=. python scripts/dev/ogsl_routing_smoke.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pandas as pd


def _stub_ogsl_network() -> None:
    """Replace the OGSL remote entrypoints with fast, offline failures."""
    import tools.ogsl_sources as ogsl

    def _no_network_query(*args, **kwargs):  # pragma: no cover - smoke only
        raise RuntimeError("STUB: OGSL network disabled for routing smoke")

    def _no_network_bbox(*args, **kwargs):  # pragma: no cover - smoke only
        raise RuntimeError("STUB: OGSL network disabled for routing smoke")

    ogsl._query_ogsl = _no_network_query
    ogsl._fetch_ogsl_bbox = _no_network_bbox


def _write_fixture(rows: list[dict], name: str) -> Path:
    path = Path(tempfile.gettempdir()) / f"ogsl_smoke_{name}_{uuid.uuid4().hex[:8]}.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _drive_turn(agent, thread_id: str, question: str) -> list[tuple[str, dict]]:
    """Run one turn, returning the (tool_name, args) calls the model made."""
    from agent import repair_invalid_tool_history

    config = {"configurable": {"thread_id": thread_id}}
    repair_invalid_tool_history(agent, config)
    calls: list[tuple[str, dict]] = []
    seen = 0
    for chunk in agent.stream(
        {"messages": [{"role": "user", "content": question}]},
        config=config,
        stream_mode="values",
    ):
        messages = chunk.get("messages", [])
        for message in messages[seen:]:
            for call in getattr(message, "tool_calls", None) or []:
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "?")
                args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
                calls.append((name, dict(args or {})))
        seen = max(seen, len(messages))
    return calls


def _ogsl_tool(calls: list[tuple[str, dict]]) -> str | None:
    for name, _ in calls:
        if name in ("query_ogsl", "enrich_with_ogsl"):
            return name
    return None


def main() -> int:
    os.environ.setdefault("SESSION_STORE_DIR", tempfile.mkdtemp())
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

    _stub_ogsl_network()
    from agent import make_agent

    run_id = f"ogsl-routing-smoke-{uuid.uuid4().hex[:8]}"
    scenarios = [
        {
            "label": "station+time table",
            "rows": [
                {"station": f"ST{i:02d}", "sampledate": f"2018-07-{10 + i:02d}", "abundance": 3 * i}
                for i in range(1, 4)
            ],
            "ask": (
                "Enrichis cette table avec les données CTD OGSL (température, salinité). "
                "Les colonnes station et date sont disponibles."
            ),
            "expected": "query_ogsl",
        },
        {
            "label": "lat/lon-only table",
            "rows": [
                {"latitude": 68.0 + 0.1 * i, "longitude": -63.0 - 0.1 * i, "sampledate": f"2018-08-{10 + i:02d}", "abundance": 2 * i}
                for i in range(1, 4)
            ],
            "ask": (
                "Enrichis cette table avec les données CTD OGSL (température, salinité). "
                "Il n'y a pas d'identifiant de station, seulement latitude/longitude."
            ),
            "expected": "enrich_with_ogsl",
        },
    ]

    results = []
    for idx, sc in enumerate(scenarios):
        thread_id = f"{run_id}-{idx}"
        user_id = f"{run_id}-{idx}"
        agent = make_agent(thread_id, user_id=user_id)
        fixture = _write_fixture(sc["rows"], f"s{idx}")
        load_calls = _drive_turn(agent, thread_id, f"Charge le fichier {fixture}")
        t0 = time.monotonic()
        ogsl_calls = _drive_turn(agent, thread_id, sc["ask"])
        chosen = _ogsl_tool(ogsl_calls)
        ok = chosen == sc["expected"]
        results.append((sc["label"], sc["expected"], chosen, ok))
        print(f"\n=== Scenario {idx}: {sc['label']} ({time.monotonic() - t0:.1f}s) ===")
        print(f"  load calls : {[n for n, _ in load_calls]}")
        print(f"  turn calls : {[n for n, _ in ogsl_calls]}")
        print(f"  expected   : {sc['expected']}")
        print(f"  chosen     : {chosen}")
        print(f"  verdict    : {'PASS' if ok else 'FAIL'}")

    print("\n--- OGSL routing smoke summary ---")
    all_ok = True
    for label, expected, chosen, ok in results:
        all_ok = all_ok and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: expected {expected}, chose {chosen}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
