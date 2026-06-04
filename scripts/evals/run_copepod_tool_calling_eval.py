"""Tool-calling eval — vérifie que le LLM appelle le bon tool pour chaque type de question.

Chaque scénario définit :
  expected_tools  — au moins un de ces tools doit apparaître dans les appels
  forbidden_tools — aucun de ces tools ne doit être appelé

Scores Langfuse émis par scénario (tag: tool-calling-eval) :
  tool_called_correctly   1.0 si tous les expected_tools ont été appelés
  no_spurious_calls       1.0 si aucun forbidden_tool appelé
  scenario_pass           1.0 si les deux sont à 1.0
"""
from __future__ import annotations

import argparse
import json
import os
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
from scripts.evals.run_copepod_lean_eval import (
    _build_system_message,
    _load_tools,
    _make_call_tool,
    _run_turn,
    _tool_specs,
)


def _default_completion(**kwargs):
    """Completion compatible OpenAI direct + OpenRouter (préfixe openrouter/)."""
    import os as _os
    from openai import OpenAI

    model: str = kwargs.get("model", "")
    api_base = _os.getenv("LLM_API_BASE") or _os.getenv("OPENAI_API_BASE") or ""
    api_key = _os.getenv("LLM_API_KEY") or _os.getenv("OPENAI_API_KEY") or ""
    timeout = float(_os.getenv("COPEPOD_LIVE_OPENAI_TIMEOUT_SECONDS", "120"))

    # LiteLLM ajoute le préfixe "openrouter/" — l'API OpenRouter veut juste "openai/..."
    if model.startswith("openrouter/"):
        model = model[len("openrouter/"):]
        kwargs = {**kwargs, "model": model}

    client_kwargs: dict = {"timeout": timeout, "max_retries": 0}
    if api_base:
        client_kwargs["base_url"] = api_base
    if api_key:
        client_kwargs["api_key"] = api_key

    return OpenAI(**client_kwargs).chat.completions.create(**kwargs, max_completion_tokens=4000)
from scripts.evals.copepod.fixtures import (
    AMUNDSEN_CTD,
    ECOTAXA_SMALL as ECOTAXA,
    ECOPART,
    NEOLABS_TAXON,
    stage_fixture,
)


# ── Langfuse helpers ───────────────────────────────────────────────────────────

def _lf_create_trace(scenario_slug: str, session_id: str) -> str | None:
    try:
        from core.copepod_observability import _configure_local_langfuse_host, should_enable_langfuse
        if not should_enable_langfuse():
            return None
        _configure_local_langfuse_host()
        from langfuse import Langfuse
        lf = Langfuse()
        trace = lf.trace(
            name=f"tool-calling-eval/{scenario_slug}",
            session_id=f"eval-tool-calling:{session_id}",
            tags=["tool-calling-eval"],
            metadata={"scenario": scenario_slug},
        )
        lf.flush()
        return trace.id
    except Exception:
        return None


def _lf_write_score(trace_id: str, name: str, value: float, comment: str | None = None) -> None:
    try:
        import urllib.request as _req
        from base64 import b64encode
        pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        sk = os.getenv("LANGFUSE_SECRET_KEY", "")
        host = os.getenv("LANGFUSE_HOST_LOCAL", "http://localhost:3001")
        if not pk or not sk:
            return
        auth = b64encode(f"{pk}:{sk}".encode()).decode()
        payload: dict = {"traceId": trace_id, "name": name, "value": value}
        if comment:
            payload["comment"] = comment
        data = json.dumps(payload).encode()
        req = _req.Request(
            f"{host}/api/public/scores",
            data=data,
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            method="POST",
        )
        with _req.urlopen(req, timeout=5):
            pass
    except Exception:
        pass


def _lf_flush() -> None:
    try:
        from langfuse import Langfuse
        Langfuse().flush()
    except Exception:
        pass


# ── Scenarios ──────────────────────────────────────────────────────────────────

@dataclass
class ToolCallingScenario:
    slug: str
    user_message_template: str        # supporte {paths} si fichier nécessaire
    expected_tools: list[str]         # au moins 1 de ceux-ci doit être appelé
    forbidden_tools: list[str] = field(default_factory=list)
    fixtures: list[Path] = field(default_factory=list)
    description: str = ""


SCENARIOS: list[ToolCallingScenario] = [
    # ── describe_column ────────────────────────────────────────────────────────
    ToolCallingScenario(
        slug="describe_column_acq_pixel",
        description="Question directe sur une colonne → describe_column requis, pas d'inspect_file",
        user_message_template="Que signifie la colonne acq_pixel dans les données EcoTaxa ?",
        expected_tools=["describe_column"],
        forbidden_tools=["inspect_file"],
    ),
    ToolCallingScenario(
        slug="describe_column_object_feret",
        description="Colonne morphométrique → describe_column, pas d'inspect_file",
        user_message_template="Explique-moi la colonne object_feret.",
        expected_tools=["describe_column"],
        forbidden_tools=["inspect_file"],
    ),
    ToolCallingScenario(
        slug="describe_multiple_columns",
        description="Plusieurs colonnes dans une seule question → describe_column appelé",
        user_message_template="Quelles sont les définitions de object_major et acq_pixel ?",
        expected_tools=["describe_column"],
        forbidden_tools=["inspect_file"],
    ),
    # ── list_available_sources ─────────────────────────────────────────────────
    ToolCallingScenario(
        slug="list_sources_on_request",
        description="Question sur les sources disponibles → list_available_sources",
        user_message_template="Quelles sources de données copépodes sont disponibles pour mon projet ?",
        expected_tools=["list_available_sources"],
        forbidden_tools=["inspect_file"],
    ),
    # ── describe_source ────────────────────────────────────────────────────────
    ToolCallingScenario(
        slug="describe_source_ecotaxa",
        description="Demande de description d'une source → describe_source",
        user_message_template="Décris la source EcoTaxa UVP5 de la campagne Amundsen 2018.",
        expected_tools=["describe_source", "list_available_sources"],
        forbidden_tools=["inspect_file"],
    ),
    # ── inspect_file ───────────────────────────────────────────────────────────
    ToolCallingScenario(
        slug="inspect_file_on_upload",
        description="Fichier chargé + demande d'inspection → inspect_file requis",
        user_message_template=(
            "J'ai chargé un fichier EcoTaxa.\n"
            "Fichier : {paths}\n"
            "Regarde ce fichier et dis-moi ce qu'il contient."
        ),
        expected_tools=["inspect_file"],
        fixtures=[ECOTAXA],
    ),
    ToolCallingScenario(
        slug="inspect_and_roles_on_upload",
        description="Inspection + rôles colonnes → inspect_file ET infer_column_roles",
        user_message_template=(
            "Voici un fichier de données.\n"
            "Fichier : {paths}\n"
            "Inspecte-le et identifie les rôles des colonnes."
        ),
        expected_tools=["inspect_file", "infer_column_roles"],
        fixtures=[ECOTAXA],
    ),
    # ── check_column_for_calc ──────────────────────────────────────────────────
    ToolCallingScenario(
        slug="check_calc_on_ecopart_file",
        description="Fichier EcoPart + demande de concentration → inspect + roles + check_column_for_calc",
        user_message_template=(
            "J'ai un fichier EcoPart UVP5.\n"
            "Fichier : {paths}\n"
            "Peux-tu vérifier si le calcul de concentration est faisable avec ce fichier ?"
        ),
        expected_tools=["inspect_file", "check_column_for_calc"],
        fixtures=[ECOPART],
    ),
    # ── unknown column — le tool doit quand même être appelé ──────────────────
    ToolCallingScenario(
        slug="describe_unknown_column",
        description="Colonne inconnue → describe_column doit être appelé (jamais inventer)",
        user_message_template="Que signifie la colonne sample_nets dans les données NeoLabs ?",
        expected_tools=["describe_column"],
        forbidden_tools=["inspect_file"],
    ),
]


# ── Runner ─────────────────────────────────────────────────────────────────────

def _result(name: str, passed: bool, detail: str, metadata: dict | None = None) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail, "metadata": metadata or {}}


def _run_scenario(
    scenario: ToolCallingScenario,
    tools: dict[str, Any],
    model: str,
    completion_fn: Callable[..., Any],
) -> tuple[list[dict], str | None]:
    """Run one scenario. Returns (results, lf_trace_id)."""
    session_id = f"tc-{scenario.slug}-{uuid.uuid4().hex[:8]}"

    # Stage fixtures
    staged_paths: list[str] = []
    for fixture in scenario.fixtures:
        info = stage_fixture(session_id, fixture)
        staged_paths.append(info["local_path"])

    user_message = scenario.user_message_template.format(
        paths=", ".join(f"`{p}`" for p in staged_paths)
    )

    # Create Langfuse trace before LLM call so tool spans attach to it
    trace_id = _lf_create_trace(scenario.slug, session_id)
    saved_trace_id = os.environ.get("COPEPOD_EVAL_LF_TRACE_ID")
    if trace_id:
        os.environ["COPEPOD_EVAL_LF_TRACE_ID"] = trace_id

    try:
        messages = [
            {"role": "system", "content": _build_system_message(session_id)},
            {"role": "user", "content": user_message},
        ]
        call_tool = _make_call_tool(tools, session_id)
        _, tool_names_called = _run_turn(messages, call_tool, model, completion_fn)
    finally:
        if saved_trace_id is None:
            os.environ.pop("COPEPOD_EVAL_LF_TRACE_ID", None)
        else:
            os.environ["COPEPOD_EVAL_LF_TRACE_ID"] = saved_trace_id

    # ── Checks ────────────────────────────────────────────────────────────────
    results: list[dict] = []

    called_set = set(tool_names_called)

    # expected_tools : au moins 1 doit avoir été appelé
    expected_hit = [t for t in scenario.expected_tools if t in called_set]
    expected_pass = len(expected_hit) > 0
    results.append(_result(
        f"{scenario.slug}_tool_called_correctly",
        expected_pass,
        f"expected={scenario.expected_tools} called={tool_names_called} hit={expected_hit}",
        {"tool_calls": tool_names_called},
    ))

    # forbidden_tools : aucun ne doit avoir été appelé
    spurious = [t for t in scenario.forbidden_tools if t in called_set]
    no_spurious = len(spurious) == 0
    results.append(_result(
        f"{scenario.slug}_no_spurious_calls",
        no_spurious,
        f"forbidden={scenario.forbidden_tools} spurious={spurious}",
        {"tool_calls": tool_names_called},
    ))

    scenario_pass = expected_pass and no_spurious
    results.append(_result(
        f"{scenario.slug}_pass",
        scenario_pass,
        f"tool_called={expected_pass} no_spurious={no_spurious}",
        {},
    ))

    # ── Langfuse scores ───────────────────────────────────────────────────────
    if trace_id:
        _lf_write_score(trace_id, "tool_called_correctly", 1.0 if expected_pass else 0.0,
                        f"expected={scenario.expected_tools} hit={expected_hit}")
        _lf_write_score(trace_id, "no_spurious_calls", 1.0 if no_spurious else 0.0,
                        f"spurious={spurious}")
        _lf_write_score(trace_id, "scenario_pass", 1.0 if scenario_pass else 0.0)

    return results, trace_id


def run_tool_calling_eval(
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
            raise ValueError(
                f"Aucun scénario correspondant à {sorted(wanted)!r}. "
                f"Disponibles : {[s.slug for s in SCENARIOS]}"
            )

    all_results: list[dict] = []
    trace_ids: list[str] = []

    for scenario in scenarios:
        results, trace_id = _run_scenario(scenario, tools, model, completion_fn)
        all_results.extend(results)
        if trace_id:
            trace_ids.append(trace_id)

    _lf_flush()

    passed = sum(1 for r in all_results if r["passed"])
    return {
        "mode": "tool_calling",
        "model": model,
        "passed": passed == len(all_results),
        "passed_count": passed,
        "total_count": len(all_results),
        "langfuse_trace_ids": trace_ids,
        "results": all_results,
    }


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Tool-calling eval pour l'agent copépodes.")
    parser.add_argument(
        "--scenarios",
        default="",
        help=(
            "Slugs séparés par des virgules. Disponibles : "
            + ", ".join(s.slug for s in SCENARIOS)
        ),
    )
    parser.add_argument("--json", action="store_true", help="Sortie JSON brute.")
    parser.add_argument("--list", action="store_true", help="Lister les scénarios disponibles.")
    args = parser.parse_args()

    if args.list:
        print("Scénarios disponibles :")
        for s in SCENARIOS:
            print(f"  {s.slug:<40} — {s.description}")
        return 0

    slugs = [s.strip() for s in args.scenarios.split(",") if s.strip()] or None
    report = run_tool_calling_eval(scenario_slugs=slugs)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"tool-calling eval ({report['model']})\n")
        for r in report["results"]:
            status = "PASS" if r["passed"] else "FAIL"
            print(f"  {status}  {r['name']}")
            print(f"        {r['detail']}")
        print()
        print(f"{report['passed_count']}/{report['total_count']} checks passed")
        if report["langfuse_trace_ids"]:
            print(f"\nLangfuse traces : {len(report['langfuse_trace_ids'])} enregistrées")
            for tid in report["langfuse_trace_ids"]:
                print(f"  http://localhost:3001/trace/{tid}")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
