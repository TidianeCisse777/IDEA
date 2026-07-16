"""Contrats sémantiques de sélection des sorties graphiques."""

from pathlib import Path

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT


def test_graph_output_rules_are_canonical_and_injected_once():
    from agents.graph_output_routing_rules import GRAPH_OUTPUT_ROUTING_RULES

    assert COPEPOD_SYSTEM_PROMPT.count(GRAPH_OUTPUT_ROUTING_RULES) == 1
    assert (
        "For ANY data analysis or visualization request"
        not in COPEPOD_SYSTEM_PROMPT
    )


def test_general_presentation_verbs_do_not_force_visual_output():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "general presentation verb" in prompt
    assert "does not establish visual intent by itself" in prompt


def test_visual_intent_is_inferred_from_requested_representation():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "requested output intent" in prompt
    assert "representation of the data" in prompt
    assert "vertical profile" in prompt


def test_non_visual_outputs_skip_both_graph_skills():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "number, calculation, ranking, summary, coordinates, or table" in prompt
    assert "do not load `graph_planner` or `graph_writer`" in prompt


def test_graph_planner_uses_semantics_instead_of_closed_keyword_list():
    planner = Path("agents/skills/graph_planner.md").read_text(
        encoding="utf-8"
    ).lower()
    assert "decide from the requested output intent" in planner
    assert "not from a closed list of words" in planner
    assert "if the prompt explicitly mentions" not in planner


def test_graph_writer_is_visual_only():
    writer = Path("agents/skills/graph_writer.md").read_text(
        encoding="utf-8"
    ).lower()
    assert "produce the planned visual output" in writer
    assert "## if the plan says output: table" not in writer
