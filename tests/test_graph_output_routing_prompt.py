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
    assert "“show/display/present” alone is not visual intent" in prompt


def test_visual_intent_is_inferred_from_requested_representation():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "map/profile/curve/chart/visual encoding = visual" in prompt


def test_non_visual_outputs_skip_both_graph_skills():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "number,\n  calculation, ranking, summary, coordinates or table = non-visual" in prompt


def test_graph_skills_must_run_in_separate_sequential_tool_batches():
    planner = Path("agents/skills/graph_planner.md").read_text(encoding="utf-8").lower()
    assert "same tool-call batch" in planner
    assert "wait for this result first" in planner


def test_every_ecotaxa_map_loads_navigation_then_graph_skills():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    navigation = Path("agents/skills/ecotaxa_navigation.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "every ecotaxa map request" in navigation
    assert "graph workflow are already active" in navigation


def test_ecotaxa_named_zone_queries_keep_iho_and_meow_labels_separate():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    navigation = Path("agents/skills/ecotaxa_navigation.md").read_text(
        encoding="utf-8"
    ).lower()
    source_tool = Path("tools/copepod_sources.py").read_text(encoding="utf-8").lower()

    assert "exact named zone" in navigation
    assert "iho_zone = 'mer de beaufort'" in navigation
    assert "never use `like` for an explicitly named zone" in navigation
    assert "iho and meow labels into one count" in navigation
    assert "exact named zone" in source_tool
    assert "iho_zone = 'baie de baffin'" in source_tool
    assert "zone_reference" in navigation
    assert "zone_reference" in source_tool


def test_ecotaxa_navigation_resolves_bilingual_zone_aliases_before_exact_sql():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    navigation = Path("agents/skills/ecotaxa_navigation.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "beaufort sea" in navigation
    assert "mer de beaufort" in navigation
    assert "equality filter" in navigation


def test_generic_ecotaxa_zone_coverage_queries_cache_in_the_same_turn():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    navigation = Path("agents/skills/ecotaxa_navigation.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "generic zone coverage" in navigation
    assert "query_ecotaxa_cache" in navigation
    assert "zone_reference, iho_zone" in navigation


def test_each_new_visual_turn_reuses_the_active_graph_workflow():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "visual -> reuse active graph rules" in prompt
    assert "preparation alone is not completion" in prompt


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


def test_graph_contract_blocks_require_one_same_dataset_retry():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "retry exactly once" in prompt
    assert "same dataframe" in prompt
    assert "never claim a graph" in prompt


def test_graph_retry_rule_has_one_canonical_prompt_location():
    from agents.graph_output_routing_rules import GRAPH_OUTPUT_ROUTING_RULES

    assert GRAPH_OUTPUT_ROUTING_RULES.count("retry exactly once") == 1
