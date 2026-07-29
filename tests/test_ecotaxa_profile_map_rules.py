from pathlib import Path


def test_profile_maps_aggregate_samples_before_rendering_one_point_per_profile():
    system_prompt = Path("agents/copepod_system_prompt.py").read_text(encoding="utf-8")
    navigation = Path("agents/skills/ecotaxa_navigation.md").read_text(
        encoding="utf-8"
    )
    graph_writer = Path("agents/skills/graph_writer.md").read_text(
        encoding="utf-8"
    )

    assert "summarize_ecotaxa_profiles_for_map" in system_prompt
    assert "summarize_ecotaxa_profiles_for_map" in navigation
    assert "Never group a profile map by sample_id" in navigation
    assert "profile_id" in graph_writer
    assert "n_samples" in graph_writer
    assert "one point per profile" in graph_writer
    assert "Never label individual casts globally" in graph_writer


def test_sample_counts_are_an_optional_map_encoding_not_a_default():
    system_prompt = Path("agents/copepod_system_prompt.py").read_text(encoding="utf-8")
    graph_writer = Path("agents/skills/graph_writer.md").read_text(
        encoding="utf-8"
    )

    assert "only when the user explicitly asks for it" in system_prompt
    assert "uniform markers by default" in system_prompt
    assert "explicitly requests that encoding" in graph_writer
    assert "uniform marker per profile" in graph_writer


def test_user_graph_framing_overrides_template_defaults_after_column_inspection():
    system_prompt = Path("agents/copepod_system_prompt.py").read_text(encoding="utf-8")

    assert "user's requested measure and encoding always override a template" in system_prompt
    assert "Inspect candidate columns before choosing a metric" in system_prompt


def test_rag_guides_domain_uncertainty_before_a_user_clarification():
    system_prompt = Path("agents/copepod_system_prompt.py").read_text(encoding="utf-8")

    assert "unresolved documentary uncertainty about a project-specific method" in system_prompt
    assert "query `query_copepod_knowledge_base` before asking the user" in system_prompt
    assert "Do not use RAG to choose among actual candidate columns" in system_prompt
    assert "Only when the agent has unresolved documentary uncertainty" in system_prompt


def test_ecotaxa_tools_do_not_reload_the_preactivated_navigation_skill():
    source = Path("tools/copepod_sources.py").read_text(encoding="utf-8")

    for tool_name in ("find_ecotaxa_samples_in_region", "query_ecotaxa_cache"):
        tool_section = source[source.index(f"def {tool_name}"):]
        next_tool = tool_section.find("\n    @tool", 1)
        if next_tool != -1:
            tool_section = tool_section[:next_tool]
        assert 'load_skill("ecotaxa_navigation")' not in tool_section
