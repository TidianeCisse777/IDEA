"""Skill loader tool — charge un skill spécialisé pour l'agent."""
from pathlib import Path
from langchain_core.tools import tool

SKILLS_DIR = Path(__file__).parent.parent / "agents" / "skills"

AVAILABLE_SKILLS = {
    "graph_planner": "graph_planner.md",
    "graph_writer": "graph_writer.md",
}


def make_skill_tool():
    @tool
    def load_skill(skill_name: str) -> str:
        """Load a specialized skill prompt.

        Available skills:
        - graph_planner: plan a graph before writing code (choose type, axes, aggregation)
        - graph_writer: write correct matplotlib code (template, rules, data handling)

        Call graph_planner BEFORE graph_writer for any visualization task.

        Args:
            skill_name: Name of the skill to load.

        Returns:
            The skill's instructions as text.
        """
        if skill_name not in AVAILABLE_SKILLS:
            available = ", ".join(AVAILABLE_SKILLS.keys())
            return f"Skill '{skill_name}' not found. Available: {available}"

        skill_path = SKILLS_DIR / AVAILABLE_SKILLS[skill_name]
        if not skill_path.exists():
            return f"Skill file not found: {skill_path}"

        return skill_path.read_text(encoding="utf-8")

    return load_skill
