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


def test_ecotaxa_tools_do_not_reload_the_preactivated_navigation_skill():
    source = Path("tools/copepod_sources.py").read_text(encoding="utf-8")

    for tool_name in ("find_ecotaxa_samples_in_region", "query_ecotaxa_cache"):
        tool_section = source[source.index(f"def {tool_name}"):]
        next_tool = tool_section.find("\n    @tool", 1)
        if next_tool != -1:
            tool_section = tool_section[:next_tool]
        assert 'load_skill("ecotaxa_navigation")' not in tool_section
