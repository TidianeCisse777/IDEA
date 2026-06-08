"""Skill loader tool — charge un skill spécialisé pour l'agent."""
from pathlib import Path
from langchain_core.tools import tool

SKILLS_DIR = Path(__file__).parent.parent / "agents" / "skills"


def _discover_skills() -> dict[str, Path]:
    """Scan agents/skills/ and return {skill_name: path} for every .md file."""
    if not SKILLS_DIR.exists():
        return {}
    return {p.stem: p for p in sorted(SKILLS_DIR.glob("*.md"))}


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
        """Load a skill by name."""
        current_skills = _discover_skills()
        if skill_name not in current_skills:
            available = ", ".join(current_skills.keys()) or "none"
            return f"Skill '{skill_name}' not found. Available: {available}"
        return current_skills[skill_name].read_text(encoding="utf-8")

    return load_skill
