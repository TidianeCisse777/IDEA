"""Contrats de contenu du skill graph_planner."""

from pathlib import Path

SKILL_PATH = Path(__file__).parent.parent / "agents" / "skills" / "graph_planner.md"


def _skill() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def test_graph_planner_contains_column_disambiguation_step():
    """graph_planner must instruct the agent to ask the user when multiple
    columns are candidates for an axis, instead of choosing silently."""
    content = _skill()
    assert "1b" in content, "Step 1b (column disambiguation) must exist"
    assert "ambig" in content.lower(), (
        "step 1b must mention ambiguity or disambiguation"
    )


def test_graph_planner_disambiguation_requires_asking_user():
    """The disambiguation rule must explicitly forbid silent column selection."""
    content = _skill().lower()
    assert "ask" in content or "demande" in content, (
        "step 1b must instruct to ask the user, not guess"
    )
    assert "silent" in content or "silenc" in content or "sans demander" in content, (
        "step 1b must forbid silent selection"
    )


def test_graph_planner_references_all_columns_field():
    """The compact schema must not make omitted columns look unavailable."""
    content = _skill()
    assert "all_columns" in content, (
        "graph_planner must reference the all_columns capsule field"
    )
    assert "not listed" in content, (
        "graph_planner must inspect the persisted table before rejecting an omitted field"
    )


def test_graph_planner_allows_one_consolidated_scoping_question():
    content = _skill().replace("\n", " ")

    assert "Ask at most one consolidated scoping question" in content
    assert "After the answer, render with that choice rather than asking again" in content


def test_graph_planner_does_not_render_object_analysis_from_ecotaxa_cache():
    planner = _skill()

    assert "do not plan or render it from a cache-only table" in planner
