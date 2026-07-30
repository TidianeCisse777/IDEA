from pathlib import Path










def test_ecotaxa_tools_do_not_reload_the_preactivated_navigation_skill():
    source = Path("tools/copepod_sources.py").read_text(encoding="utf-8")

    for tool_name in ("find_ecotaxa_samples_in_region", "query_ecotaxa_cache"):
        tool_section = source[source.index(f"def {tool_name}"):]
        next_tool = tool_section.find("\n    @tool", 1)
        if next_tool != -1:
            tool_section = tool_section[:next_tool]
        assert 'load_skill("ecotaxa_navigation")' not in tool_section
