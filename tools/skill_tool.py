"""Skill loader tool — charge un skill depuis le LangSmith Context Hub ou le disque."""
from __future__ import annotations

import os
from pathlib import Path

from langchain_core.tools import tool

from tools.session_store import SessionStore, default_store
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
    skills = _discover_skills()
    available_list = ", ".join(skills.keys()) or "none"
    description = (
        f"Load a specialized skill prompt. "
        f"Available skills: {available_list}. "
        f"For visualization tasks, call graph_planner first, then graph_writer."
    )

    @tool(description=description, response_format="content_and_artifact")
    def load_skill(skill_name: str) -> str:
        """Load a skill by name from the local allowlist.

        Fail-closed: only a skill present in the local skills directory can be
        loaded. The LangSmith Context Hub may serve a newer version of an
        already-allowlisted skill, but can never introduce a skill name absent
        from the local allowlist.
        """
        current_skills = _discover_skills()
        if skill_name not in current_skills:
            available = ", ".join(current_skills.keys()) or "none"
            return blocked(
                f"Skill '{skill_name}' not found. Available: {available}",
                provenance={"source": "local skill allowlist", "skill": skill_name},
                method="skill loader",
            )

        # Allowlisted: prefer the Hub version, fall back to the local file. The
        # effective source stays visible in provenance for observability.
        content = _pull_from_hub(skill_name)
        if content:
            _record_loaded_skill(_store, thread_id, skill_name)
            return success(
                content,
                provenance={"source": "LangSmith Context Hub", "skill": skill_name},
                persisted=bool(thread_id),
                method="skill loader",
            )

        _record_loaded_skill(_store, thread_id, skill_name)
        content = current_skills[skill_name].read_text(encoding="utf-8")
        return success(
            content,
            provenance={
                "source": "local skill file",
                "skill": skill_name,
                "path": str(current_skills[skill_name]),
            },
            persisted=bool(thread_id),
            method="skill loader",
        )

    return load_skill
