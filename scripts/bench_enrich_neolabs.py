"""Bench parallel enrich on a NeoLabs-like file (slice).

Usage:
    PYTHONPATH=. python scripts/bench_enrich_neolabs.py [n_rows] [--vars=v1,v2,..] [--only=bio|amundsen|both] [--file=path]
    n_rows=0 → full file
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

from tools.amundsen_sources import make_amundsen_tools
from tools.bio_oracle_sources import make_bio_oracle_tools
from tools.session_store import default_store as _store

CSV_PATH = Path("data/neolabs/neolabs_sample.csv")
THREAD_ID = "bench-neolabs"


def _read_table(path: Path) -> pd.DataFrame:
    sep = "\t" if path.suffix.lower() == ".tsv" else ","
    df = pd.read_csv(path, sep=sep)
    df.columns = [c.lower() for c in df.columns]
    return df


def _seed_session(df: pd.DataFrame) -> None:
    for key in _store.keys(THREAD_ID):
        _store.clear(key)
    _store.set(THREAD_ID, df, {"source": f"file:{CSV_PATH.name}"})


def _get_tool(tools, name):
    return next(t for t in tools if t.name == name)


def _print_method_block(text: str) -> None:
    print(f">> {text.splitlines()[0]}", flush=True)
    for line in text.splitlines():
        if line.startswith(("- Requ", "- Points", "- Statuts", "- Avertissement", "- Note", "- Bornes", "- Couverture", "  ·")):
            print(line, flush=True)


def run_amundsen(df: pd.DataFrame, max_workers: int) -> float:
    _seed_session(df)
    enrich = _get_tool(make_amundsen_tools(THREAD_ID), "enrich_with_amundsen_ctd")
    print(f"\n--- Amundsen CTD (max_workers={max_workers}) ---", flush=True)
    t0 = time.perf_counter()
    text = enrich.invoke({"max_workers": max_workers})
    elapsed = time.perf_counter() - t0
    print(f"Wall: {elapsed:.1f}s", flush=True)
    _print_method_block(text)
    return elapsed


def run_bio_oracle(df: pd.DataFrame, variables: list[str], scenarios: list[str], max_workers: int) -> float:
    _seed_session(df)
    enrich = _get_tool(make_bio_oracle_tools(THREAD_ID), "enrich_with_bio_oracle")
    print(f"\n--- Bio-ORACLE {variables} × {scenarios} (max_workers={max_workers}) ---", flush=True)
    t0 = time.perf_counter()
    text = enrich.invoke({
        "variables": variables,
        "scenarios": scenarios,
        "max_unique_queries": 100000,
        "confirmed": True,
        "max_workers": max_workers,
    })
    elapsed = time.perf_counter() - t0
    print(f"Wall: {elapsed:.1f}s", flush=True)
    _print_method_block(text)
    return elapsed


def _parse_args(argv: list[str]) -> tuple[int, list[str], list[str], str, Path]:
    n_rows = 200
    variables = ["temperature"]
    scenarios = ["baseline"]
    only = "both"
    file_path = CSV_PATH
    for arg in argv:
        if arg.startswith("--vars="):
            variables = [v.strip() for v in arg.split("=", 1)[1].split(",") if v.strip()]
        elif arg.startswith("--scenarios="):
            scenarios = [s.strip() for s in arg.split("=", 1)[1].split(",") if s.strip()]
        elif arg.startswith("--only="):
            only = arg.split("=", 1)[1]
        elif arg.startswith("--file="):
            file_path = Path(arg.split("=", 1)[1])
        elif arg.isdigit():
            n_rows = int(arg)
    return n_rows, variables, scenarios, only, file_path


def main() -> None:
    n_rows, variables, scenarios, only, file_path = _parse_args(sys.argv[1:])
    print(f"Loading {file_path} ...", flush=True)
    df = _read_table(file_path)
    if n_rows > 0:
        df = df.sample(n=min(n_rows, len(df)), random_state=42).reset_index(drop=True)
    print(f"Rows: {len(df)} | only={only} | vars={variables} | scenarios={scenarios}", flush=True)
    unique = df[["latitude", "longitude", "deployment_datetime_start", "max_sample_depth"]].drop_duplicates()
    print(f"Unique (lat,lon,time,depth): {len(unique)}", flush=True)

    a = run_amundsen(df, max_workers=8) if only in ("amundsen", "both") else None
    b = run_bio_oracle(df, variables=variables, scenarios=scenarios, max_workers=6) if only in ("bio", "both") else None

    print("\n=== Summary ===", flush=True)
    parts = [f"Rows: {len(df)}"]
    if a is not None:
        parts.append(f"Amundsen: {a:.1f}s")
    if b is not None:
        parts.append(f"Bio-ORACLE: {b:.1f}s")
    print(" | ".join(parts), flush=True)


if __name__ == "__main__":
    main()
