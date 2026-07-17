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


def _record_loaded_skill(store: SessionStore, thread_id: str | None, skill_name: str) -> None:
    if not thread_id:
        return
    session = store.get(thread_id) or {"df": None, "meta": {}}
    meta = dict(session.get("meta") or {})
    loaded = list(meta.get("loaded_skills") or [])
    if skill_name not in loaded:
        loaded.append(skill_name)
    store.update_meta(thread_id, {"loaded_skills": loaded})


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
        f"For visualization tasks, call graph_planner first, then graph_writer."
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

        _record_loaded_skill(_store, thread_id, skill_name)
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
        return success(
            selected_document.content,
            provenance=provenance,
            persisted=bool(thread_id),
            method="skill loader",
        )

    return load_skill
