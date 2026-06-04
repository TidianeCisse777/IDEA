"""Tool-calling eval — vérifie que le LLM appelle le bon tool pour chaque type de question.

Couvre les 20 fonctions injectées dans le sandbox Python de l'agent.

Chaque scénario définit :
  expected_tools  — au moins un de ces tools doit apparaître dans les appels
  forbidden_tools — aucun de ces tools ne doit être appelé

Scores Langfuse émis par scénario (tag: tool-calling-eval) :
  tool_called_correctly   1.0 si au moins un expected_tool a été appelé
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
)
from scripts.evals.copepod.fixtures import (
    AMUNDSEN_CTD,
    ECOTAXA_SMALL as ECOTAXA,
    ECOTAXA_UVP5,
    ECOPART,
    NEOLABS_TAXON,
    stage_fixture,
)


# ── Completion override (OpenRouter support) ───────────────────────────────────

def _default_completion(**kwargs):
    """Completion compatible OpenAI direct + OpenRouter (préfixe openrouter/)."""
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


# ── Full tool specs — toutes les 20 fonctions ──────────────────────────────────

def _all_tool_specs() -> list[dict]:
    obj = {"type": "object", "additionalProperties": True}
    arr_obj = {"type": "array", "items": obj}
    arr_str = {"type": "array", "items": {"type": "string"}}

    def fn(name, description, properties, required):
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

    str_p = {"type": "string"}
    int_p = {"type": "integer"}
    bool_p = {"type": "boolean"}

    return [
        # ── copepod_data ──────────────────────────────────────────────────────
        fn("inspect_file",
           "Inspecte un fichier CSV/TSV/Excel et retourne forme, dtypes, encodage, type de source.",
           {"file_path": str_p, "sample_rows": int_p}, ["file_path"]),

        fn("infer_column_roles",
           "Propose des rôles sémantiques pour les colonnes d'un fichier inspecté.",
           {"columns": arr_obj, "metadata": obj}, ["columns"]),

        fn("collect_column_definitions",
           "Interroge le RAG pour toutes les colonnes d'un rapport d'inspection.",
           {"file_report": obj, "session_id": str_p}, ["file_report"]),

        fn("format_inspect_report",
           "Génère un rapport Markdown à partir du résultat d'inspect_file.",
           {"file_report": obj, "column_definitions": arr_obj}, ["file_report"]),

        fn("summarize_understanding",
           "Produit le résumé structuré de compréhension des données (Mode Plan).",
           {"inspect_report": obj, "role_report": obj, "column_definitions": arr_obj},
           ["inspect_report", "role_report"]),

        fn("inspect_and_report",
           "Pipeline atomique : inspecte plusieurs fichiers et retourne rapports + résumé croisé.",
           {"file_paths": arr_str, "session_id": str_p}, ["file_paths"]),

        fn("get_inspection_report",
           "Récupère le rapport d'inspection complet d'un fichier depuis le stockage hors-contexte.",
           {"filename": str_p}, ["filename"]),

        fn("graph_readiness",
           "Valide les colonnes et données avant de produire un graphique.",
           {"file_report": obj, "required_columns": arr_str,
            "column_definitions": arr_obj, "user_request": str_p,
            "graph_type": str_p, "validation_status": obj},
           ["file_report"]),

        fn("profile_join_keys",
           "Profile la cardinalité et l'expansion de lignes avant une jointure.",
           {"left": obj, "right": obj, "left_key": str_p, "right_key": str_p},
           ["left", "right", "left_key", "right_key"]),

        fn("install_copepod_join_guard",
           "Installe le guard de jointure sur pandas pour éviter les jointures non profilées.",
           {}, []),

        # ── copepod_columns ───────────────────────────────────────────────────
        fn("describe_column",
           "Retourne la définition, l'unité et les notes critiques d'une colonne via le RAG.",
           {"column_name": str_p, "source_hint": str_p, "session_id": str_p},
           ["column_name"]),

        fn("check_column_for_calc",
           "Vérifie si les rôles sémantiques nécessaires à un calcul sont présents.",
           {"column_roles": obj, "calculation": str_p, "session_id": str_p},
           ["column_roles", "calculation"]),

        # ── copepod_sources_meta ──────────────────────────────────────────────
        fn("list_available_sources",
           "Liste les sources de données copépodes connues et leur statut.",
           {"auth_token": str_p, "session_id": str_p}, []),

        fn("describe_source",
           "Retourne les métadonnées complètes d'une source de données.",
           {"source_id": str_p, "session_id": str_p}, ["source_id"]),

        fn("plan_remote_source_request",
           "Normalise une demande de données distantes en plan structuré.",
           {"request_text": str_p, "source_hint": str_p, "session_id": str_p},
           ["request_text"]),

        # ── copepod_remote_sources ────────────────────────────────────────────
        fn("fetch_remote_source_dataset",
           "Télécharge un jeu de données depuis une source distante et le persiste localement.",
           {"session_key": str_p, "source_id": str_p, "parameters": obj,
            "output_filename": str_p},
           ["session_key", "source_id", "parameters"]),

        # ── copepod_rag ───────────────────────────────────────────────────────
        fn("query_copepod_knowledge_base",
           "Recherche dans la base de connaissances copépodes (colonnes, méthodes, espèces).",
           {"question": str_p, "session_id": str_p, "top_k": int_p},
           ["question"]),

        # ── copepod_uvp_metrics ───────────────────────────────────────────────
        fn("resolve_uvp_m5_m6_inputs",
           "Identifie les colonnes nécessaires aux métriques UVP MCA m5/m6.",
           {"columns": arr_obj, "metadata": obj, "session_id": str_p},
           ["columns"]),

        fn("calculate_uvp_m5_m6",
           "Calcule les métriques UVP MCA m5 (densité copépodes) et m6 (grands copépodes).",
           {"data": obj, "resolved_inputs": obj, "session_id": str_p},
           ["data"]),

        # ── copepod_taxonomy ──────────────────────────────────────────────────
        fn("lookup_worms_taxonomy",
           "Interroge l'API WoRMS pour la classification taxonomique d'un organisme marin.",
           {"query": str_p, "include_children": bool_p,
            "marine_only": bool_p, "session_id": str_p},
           ["query"]),
    ]


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


# ── Runner override utilisant _all_tool_specs ──────────────────────────────────

def _run_turn_full(
    messages: list[dict],
    call_tool: Callable[[str, dict], Any],
    model: str,
    completion_fn: Callable[..., Any],
    max_rounds: int = 20,
) -> tuple[str, list[str]]:
    """Identique à _run_turn mais avec les specs complètes (20 tools)."""
    specs = _all_tool_specs()
    tool_names_called: list[str] = []
    last_content = ""

    for _ in range(max_rounds):
        response = completion_fn(
            model=model,
            messages=messages,
            tools=specs,
            tool_choice="auto",
            temperature=float(os.getenv("LLM_TEMPERATURE", settings.LLM_TEMPERATURE)),
        )
        if hasattr(response, "choices"):
            msg_obj = response.choices[0].message
            msg = msg_obj.model_dump(exclude_none=True) if hasattr(msg_obj, "model_dump") else dict(msg_obj)
        else:
            msg = response["choices"][0]["message"]
        messages.append(msg)
        last_content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            return last_content, tool_names_called

        for raw in tool_calls:
            call = raw.model_dump(exclude_none=True) if hasattr(raw, "model_dump") else dict(raw)
            fn_info = call.get("function") or {}
            name = fn_info.get("name") or ""
            tool_names_called.append(name)
            try:
                args = json.loads(fn_info.get("arguments") or "{}")
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


# ── Scenarios ──────────────────────────────────────────────────────────────────

@dataclass
class ToolCallingScenario:
    slug: str
    user_message_template: str
    expected_tools: list[str]
    forbidden_tools: list[str] = field(default_factory=list)
    fixtures: list[Path] = field(default_factory=list)
    description: str = ""


SCENARIOS: list[ToolCallingScenario] = [
    # ── describe_column ────────────────────────────────────────────────────────
    ToolCallingScenario(
        slug="describe_column_acq_pixel",
        description="Question directe sur colonne → describe_column, pas d'inspect_file",
        user_message_template="Que signifie la colonne acq_pixel dans les données EcoTaxa ?",
        expected_tools=["describe_column"],
        forbidden_tools=["inspect_file"],
    ),
    ToolCallingScenario(
        slug="describe_column_object_feret",
        description="Colonne morphométrique → describe_column",
        user_message_template="Explique-moi la colonne object_feret.",
        expected_tools=["describe_column"],
        forbidden_tools=["inspect_file"],
    ),
    ToolCallingScenario(
        slug="describe_multiple_columns",
        description="Plusieurs colonnes → describe_column appelé au moins une fois",
        user_message_template="Quelles sont les définitions de object_major et acq_pixel ?",
        expected_tools=["describe_column"],
        forbidden_tools=["inspect_file"],
    ),
    ToolCallingScenario(
        slug="describe_unknown_column",
        description="Colonne inconnue → describe_column quand même (ne pas inventer)",
        user_message_template="Que signifie la colonne sample_nets dans les données NeoLabs ?",
        expected_tools=["describe_column"],
        forbidden_tools=["inspect_file"],
    ),
    # ── inspect_file + infer_column_roles ──────────────────────────────────────
    ToolCallingScenario(
        slug="inspect_file_on_upload",
        description="Fichier chargé + demande d'inspection → inspect_file",
        user_message_template=(
            "J'ai chargé un fichier EcoTaxa.\nFichier : {paths}\n"
            "Regarde ce fichier et dis-moi ce qu'il contient."
        ),
        expected_tools=["inspect_file"],
        fixtures=[ECOTAXA],
    ),
    ToolCallingScenario(
        slug="inspect_and_roles_on_upload",
        description="Inspection + rôles → inspect_file ET infer_column_roles",
        user_message_template=(
            "Voici un fichier de données.\nFichier : {paths}\n"
            "Inspecte-le et identifie les rôles des colonnes."
        ),
        expected_tools=["inspect_file", "infer_column_roles"],
        fixtures=[ECOTAXA],
    ),
    # ── inspect_and_report ─────────────────────────────────────────────────────
    ToolCallingScenario(
        slug="inspect_and_report_pipeline",
        description="Demande de rapport complet → inspect_and_report (pipeline atomique)",
        user_message_template=(
            "Génère un rapport d'inspection complet pour ce fichier.\nFichier : {paths}"
        ),
        expected_tools=["inspect_and_report", "inspect_file"],
        fixtures=[ECOTAXA],
    ),
    # ── summarize_understanding ────────────────────────────────────────────────
    ToolCallingScenario(
        slug="summarize_understanding_after_inspect",
        description="Après inspection → summarize_understanding pour résumé structuré",
        user_message_template=(
            "J'ai chargé ce fichier.\nFichier : {paths}\n"
            "Inspecte-le et produis un résumé structuré de compréhension des données."
        ),
        expected_tools=["inspect_file", "summarize_understanding"],
        fixtures=[ECOTAXA],
    ),
    # ── collect_column_definitions ─────────────────────────────────────────────
    ToolCallingScenario(
        slug="collect_definitions_after_inspect",
        description="Après inspection → collect_column_definitions pour définir toutes les colonnes",
        user_message_template=(
            "Voici un fichier EcoPart.\nFichier : {paths}\n"
            "Inspecte le fichier et cherche la définition RAG de toutes ses colonnes."
        ),
        expected_tools=["inspect_file", "collect_column_definitions"],
        fixtures=[ECOPART],
    ),
    # ── list_available_sources + describe_source ───────────────────────────────
    ToolCallingScenario(
        slug="list_sources_on_request",
        description="Question sur sources disponibles → list_available_sources",
        user_message_template="Quelles sources de données copépodes sont disponibles ?",
        expected_tools=["list_available_sources"],
        forbidden_tools=["inspect_file"],
    ),
    ToolCallingScenario(
        slug="describe_source_ecotaxa",
        description="Demande de description d'une source → describe_source",
        user_message_template="Décris la source EcoTaxa UVP5 de la campagne Amundsen 2018.",
        expected_tools=["describe_source", "list_available_sources"],
        forbidden_tools=["inspect_file"],
    ),
    # ── plan_remote_source_request ─────────────────────────────────────────────
    ToolCallingScenario(
        slug="plan_remote_source_request_bio_oracle",
        description="Demande de données Bio-ORACLE → plan_remote_source_request",
        user_message_template=(
            "Je veux récupérer les données de température de surface Bio-ORACLE "
            "pour le scénario SSP126 dans ma zone d'étude."
        ),
        expected_tools=["plan_remote_source_request", "list_available_sources"],
        forbidden_tools=["inspect_file"],
    ),
    # ── query_copepod_knowledge_base ───────────────────────────────────────────
    ToolCallingScenario(
        slug="query_rag_on_biology_question",
        description="Question de biologie / méthode → query_copepod_knowledge_base",
        user_message_template=(
            "Comment calcule-t-on le biovolume d'un copépode à partir des images UVP5 ?"
        ),
        expected_tools=["query_copepod_knowledge_base", "describe_column"],
        forbidden_tools=["inspect_file"],
    ),
    # ── lookup_worms_taxonomy ──────────────────────────────────────────────────
    ToolCallingScenario(
        slug="worms_taxonomy_lookup",
        description="Question taxonomique → lookup_worms_taxonomy",
        user_message_template=(
            "Quelle est la classification complète de Calanus hyperboreus dans WoRMS ?"
        ),
        expected_tools=["lookup_worms_taxonomy"],
        forbidden_tools=["inspect_file"],
    ),
    # ── resolve_uvp_m5_m6_inputs + calculate_uvp_m5_m6 ───────────────────────
    ToolCallingScenario(
        slug="resolve_uvp_inputs_on_ecotaxa",
        description="Fichier EcoTaxa UVP5 + demande m5/m6 → resolve_uvp_m5_m6_inputs",
        user_message_template=(
            "J'ai un fichier EcoTaxa UVP5 joint à EcoPart.\nFichier : {paths}\n"
            "Vérifie si les métriques UVP m5 et m6 sont calculables."
        ),
        expected_tools=["resolve_uvp_m5_m6_inputs", "inspect_file"],
        fixtures=[ECOTAXA_UVP5],
    ),
    # ── graph_readiness ────────────────────────────────────────────────────────
    ToolCallingScenario(
        slug="graph_readiness_before_plot",
        description="Demande de graphique → graph_readiness avant de produire le plot",
        user_message_template=(
            "Voici un fichier EcoTaxa.\nFichier : {paths}\n"
            "Je veux faire un graphique de la profondeur vs object_major. "
            "Vérifie que les colonnes nécessaires sont disponibles."
        ),
        expected_tools=["graph_readiness", "inspect_file"],
        fixtures=[ECOTAXA],
    ),
    # ── profile_join_keys ─────────────────────────────────────────────────────
    ToolCallingScenario(
        slug="profile_join_before_merge",
        description="Jointure EcoTaxa + EcoPart → profile_join_keys avant merge",
        user_message_template=(
            "J'ai deux fichiers à joindre : EcoTaxa et EcoPart.\n"
            "Fichiers : {paths}\n"
            "Profile les clés de jointure obj_orig_id / Profile avant de croiser les deux."
        ),
        expected_tools=["profile_join_keys", "inspect_file"],
        fixtures=[ECOTAXA, ECOPART],
    ),
    # ── install_copepod_join_guard ─────────────────────────────────────────────
    ToolCallingScenario(
        slug="install_join_guard_before_join",
        description="Demande de jointure → install_copepod_join_guard d'abord",
        user_message_template=(
            "Je vais joindre plusieurs fichiers. "
            "Active le guard de jointure pour m'assurer que toutes les jointures sont profilées."
        ),
        expected_tools=["install_copepod_join_guard"],
        forbidden_tools=["inspect_file"],
    ),
    # ── get_inspection_report ──────────────────────────────────────────────────
    ToolCallingScenario(
        slug="get_inspection_report_by_name",
        description="Demande de rapport d'un fichier précédent → get_inspection_report",
        user_message_template=(
            "Montre-moi le rapport d'inspection complet du fichier ecotaxa_sample_50.tsv "
            "que j'ai inspecté plus tôt."
        ),
        expected_tools=["get_inspection_report"],
        forbidden_tools=["inspect_file"],
    ),
    # ── check_column_for_calc (multi-step) ────────────────────────────────────
    ToolCallingScenario(
        slug="check_calc_on_ecopart_file",
        description="EcoPart + demande concentration → inspect + check_column_for_calc",
        user_message_template=(
            "J'ai un fichier EcoPart UVP5.\nFichier : {paths}\n"
            "Peux-tu vérifier si le calcul de concentration est faisable avec ce fichier ?"
        ),
        expected_tools=["inspect_file", "check_column_for_calc"],
        fixtures=[ECOPART],
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
    session_id = f"tc-{scenario.slug}-{uuid.uuid4().hex[:8]}"

    staged_paths: list[str] = []
    for fixture in scenario.fixtures:
        info = stage_fixture(session_id, fixture)
        staged_paths.append(info["local_path"])

    user_message = scenario.user_message_template.format(
        paths=", ".join(f"`{p}`" for p in staged_paths)
    )

    trace_id = _lf_create_trace(scenario.slug, session_id)
    saved = os.environ.get("COPEPOD_EVAL_LF_TRACE_ID")
    if trace_id:
        os.environ["COPEPOD_EVAL_LF_TRACE_ID"] = trace_id

    try:
        messages = [
            {"role": "system", "content": _build_system_message(session_id)},
            {"role": "user", "content": user_message},
        ]
        call_tool = _make_call_tool(tools, session_id)
        _, tool_names_called = _run_turn_full(messages, call_tool, model, completion_fn)
    finally:
        if saved is None:
            os.environ.pop("COPEPOD_EVAL_LF_TRACE_ID", None)
        else:
            os.environ["COPEPOD_EVAL_LF_TRACE_ID"] = saved

    called_set = set(tool_names_called)
    results: list[dict] = []

    expected_hit = [t for t in scenario.expected_tools if t in called_set]
    expected_pass = len(expected_hit) > 0
    results.append(_result(
        f"{scenario.slug}_tool_called_correctly",
        expected_pass,
        f"expected={scenario.expected_tools} called={tool_names_called} hit={expected_hit}",
        {"tool_calls": tool_names_called},
    ))

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
    parser = argparse.ArgumentParser(description="Tool-calling eval pour l'agent copépodes (20 tools).")
    parser.add_argument(
        "--scenarios", default="",
        help="Slugs séparés par virgules. Laisser vide pour tout lancer.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--list", action="store_true", help="Lister les scénarios disponibles.")
    args = parser.parse_args()

    if args.list:
        print(f"Scénarios disponibles ({len(SCENARIOS)}) :")
        for s in SCENARIOS:
            print(f"  {s.slug:<45} — {s.description}")
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
            print(f"\nLangfuse : {len(report['langfuse_trace_ids'])} traces enregistrées")
            for tid in report["langfuse_trace_ids"]:
                print(f"  http://localhost:3001/trace/{tid}")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
