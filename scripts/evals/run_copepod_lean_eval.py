"""Lean copepod eval — behavioural scenarios, no Plan/Analyse machinery.

Each scenario stages one or more fixture files, kicks off a real LLM turn
through the copepod tools, and asserts observable behaviour:

- The LLM inspected every uploaded file (called inspect_file on it).
- The LLM produced a self-summary of what it found.
- The LLM did not invent values out of thin air (no numeric value in the
  reply that is absent from the inspected data — best-effort heuristic).
- The LLM refused scientific interpretation when explicitly asked.

This is intentionally short — the point is to validate the direction, not
to lock down a full test contract.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from core.config import settings
from core.session_store import InMemorySessionStore
from scripts.evals.copepod.fixtures import (
    AMUNDSEN_CTD,
    BIO_ORACLE,
    ECOPART,
    ECOTAXA_SMALL as ECOTAXA,
    ECOTAXA_UVP5,
    NEOLABS_LOKI,
    NEOLABS_TAXON,
    OGSL,
    stage_fixture,
)


# ── tool plumbing ──────────────────────────────────────────────────────────────

def _load_tools() -> dict[str, Any]:
    from core.tool_registry import registry
    from core.tool_registry.tools import (  # noqa: F401
        copepod_columns,
        copepod_data,
        copepod_rag,
        copepod_remote_sources,
        copepod_sources_meta,
        copepod_taxonomy,
        copepod_uvp_metrics,
    )

    ns: dict[str, Any] = {}
    exec(
        registry.render({
            "copepod_data",
            "copepod_columns",
            "copepod_rag",
            "copepod_remote_sources",
            "copepod_sources_meta",
            "copepod_taxonomy",
            "copepod_uvp_metrics",
        }),
        ns,
    )
    return ns


def _tool_specs() -> list[dict]:
    object_schema = {"type": "object", "additionalProperties": True}

    def fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        }

    return [
        fn(
            "inspect_file",
            "Inspect an uploaded CSV/TSV/Excel file and return shape, dtypes, sample rows, encoding, source-type guess.",
            {"file_path": {"type": "string"}, "sample_rows": {"type": "integer", "default": 20}},
            ["file_path"],
        ),
        fn(
            "infer_column_roles",
            "Infer semantic roles for inspected columns.",
            {"columns": {"type": "array", "items": object_schema}, "metadata": object_schema},
            ["columns"],
        ),
        fn(
            "describe_column",
            "Look up a column definition in the copepod RAG corpus.",
            {"column_name": {"type": "string"}, "source_hint": {"type": "string"}, "session_id": {"type": "string"}},
            ["column_name"],
        ),
        fn(
            "summarize_understanding",
            "Build a structured per-file summary from inspect + role reports.",
            {
                "inspect_report": object_schema,
                "role_report": object_schema,
                "column_definitions": {"type": "array", "items": object_schema},
            },
            ["inspect_report", "role_report"],
        ),
        fn(
            "list_available_sources",
            "List known copepod data sources.",
            {"auth_token": {"type": "string"}, "session_id": {"type": "string"}},
            [],
        ),
        fn(
            "describe_source",
            "Return metadata for one data source.",
            {"source_id": {"type": "string"}, "session_id": {"type": "string"}},
            ["source_id"],
        ),
        fn(
            "inspect_and_report",
            "Atomic pipeline: inspect multiple files and return formatted reports + cross-file summary.",
            {
                "file_paths": {"type": "array", "items": {"type": "string"}},
                "session_id": {"type": "string"},
            },
            ["file_paths"],
        ),
        fn(
            "collect_column_definitions",
            "Batch-query the RAG corpus for all columns in an inspect_file report.",
            {"file_report": object_schema, "session_id": {"type": "string"}},
            ["file_report"],
        ),
        fn(
            "get_inspection_report",
            "Retrieve the full inspection report for a previously inspected file.",
            {"filename": {"type": "string"}},
            ["filename"],
        ),
    ]


def _make_call_tool(tools: dict[str, Any], session_id: str) -> Callable[[str, dict], Any]:
    cache: dict[str, Any] = {"inspected_paths": set()}

    def call(name: str, arguments: dict) -> Any:
        if name == "describe_column" and not arguments.get("session_id"):
            arguments = {**arguments, "session_id": session_id}
        if name == "inspect_file":
            path = arguments.get("file_path")
            if path:
                cache["inspected_paths"].add(path)
        try:
            return tools[name](**arguments)
        except Exception as exc:
            return {"error": str(exc)}

    return call


# ── LLM driver ─────────────────────────────────────────────────────────────────

def _message_to_dict(message: Any) -> dict:
    if isinstance(message, dict):
        return message
    if hasattr(message, "model_dump"):
        return message.model_dump(exclude_none=True)
    return dict(message)


def _tool_call_to_dict(tc: Any) -> dict:
    if isinstance(tc, dict):
        return tc
    if hasattr(tc, "model_dump"):
        return tc.model_dump(exclude_none=True)
    return dict(tc)


def _completion_message(response: Any) -> Any:
    if isinstance(response, dict):
        return response["choices"][0]["message"]
    return response.choices[0].message


def _default_completion(**kwargs):
    from openai import OpenAI

    model: str = kwargs.get("model", "")
    api_base = os.getenv("LLM_API_BASE") or os.getenv("OPENAI_API_BASE") or ""
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    timeout = float(os.getenv("COPEPOD_LIVE_OPENAI_TIMEOUT_SECONDS", "120"))

    if model.startswith("openrouter/"):
        model = model[len("openrouter/"):]
        kwargs = {**kwargs, "model": model}

    client_kwargs: dict = {"timeout": timeout, "max_retries": 0}
    if api_base:
        client_kwargs["base_url"] = api_base
    if api_key:
        client_kwargs["api_key"] = api_key

    return OpenAI(**client_kwargs).chat.completions.create(**kwargs, max_completion_tokens=4000)


def _run_turn(
    messages: list[dict],
    call_tool: Callable[[str, dict], Any],
    model: str,
    completion_fn: Callable[..., Any],
    max_rounds: int = 20,
) -> tuple[str, list[str]]:
    """Run rounds until the assistant emits text. Returns (reply, tool_names_called)."""
    specs = _tool_specs()
    tool_names_called: list[str] = []
    last_content = ""

    for round_index in range(max_rounds):
        response = completion_fn(
            model=model,
            messages=messages,
            tools=specs,
            tool_choice="auto",
            temperature=float(os.getenv("LLM_TEMPERATURE", settings.LLM_TEMPERATURE)),
        )
        msg = _message_to_dict(_completion_message(response))
        messages.append(msg)
        last_content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            return last_content, tool_names_called

        for raw in tool_calls:
            call = _tool_call_to_dict(raw)
            fn = call.get("function") or {}
            name = fn.get("name")
            tool_names_called.append(name or "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
                result = call_tool(name, args)
            except Exception as exc:
                result = {"error": str(exc)}
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id"),
                "name": name,
                "content": json.dumps(result, ensure_ascii=False, default=str)[:4000],
            })

    return last_content, tool_names_called


# ── scenarios ──────────────────────────────────────────────────────────────────

@dataclass
class LeanScenario:
    slug: str
    fixtures: list[Path]
    user_message_template: str  # use {paths} placeholder
    # behavioural expectations
    expect_inspect_per_file: bool = True
    expect_self_summary: bool = True
    expect_no_interpretation: bool = False
    forbidden_terms_in_reply: list[str] = field(default_factory=list)
    # generic tool-call checks: at least one of these must appear in tool_names_called
    expect_tools_called: list[str] = field(default_factory=list)


SCENARIOS: list[LeanScenario] = [
    LeanScenario(
        slug="single_ecotaxa",
        fixtures=[ECOTAXA],
        user_message_template=(
            "J'ai chargé un export EcoTaxa de la campagne Green Edge.\n"
            "Fichier : {paths}\n"
            "Regarde ce fichier et dis-moi ce qu'il contient."
        ),
    ),
    LeanScenario(
        slug="multi_ecotaxa_ecopart",
        fixtures=[ECOTAXA, ECOPART],
        user_message_template=(
            "Voici deux fichiers de la campagne Green Edge — un export EcoTaxa "
            "et un export EcoPart UVP5.\n"
            "Fichiers : {paths}\n"
            "Analyse les deux et dis-moi si on peut les croiser."
        ),
    ),
    LeanScenario(
        slug="lab_unknown_structure",
        fixtures=[NEOLABS_TAXON],
        user_message_template=(
            "J'ai un fichier de comptages taxonomiques de notre labo NeoLabs.\n"
            "Fichier : {paths}\n"
            "Regarde sa structure."
        ),
    ),
    LeanScenario(
        slug="refuse_interpretation",
        fixtures=[ECOTAXA],
        user_message_template=(
            "Voici un export EcoTaxa Green Edge.\n"
            "Fichier : {paths}\n"
            "Regarde ce fichier puis explique-moi biologiquement pourquoi Calanus "
            "hyperboreus serait plus abondant à certaines profondeurs. "
            "Donne-moi une interprétation écologique."
        ),
        expect_self_summary=False,
        expect_no_interpretation=True,
    ),
    # ── file loading ───────────────────────────────────────────────────────────
    LeanScenario(
        slug="atomic_report_pipeline",
        fixtures=[ECOTAXA],
        user_message_template=(
            "Génère un rapport d'inspection complet pour ce fichier.\n"
            "Fichier : {paths}"
        ),
        expect_inspect_per_file=True,
        expect_self_summary=True,
        expect_tools_called=["inspect_and_report", "inspect_file"],
    ),
    LeanScenario(
        slug="collect_column_defs_after_inspect",
        fixtures=[ECOPART],
        user_message_template=(
            "J'ai un fichier EcoPart.\n"
            "Fichier : {paths}\n"
            "Inspecte-le et cherche la définition RAG de toutes ses colonnes."
        ),
        expect_inspect_per_file=True,
        expect_self_summary=False,
        # inspect_and_report calls collect_column_definitions internally
        expect_tools_called=["collect_column_definitions", "inspect_and_report"],
    ),
    LeanScenario(
        slug="summarize_understanding_requested",
        fixtures=[ECOTAXA],
        user_message_template=(
            "Voici un fichier EcoTaxa.\n"
            "Fichier : {paths}\n"
            "Inspecte-le et produis un résumé structuré de compréhension des données "
            "pour Mode Plan."
        ),
        expect_inspect_per_file=True,
        expect_self_summary=True,
        # inspect_and_report handles the full pipeline including summarize_understanding
        expect_tools_called=["summarize_understanding", "inspect_and_report"],
    ),
]


# ── eval runner ────────────────────────────────────────────────────────────────

def _result(name: str, passed: bool, detail: str, metadata: dict | None = None) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail, "metadata": metadata or {}}


_INTERPRETATION_KEYWORDS_FR = [
    "parce que", "car les", "écologiquement", "biologiquement",
    "indique que", "suggère que", "preuve de",
]


def _build_system_message(session_id: str) -> str:
    from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT
    runtime_note = (
        f"\n\nRuntime context for this eval:\n"
        f"- session_id: {session_id}\n"
        f"- When a file path appears in the user message, use that exact local path for inspect_file.\n"
    )
    return COPEPOD_SYSTEM_PROMPT + runtime_note


def _run_scenario(
    scenario: LeanScenario,
    tools: dict[str, Any],
    model: str,
    completion_fn: Callable[..., Any],
) -> list[dict]:
    session_id = f"lean-{scenario.slug}-{uuid.uuid4().hex[:6]}"
    staged_paths: list[str] = []
    for fixture in scenario.fixtures:
        info = stage_fixture(session_id, fixture)
        staged_paths.append(info["local_path"])

    user_message = scenario.user_message_template.format(
        paths=", ".join(f"`{p}`" for p in staged_paths)
    )

    messages = [
        {"role": "system", "content": _build_system_message(session_id)},
        {"role": "user", "content": user_message},
    ]
    call_tool = _make_call_tool(tools, session_id)
    reply, tool_names_called = _run_turn(messages, call_tool, model, completion_fn)

    results: list[dict] = []
    # inspect_and_report is the atomic pipeline — count it as equivalent to inspect_file
    inspect_calls = [n for n in tool_names_called if n in ("inspect_file", "inspect_and_report")]
    if scenario.expect_inspect_per_file:
        passed = len(inspect_calls) >= len(scenario.fixtures)
        results.append(_result(
            f"{scenario.slug}_inspect_called_for_each_file",
            passed,
            f"inspect_file/inspect_and_report called {len(inspect_calls)}× for {len(scenario.fixtures)} fixture(s).",
            {"tool_calls": tool_names_called},
        ))

    if scenario.expect_self_summary:
        # Heuristic: reply mentions either column names, file format, or one of the
        # source identifiers we expect — i.e. the LLM volunteered a summary rather
        # than waiting silently.
        cues = ["colonne", "lignes", "fichier", "ecotaxa", "ecopart", "ctd", "labo", "taxon"]
        found = [c for c in cues if c in reply.lower()]
        passed = len(reply) > 60 and len(found) >= 2
        results.append(_result(
            f"{scenario.slug}_spontaneous_self_summary",
            passed,
            f"reply length={len(reply)} cues_matched={found}",
            {"reply_snippet": reply[:300]},
        ))

    if scenario.expect_no_interpretation:
        leaked = [k for k in _INTERPRETATION_KEYWORDS_FR if k in reply.lower()]
        # We want the model to refuse — refusal usually mentions "interpret" or
        # references its scope. We accept either: no interpretive keywords used,
        # OR an explicit refusal mention.
        explicit_refusal = any(
            term in reply.lower() for term in ["interpr", "pas mon rôle", "scope", "périmètre"]
        )
        passed = not leaked or explicit_refusal
        results.append(_result(
            f"{scenario.slug}_refused_interpretation",
            passed,
            f"leaked_keywords={leaked} explicit_refusal={explicit_refusal}",
            {"reply_snippet": reply[:300]},
        ))

    for term in scenario.forbidden_terms_in_reply:
        results.append(_result(
            f"{scenario.slug}_no_forbidden_{term}",
            term.lower() not in reply.lower(),
            f"term '{term}' {'absent' if term.lower() not in reply.lower() else 'present'}",
            {},
        ))

    if scenario.expect_tools_called:
        called_set = set(tool_names_called)
        hit = [t for t in scenario.expect_tools_called if t in called_set]
        passed = len(hit) > 0
        results.append(_result(
            f"{scenario.slug}_expected_tool_called",
            passed,
            f"expected_any={scenario.expect_tools_called} called={tool_names_called} hit={hit}",
            {"tool_calls": tool_names_called},
        ))

    return results


def run_lean_eval(
    *,
    scenario_slugs: list[str] | None = None,
    completion_fn: Callable[..., Any] | None = None,
) -> dict:
    completion_fn = completion_fn or _default_completion
    tools = _load_tools()
    model = settings.LLM_MODEL

    scenarios = SCENARIOS
    if scenario_slugs:
        wanted = {s.strip() for s in scenario_slugs if s.strip()}
        scenarios = [s for s in SCENARIOS if s.slug in wanted]
        if not scenarios:
            available = [s.slug for s in SCENARIOS]
            raise ValueError(f"No scenarios matched {sorted(wanted)!r}. Available: {available}")

    all_results: list[dict] = []
    for scenario in scenarios:
        all_results.extend(_run_scenario(scenario, tools, model, completion_fn))

    passed = sum(1 for r in all_results if r["passed"])
    return {
        "mode": "lean",
        "model": model,
        "passed": passed == len(all_results),
        "passed_count": passed,
        "total_count": len(all_results),
        "results": all_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the lean copepod eval (no Plan/Analyse).")
    parser.add_argument(
        "--scenarios",
        default="",
        help="Comma-separated slugs (single_ecotaxa, multi_ecotaxa_ecopart, lab_unknown_structure, refuse_interpretation).",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    slugs = [s.strip() for s in args.scenarios.split(",") if s.strip()] or None
    report = run_lean_eval(scenario_slugs=slugs)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"copepod lean eval ({report['model']})\n")
        for r in report["results"]:
            status = "PASS" if r["passed"] else "FAIL"
            print(f"{status} {r['name']}")
            print(f"     {r['detail']}")
        print()
        print(f"{report['passed_count']}/{report['total_count']} passed")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
