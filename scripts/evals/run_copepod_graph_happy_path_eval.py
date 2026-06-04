"""Dedicated lean-eval entrypoint for graph happy-path scenarios.

This keeps graph-generation scenarios isolated from the main lean eval manifest
until they are stable enough to be merged into the default pack.
"""
from __future__ import annotations

import argparse
import json

import scripts.evals.run_copepod_lean_eval as lean_eval
from scripts.evals.copepod.fixtures import (
    ECOTAXA_UVP5,
    ECOTAXA_UVP5_ENRICHED,
    NEOLABS_TAXON_AMUNDSEN_CTD,
)
from scripts.evals.copepod_lean_scenarios_graph_happy_path import (
    build_graph_happy_path_scenarios,
)


GRAPH_HAPPY_PATH_SCENARIOS = build_graph_happy_path_scenarios(
    LeanScenario=lean_eval.LeanScenario,
    ECOTAXA_UVP5=ECOTAXA_UVP5,
    ECOTAXA_UVP5_ENRICHED=ECOTAXA_UVP5_ENRICHED,
    NEOLABS_TAXON_AMUNDSEN_CTD=NEOLABS_TAXON_AMUNDSEN_CTD,
)


def run_graph_happy_path_eval(
    *,
    scenario_slugs: list[str] | None = None,
    completion_fn=None,
) -> dict:
    original_scenarios = lean_eval.SCENARIOS
    try:
        lean_eval.SCENARIOS = [*original_scenarios, *GRAPH_HAPPY_PATH_SCENARIOS]
        return lean_eval.run_lean_eval(
            scenario_slugs=scenario_slugs,
            completion_fn=completion_fn,
        )
    finally:
        lean_eval.SCENARIOS = original_scenarios


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the dedicated copepod graph happy-path lean eval pack."
    )
    parser.add_argument(
        "--scenarios",
        default="",
        help="Comma-separated slugs from the graph happy-path pack.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Stream tool calls and checks in real time.",
    )
    args = parser.parse_args()

    if args.verbose:
        lean_eval._VERBOSE = True

    slugs = [s.strip() for s in args.scenarios.split(",") if s.strip()] or None
    report = run_graph_happy_path_eval(scenario_slugs=slugs)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"copepod graph happy-path eval ({report['model']})\n")
        for result in report["results"]:
            status = "PASS" if result["passed"] else "FAIL"
            print(f"{status} {result['name']}")
            print(f"     {result['detail']}")
        print()
        print(f"{report['passed_count']}/{report['total_count']} passed")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
