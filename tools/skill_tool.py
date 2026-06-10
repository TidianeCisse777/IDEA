"""Skill loader tool — charge un skill depuis le LangSmith Context Hub ou le disque."""
from __future__ import annotations

import os
from pathlib import Path

from langchain_core.tools import tool

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
    """
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


def make_skill_tool():
    skills = _discover_skills()
    available_list = ", ".join(skills.keys()) or "none"
    description = (
        f"Load a specialized skill prompt. "
        f"Available skills: {available_list}. "
        f"For visualization tasks, call graph_planner first, then graph_writer."
    )

    @tool(description=description)
    def load_skill(skill_name: str) -> str:
        """Load a skill by name. Pulls from LangSmith Context Hub, falls back to local file."""
        content = _pull_from_hub(skill_name)
        if content:
            return content

        current_skills = _discover_skills()
        if skill_name not in current_skills:
            available = ", ".join(current_skills.keys()) or "none"
            return f"Skill '{skill_name}' not found. Available: {available}"
        return current_skills[skill_name].read_text(encoding="utf-8")

    return load_skill
