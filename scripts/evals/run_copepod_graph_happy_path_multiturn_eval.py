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
    ECOTAXA_UVP5,
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


@dataclass
class PostInspectGraphScenario:
    """Scenario where the file is uploaded and inspected in turn-1, then the user
    asks for a graph in turn-2 with vague column names (no 'les colonnes sont confirmées').

    The critical assertion: turn-2 must call ``graph_readiness`` from code.
    It must NOT produce a hand-written Plan+questions response.
    """
    slug: str
    fixtures: list[Path]
    turn1_message_template: str   # "Voici un fichier…\nFichier : {paths}\nInspecte-le."
    turn2_message: str            # "fais un profil vertical abondance et température"
    expect_turn2_tools: list[str] = field(default_factory=list)
    forbidden_turn2_terms: list[str] = field(default_factory=list)
    expect_turn2_mentions: list[str] = field(default_factory=list)


POST_INSPECT_GRAPH_SCENARIOS: list[PostInspectGraphScenario] = [
    PostInspectGraphScenario(
        slug="neolabs_graph_after_prior_inspection",
        fixtures=[NEOLABS_TAXON_AMUNDSEN_CTD],
        turn1_message_template=(
            "Voici un fichier NeoLabs CTD.\n"
            "Fichier : {paths}\n"
            "Inspecte-le."
        ),
        turn2_message=(
            "ok je vais tracer un profil vertical abondance et température"
        ),
        expect_turn2_tools=["graph_readiness"],
        forbidden_turn2_terms=[
            "quelle colonne d'abondance",
            "quelle colonne de température",
            "confirmez-vous que le profil",
            "quelle colonne",
        ],
        expect_turn2_mentions=["graph_readiness"],
    ),
    PostInspectGraphScenario(
        slug="uvp5_graph_after_prior_inspection",
        fixtures=[ECOTAXA_UVP5],
        turn1_message_template=(
            "Voici un export EcoTaxa UVP5.\n"
            "Fichier : {paths}\n"
            "Inspecte-le."
        ),
        turn2_message=(
            "fais un graphe obj_depth_min en fonction de fre_area — les colonnes sont confirmées"
        ),
        expect_turn2_tools=["graph_readiness"],
        forbidden_turn2_terms=[
            "confirmez-vous",
            "quel axe",
        ],
        expect_turn2_mentions=["graph_readiness"],
    ),
    # Column-injection stress test: vague semantic terms, no explicit column names.
    # The model must resolve them from injected column context, not from re-reading
    # the report, and call graph_readiness without asking the user to clarify.
    PostInspectGraphScenario(
        slug="uvp5_graph_vague_columns_column_injection",
        fixtures=[ECOTAXA_UVP5],
        turn1_message_template=(
            "Voici un export EcoTaxa UVP5.\n"
            "Fichier : {paths}\n"
            "Inspecte-le."
        ),
        turn2_message=(
            "trace un graphique profondeur vs surface des objets"
        ),
        expect_turn2_tools=["graph_readiness"],
        forbidden_turn2_terms=[
            "quelle colonne",
            "quel axe",
            "pouvez-vous préciser",
            "confirmez-vous",
        ],
        expect_turn2_mentions=["graph_readiness"],
    ),
]


def _build_column_context_note(session_id: str, filenames: list[str]) -> str:
    """Mirror the column injection that chat_routes does on each production turn.

    Reads structured inspection data from session_store and returns a note
    with column names so the model can call graph_readiness without re-reading
    the full markdown report.
    """
    from core.session_store import session_store as _ss
    col_lines: list[str] = []
    for fname in filenames:
        try:
            data = _ss.read_inspection_data(session_id, fname)
            if data and isinstance(data, dict):
                col_names = [
                    str(c.get("name", ""))
                    for c in (data.get("columns") or [])
                    if isinstance(c, dict) and c.get("name")
                ][:50]
                if col_names:
                    col_lines.append(f"- {fname} : {', '.join(col_names)}")
        except Exception:
            pass
    if not col_lines:
        return ""
    return (
        "\n\nInspected file columns (exact facts available for readback and graph_readiness):\n"
        + "\n".join(col_lines)
    )


def _run_post_inspect_graph_scenario(
    scenario: PostInspectGraphScenario,
    tools: dict[str, Any],
    model: str,
    completion_fn: Callable[..., Any],
) -> list[dict]:
    session_id = f"lean-pig-{scenario.slug}-{uuid.uuid4().hex[:6]}"
    staged_paths: list[str] = []
    for fixture in scenario.fixtures:
        info = stage_fixture(session_id, fixture)
        staged_paths.append(info["local_path"])

    turn1_message = scenario.turn1_message_template.format(
        paths=", ".join(f"`{p}`" for p in staged_paths)
    )

    lean_eval._vprint(f"\n{'=' * 60}")
    lean_eval._vprint(f"POST-INSPECT GRAPH SCENARIO: {scenario.slug}")
    lean_eval._vprint(f"fixtures: {[f.name for f in scenario.fixtures]}")
    lean_eval._vprint(f"{'=' * 60}")

    messages = [
        {"role": "system", "content": lean_eval._build_system_message(session_id)},
        {"role": "user", "content": turn1_message},
    ]
    call_tool = lean_eval._make_call_tool(tools, session_id)

    turn1_reply, turn1_tools = lean_eval._run_turn(messages, call_tool, model, completion_fn)
    lean_eval._vprint(f"  turn-1 tools called: {turn1_tools}")
    lean_eval._vprint(f"  turn-1 reply snippet: {turn1_reply[:400]!r}")

    # Mirror production behavior: inject column names from session_store into the
    # system message before turn-2 so the model doesn't need to re-read the report.
    filenames = [f.name for f in scenario.fixtures]
    col_note = _build_column_context_note(session_id, filenames)
    if col_note:
        messages[0] = {**messages[0], "content": messages[0]["content"] + col_note}
        lean_eval._vprint(f"  [column injection] injected {len(filenames)} file(s) into system message")

    messages.append({"role": "user", "content": scenario.turn2_message})
    turn2_reply, turn2_tools = lean_eval._run_turn(messages, call_tool, model, completion_fn)
    lean_eval._vprint(f"  turn-2 tools called: {turn2_tools}")
    lean_eval._vprint(f"  turn-2 reply snippet: {turn2_reply[:800]!r}")

    results: list[dict] = []

    # Assert: turn-1 ran inspect_and_report
    results.append(_result(
        f"{scenario.slug}_turn1_inspected",
        "inspect_and_report" in turn1_tools,
        f"turn1 tools={turn1_tools}",
        {"tool_calls": turn1_tools},
    ))

    # Assert: turn-2 called graph_readiness (not hand-written questions)
    if scenario.expect_turn2_tools:
        called_set = set(turn2_tools)
        hit = [t for t in scenario.expect_turn2_tools if t in called_set]
        results.append(_result(
            f"{scenario.slug}_turn2_called_graph_readiness",
            len(hit) > 0,
            f"expected={scenario.expect_turn2_tools} turn2_tools={turn2_tools} hit={hit}",
            {"tool_calls": turn2_tools},
        ))

    # Assert: forbidden hand-written questions absent from turn-2 reply
    turn2_lower = turn2_reply.lower()
    for term in scenario.forbidden_turn2_terms:
        results.append(_result(
            f"{scenario.slug}_turn2_no_own_question_{term[:30]}",
            term.lower() not in turn2_lower,
            f"term '{term}' {'absent' if term.lower() not in turn2_lower else 'PRESENT — model wrote its own question'}",
            {"reply_snippet": turn2_reply[:300]},
        ))

    if lean_eval._VERBOSE:
        for result in results:
            status = "PASS" if result["passed"] else "FAIL"
            print(f"  {status}  {result['name']}", flush=True)
            print(f"       {result['detail']}", flush=True)

    return results


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

    mt_scenarios = MULTITURN_SCENARIOS
    pig_scenarios = POST_INSPECT_GRAPH_SCENARIOS
    if scenario_slugs:
        wanted = {s.strip() for s in scenario_slugs if s.strip()}
        mt_scenarios = [s for s in MULTITURN_SCENARIOS if s.slug in wanted]
        pig_scenarios = [s for s in POST_INSPECT_GRAPH_SCENARIOS if s.slug in wanted]
        if not mt_scenarios and not pig_scenarios:
            available = [s.slug for s in MULTITURN_SCENARIOS] + [s.slug for s in POST_INSPECT_GRAPH_SCENARIOS]
            raise ValueError(f"No scenarios matched {sorted(wanted)!r}. Available: {available}")

    all_results: list[dict] = []
    for scenario in mt_scenarios:
        all_results.extend(_run_multiturn_scenario(scenario, tools, model, completion_fn))
    for scenario in pig_scenarios:
        all_results.extend(_run_post_inspect_graph_scenario(scenario, tools, model, completion_fn))

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
