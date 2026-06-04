"""Dedicated multi-turn graph evals for clarification -> answer -> generation."""
from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import scripts.evals.run_copepod_lean_eval as lean_eval
from scripts.evals.copepod.fixtures import (
    ECOTAXA_UVP5_ENRICHED,
    NEOLABS_TAXON_AMUNDSEN_CTD,
    stage_fixture,
)


@dataclass
class MultiTurnGraphScenario:
    slug: str
    fixtures: list[Path]
    initial_user_message_template: str
    clarification_reply: str
    expect_first_reply_mentions: list[str] = field(default_factory=list)
    expect_second_reply_mentions: list[str] = field(default_factory=list)
    forbidden_second_reply_terms: list[str] = field(default_factory=list)
    expect_tools_called: list[str] = field(default_factory=list)


MULTITURN_SCENARIOS: list[MultiTurnGraphScenario] = [
    MultiTurnGraphScenario(
        slug="uvp_enriched_after_validation_clarification",
        fixtures=[ECOTAXA_UVP5_ENRICHED],
        initial_user_message_template=(
            "Voici un fichier UVP enrichi.\n"
            "Fichier : {paths}\n"
            "Fais un graphique de ecopart_temperature_degC en fonction de object_depth — les colonnes sont confirmées.\n"
            "Donne un plan puis le code Python."
        ),
        clarification_reply="Exclure les annotations non confirmées.",
        expect_first_reply_mentions=[
            "inclure",
            "exclure",
            "annotations non confirm",
            "validation",
        ],
        expect_second_reply_mentions=[
            "**Plan**",
            "```python",
            "ecopart_temperature_degC",
            "object_depth",
            "python",
        ],
        forbidden_second_reply_terms=[
            "inclure ou exclure",
            "annotations non confirmées ?",
            "quel statut de validation",
        ],
        expect_tools_called=["inspect_and_report", "graph_readiness"],
    ),
    MultiTurnGraphScenario(
        slug="neolabs_ctd_after_validation_clarification",
        fixtures=[NEOLABS_TAXON_AMUNDSEN_CTD],
        initial_user_message_template=(
            "Voici une table NeoLabs enrichie avec la CTD Amundsen.\n"
            "Fichier : {paths}\n"
            "Fais un graphique de Total abundance (ind./m3 depth vol) en fonction de "
            "amundsen_temperature_degC_nearest — les colonnes sont confirmées.\n"
            "Donne un plan puis le code Python."
        ),
        clarification_reply="Exclure les annotations non confirmées.",
        expect_first_reply_mentions=[
            "inclure",
            "exclure",
            "annotations non confirm",
            "validation",
        ],
        expect_second_reply_mentions=[
            "**Plan**",
            "```python",
            "Total abundance (ind./m3 depth vol)",
            "amundsen_temperature_degC_nearest",
            "python",
        ],
        forbidden_second_reply_terms=[
            "inclure ou exclure",
            "annotations non confirmées ?",
            "quel statut de validation",
        ],
        expect_tools_called=["inspect_and_report", "graph_readiness"],
    ),
]


def _result(name: str, passed: bool, detail: str, metadata: dict | None = None) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail, "metadata": metadata or {}}


def _run_multiturn_scenario(
    scenario: MultiTurnGraphScenario,
    tools: dict[str, Any],
    model: str,
    completion_fn: Callable[..., Any],
) -> list[dict]:
    session_id = f"lean-mt-{scenario.slug}-{uuid.uuid4().hex[:6]}"
    staged_paths: list[str] = []
    for fixture in scenario.fixtures:
        info = stage_fixture(session_id, fixture)
        staged_paths.append(info["local_path"])

    initial_user_message = scenario.initial_user_message_template.format(
        paths=", ".join(f"`{p}`" for p in staged_paths)
    )

    lean_eval._vprint(f"\n{'=' * 60}")
    lean_eval._vprint(f"MULTITURN SCENARIO: {scenario.slug}")
    lean_eval._vprint(f"fixtures: {[f.name for f in scenario.fixtures]}")
    lean_eval._vprint(f"{'=' * 60}")

    messages = [
        {"role": "system", "content": lean_eval._build_system_message(session_id)},
        {"role": "user", "content": initial_user_message},
    ]
    call_tool = lean_eval._make_call_tool(tools, session_id)

    first_reply, first_tools = lean_eval._run_turn(messages, call_tool, model, completion_fn)
    lean_eval._vprint(f"  first-turn tools called: {first_tools}")
    lean_eval._vprint(f"  first-turn reply snippet: {first_reply[:800]!r}")

    messages.append({"role": "user", "content": scenario.clarification_reply})
    second_reply, second_tools = lean_eval._run_turn(messages, call_tool, model, completion_fn)
    lean_eval._vprint(f"  second-turn tools called: {second_tools}")
    lean_eval._vprint(f"  second-turn reply snippet: {second_reply[:800]!r}")

    all_tools = [*first_tools, *second_tools]
    results: list[dict] = []

    if scenario.expect_tools_called:
        called_set = set(all_tools)
        hit = [t for t in scenario.expect_tools_called if t in called_set]
        results.append(_result(
            f"{scenario.slug}_expected_tool_called",
            len(hit) > 0,
            f"expected_any={scenario.expect_tools_called} called={all_tools} hit={hit}",
            {"tool_calls": all_tools},
        ))

    if scenario.expect_first_reply_mentions:
        first_lower = first_reply.lower()
        found = [w for w in scenario.expect_first_reply_mentions if w.lower() in first_lower]
        results.append(_result(
            f"{scenario.slug}_first_turn_requested_expected_clarification",
            len(found) >= min(2, len(scenario.expect_first_reply_mentions)),
            f"required_any_2_of={scenario.expect_first_reply_mentions} found={found}",
            {"reply_snippet": first_reply[:300]},
        ))

    if scenario.expect_second_reply_mentions:
        second_lower = second_reply.lower()
        found = [w for w in scenario.expect_second_reply_mentions if w.lower() in second_lower]
        results.append(_result(
            f"{scenario.slug}_second_turn_generated_expected_content",
            len(found) >= min(2, len(scenario.expect_second_reply_mentions)),
            f"required_any_2_of={scenario.expect_second_reply_mentions} found={found}",
            {"reply_snippet": second_reply[:300]},
        ))

    for term in scenario.forbidden_second_reply_terms:
        results.append(_result(
            f"{scenario.slug}_second_turn_no_forbidden_{term}",
            term.lower() not in second_reply.lower(),
            f"term '{term}' {'absent' if term.lower() not in second_reply.lower() else 'present'}",
            {},
        ))

    if lean_eval._VERBOSE:
        for result in results:
            status = "PASS" if result["passed"] else "FAIL"
            print(f"  {status}  {result['name']}", flush=True)
            print(f"       {result['detail']}", flush=True)

    return results


def run_multiturn_graph_happy_path_eval(
    *,
    scenario_slugs: list[str] | None = None,
    completion_fn: Callable[..., Any] | None = None,
) -> dict:
    completion_fn = completion_fn or lean_eval._default_completion
    tools = lean_eval._load_tools()
    model = lean_eval.settings.LLM_MODEL

    scenarios = MULTITURN_SCENARIOS
    if scenario_slugs:
        wanted = {s.strip() for s in scenario_slugs if s.strip()}
        scenarios = [s for s in MULTITURN_SCENARIOS if s.slug in wanted]
        if not scenarios:
            available = [s.slug for s in MULTITURN_SCENARIOS]
            raise ValueError(f"No scenarios matched {sorted(wanted)!r}. Available: {available}")

    all_results: list[dict] = []
    for scenario in scenarios:
        all_results.extend(_run_multiturn_scenario(scenario, tools, model, completion_fn))

    passed = sum(1 for r in all_results if r["passed"])
    return {
        "mode": "lean-multiturn",
        "model": model,
        "passed": passed == len(all_results),
        "passed_count": passed,
        "total_count": len(all_results),
        "results": all_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the dedicated multi-turn graph happy-path eval pack."
    )
    parser.add_argument("--scenarios", default="", help="Comma-separated slugs from the multi-turn pack.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true", help="Stream tool calls and checks in real time.")
    args = parser.parse_args()

    if args.verbose:
        lean_eval._VERBOSE = True

    slugs = [s.strip() for s in args.scenarios.split(",") if s.strip()] or None
    report = run_multiturn_graph_happy_path_eval(scenario_slugs=slugs)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"copepod graph happy-path multi-turn eval ({report['model']})\n")
        for result in report["results"]:
            status = "PASS" if result["passed"] else "FAIL"
            print(f"{status} {result['name']}")
            print(f"     {result['detail']}")
        print()
        print(f"{report['passed_count']}/{report['total_count']} passed")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
