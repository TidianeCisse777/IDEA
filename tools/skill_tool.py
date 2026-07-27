"""Skill loader tool — charge un skill depuis le LangSmith Context Hub ou le disque."""
from __future__ import annotations

import os
from pathlib import Path

from langchain_core.tools import tool

from tools.session_store import SessionStore, default_store
from tools.skill_manifest import SkillDocument, load_skill_document, parse_skill_document
from tools.tool_result import blocked, success

try:
    from langsmith import Client as _LangSmithClient
except ImportError:
    _LangSmithClient = None  # type: ignore[assignment,misc]

SKILLS_DIR = Path(__file__).parent.parent / "agents" / "skills"

_RUNTIME_CAPSULES = {
    "graph_planner": """Plan before code. Stop on an empty selected table. Use only the explicit source variable and never invent an artifact URL. For a named geographic request, resolve/filter the exact zone first; maps use Cartopy `station_map` or `abundance_environment_map`, never `kind:\"map\"`/`kind:\"scatter\"`. Aggregate NeoLabs taxon rows to samples before station/sample plots. graph_writer is already active — go straight to run_graph, never call load_skill.""",
    "graph_writer": """Stop on empty data; use only the named active table and validate plot_df after filtering. Use Agg matplotlib, readable labelled axes/units, legend or labelled colourbar, and never invent an artifact URL. Define graph_contract and neutral graph_explanation. Keep identifiers as strings. Never produce a graph where exploratory and confirmed values are visually indistinguishable. Maps use Cartopy GeoAxes, longitude/latitude position mapping, coastlines, aggregation of coincident points, and the exact zone polygon from `zone_polygons` via Cartopy ShapelyFeature; never draw a bbox rectangle. Vertical profiles invert only depth. Return only the image emitted by run_graph.""",
    "ecotaxa_navigation": """EcoTaxa is authorized: use the local SQLite cache at sample level unless objects are explicitly requested. Inspect available cache schema before relying on a column; issue one read-only SELECT statement without a semicolon. Reuse the active selection/table for follow-ups. Never infer missing identifiers or use an external source unless explicitly requested. For maps, use the exact persisted query result and the active graph rules.""",
}


def _runtime_capsule(skill_name: str, document: SkillDocument) -> str:
    """Small persistent execution rules; the complete skill remains unchanged."""
    return _RUNTIME_CAPSULES.get(skill_name, document.content[:1600])


def _hub_skill_name(stem: str) -> str:
    return f"copepod-{stem.replace('_', '-')}"


def _discover_skills() -> dict[str, Path]:
    if not SKILLS_DIR.exists():
        return {}
    return {p.stem: p for p in sorted(SKILLS_DIR.glob("*.md"))}


def _discover_skill_documents() -> dict[str, SkillDocument]:
    """Load the local allowlist and fail startup on an invalid manifest."""

    return {
        name: load_skill_document(path)
        for name, path in _discover_skills().items()
    }


def _pull_from_hub(skill_name: str) -> str | None:
    """Tente de charger le skill depuis le LangSmith Context Hub.

    Retourne le contenu ou None si indisponible.
    Set SKILL_PREFER_LOCAL=true to bypass the hub entirely (useful when the
    hub holds a stale version and push is blocked, e.g. LangSmith 5xx).
    """
    if os.getenv("SKILL_PREFER_LOCAL", "").lower() in ("1", "true", "yes"):
        return None
    api_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
    if not api_key or _LangSmithClient is None:
        return None
    try:
        env = os.getenv("SKILL_ENV", "production")
        hub_name = _hub_skill_name(skill_name)
        identifier = f"{hub_name}:{env}"
        client = _LangSmithClient()
        skill = client.pull_skill(identifier)
        return skill.files["SKILL.md"].content
    except Exception:
        return None


def _record_loaded_skill(
    store: SessionStore,
    thread_id: str | None,
    skill_name: str,
    document: SkillDocument,
) -> bool:
    if not thread_id:
        return False
    session = store.get(thread_id) or {"df": None, "meta": {}}
    meta = dict(session.get("meta") or {})
    loaded = list(meta.get("loaded_skills") or [])
    if skill_name not in loaded:
        loaded.append(skill_name)
    capsules = dict(meta.get("active_skill_capsules") or {})
    existing = capsules.get(skill_name) or {}
    already_active = existing.get("sha256") == document.sha256
    capsules[skill_name] = {
        "version": document.manifest.version,
        "sha256": document.sha256,
        "content": _runtime_capsule(skill_name, document),
    }
    store.update_meta(thread_id, {
        "loaded_skills": loaded,
        "active_skill_capsules": capsules,
    })
    return already_active


def preseed_capsule_skills(
    store: SessionStore,
    thread_id: str | None,
    skill_names: tuple[str, ...],
) -> list[str]:
    """Activate a skill's runtime capsule without a model round-trip.

    Only skills whose full guidance is already captured by a static runtime
    capsule (``_RUNTIME_CAPSULES``) are eligible: for those, ``load_skill``
    returns nothing more than the capsule, so seeding it directly gives the
    model the same rules while removing the ``load_skill`` call. Idempotent;
    reuses the exact seam ``load_skill`` and ``run_graph`` already use.
    """
    if not thread_id:
        return []
    documents = _discover_skill_documents()
    seeded: list[str] = []
    for name in skill_names:
        if name not in _RUNTIME_CAPSULES or name not in documents:
            continue
        already_active = _record_loaded_skill(store, thread_id, name, documents[name])
        if not already_active:
            seeded.append(name)
    return seeded


_GRAPH_REFERENCE_SKILLS = ("graph_planner", "graph_writer")
_reference_cache: dict[str, str] = {}


def _full_skill_reference(skill_names: tuple[str, ...], header: str) -> str:
    """Concatenate the full reviewed bodies of the given skills, under a header.

    ``load_skill`` only ever returned the ~600-char runtime capsule for these
    skills (see ``_RUNTIME_CAPSULES``), so their reviewed procedures/templates
    never reached the model — it re-derived from memory instead. Latency is
    driven by model round-trips, not prompt tokens (measured: flat ~1.2s floor
    over 11K–32K tokens), so injecting the authoritative bodies when the skill
    is already active raises precision at negligible latency cost. Cached: the
    skill files are static.
    """
    cache_key = "|".join(skill_names)
    cached = _reference_cache.get(cache_key)
    if cached is not None:
        return cached
    documents = _discover_skill_documents()
    parts = [
        f"### {name}\n{documents[name].content}"
        for name in skill_names
        if name in documents
    ]
    reference = f"\n\n{header}\n\n" + "\n\n".join(parts) if parts else ""
    _reference_cache[cache_key] = reference
    return reference


def graph_rendering_reference() -> str:
    """Full reviewed graph_planner + graph_writer bodies for direct in-context use."""
    return _full_skill_reference(
        _GRAPH_REFERENCE_SKILLS,
        "## GRAPH RENDERING REFERENCE (authoritative reviewed templates; "
        "graph_planner and graph_writer are already active — build run_graph "
        "code directly from these templates, never call load_skill for them)",
    )


def source_navigation_reference(skill_names: tuple[str, ...]) -> str:
    """Full reviewed body of an already-active source-procedure skill (e.g. EcoTaxa)."""
    return _full_skill_reference(
        skill_names,
        "## SOURCE NAVIGATION REFERENCE (authoritative reviewed procedure; this "
        "source skill is already active — query directly from these rules, never "
        "call load_skill for it)",
    )


def dataset_analysis_reference(skill_names: tuple[str, ...]) -> str:
    """Full reviewed body of a dataset-triggered analysis skill (e.g. NeoLabs).

    Pre-activated when the matching file is the active dataset because the model
    does not reliably `load_skill` it and the file's column traps otherwise yield
    wrong numbers (aggregate-column double counting, single-stratum "profiles").
    """
    return _full_skill_reference(
        skill_names,
        "## DATASET ANALYSIS REFERENCE (authoritative reviewed workflow for the "
        "active dataset; already active — apply these rules directly, never call "
        "load_skill for it)",
    )


def make_skill_tool(thread_id: str | None = None, store: SessionStore | None = None):
    _store = store or default_store
    skills = _discover_skill_documents()
    activation_catalog = "; ".join(
        f"{name}: {document.manifest.triggers[0]}"
        for name, document in skills.items()
    ) or "none"
    description = (
        "Load one manifest-validated specialized skill only when its semantic "
        "activation intent matches. Available skills and primary triggers: "
        f"{activation_catalog}. "
        "For visualization tasks graph_planner and graph_writer are pre-activated "
        "automatically: reuse the ACTIVE SKILL RULES capsule and call run_graph "
        "directly. Do not spend a load_skill call on them when those rules are "
        "already present."
    )

    @tool(description=description, response_format="content_and_artifact")
    def load_skill(skill_name: str) -> str:
        """Load a skill by name from the local allowlist.

        Fail-closed: only a skill present in the local skills directory can be
        loaded. The LangSmith Context Hub may serve only the exact reviewed
        local version (same manifest and SHA-256), and can never introduce a
        skill name or content absent from the local allowlist.
        """
        current_skills = _discover_skill_documents()
        if skill_name not in current_skills:
            available = ", ".join(current_skills.keys()) or "none"
            return blocked(
                f"Skill '{skill_name}' not found. Available: {available}",
                provenance={"source": "local skill allowlist", "skill": skill_name},
                method="skill loader",
            )

        local_document = current_skills[skill_name]
        environment = os.getenv("SKILL_ENV", "production")
        selected_document = local_document
        source = "local skill file"
        hub_fallback_reason: str | None = None

        # The Hub is a distribution cache, not a second source of truth. A
        # remote document is accepted only when its reviewed local hash and
        # manifest match exactly; drift falls back to the local allowlist.
        hub_content = _pull_from_hub(skill_name)
        if hub_content:
            try:
                hub_document = parse_skill_document(
                    hub_content,
                    expected_name=skill_name,
                )
            except Exception:
                hub_fallback_reason = "invalid_manifest"
            else:
                if hub_document.sha256 != local_document.sha256:
                    hub_fallback_reason = "unreviewed_hash"
                else:
                    selected_document = hub_document
                    source = "LangSmith Context Hub"

        already_active = _record_loaded_skill(
            _store, thread_id, skill_name, selected_document,
        )
        manifest = selected_document.manifest
        provenance = {
            "source": source,
            "skill": manifest.name,
            "environment": environment,
            "version": manifest.version,
            "sha256": selected_document.sha256,
            "max_tokens": manifest.max_tokens,
            "estimated_tokens": selected_document.estimated_tokens,
        }
        if source == "local skill file" and local_document.path is not None:
            provenance["path"] = str(local_document.path)
        if hub_fallback_reason:
            provenance["hub_fallback_reason"] = hub_fallback_reason
        content = (
            f"Skill '{skill_name}' already active in this session; reuse its "
            "active rules."
            if already_active else selected_document.content
        )
        if not already_active and skill_name in _RUNTIME_CAPSULES:
            content = _runtime_capsule(skill_name, selected_document)
        return success(
            content,
            provenance=provenance,
            persisted=bool(thread_id),
            method="skill loader",
        )

    return load_skill
