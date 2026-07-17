"""Tool allowlist contracts driven by SourceDecision and ToolPolicy."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace


@dataclass
class _Tool:
    name: str


def _policies():
    return {
        "run_pandas": SimpleNamespace(source="file"),
        "get_zone_info": SimpleNamespace(source="geography"),
        "load_skill": SimpleNamespace(source="skill"),
        "find_ecotaxa_projects": SimpleNamespace(source="ecotaxa"),
        "query_ecopart": SimpleNamespace(source="ecopart"),
        "query_amundsen_ctd": SimpleNamespace(source="amundsen"),
        "query_bio_oracle": SimpleNamespace(source="bio_oracle"),
        "query_ogsl": SimpleNamespace(source="ogsl"),
        "list_sql_tables": SimpleNamespace(source="sql"),
    }


def _ecotaxa_decision():
    from tools.source_scope import SourceDecision

    return SourceDecision(
        primary_source="ecotaxa",
        authorized_sources=("ecotaxa",),
        explicit_sources=("ecotaxa",),
        evidence="explicit_name",
        needs_clarification=False,
        reason="test",
    )


def test_filter_keeps_common_and_authorized_source_tools():
    from tools.source_scope import filter_tools_for_decision

    tools = [_Tool(name) for name in _policies()]
    kept = {
        tool.name
        for tool in filter_tools_for_decision(tools, _ecotaxa_decision(), _policies())
    }

    assert kept == {
        "run_pandas",
        "get_zone_info",
        "load_skill",
        "find_ecotaxa_projects",
    }


def test_no_selected_source_hides_every_external_family():
    from tools.source_scope import SourceDecision, filter_tools_for_decision

    decision = SourceDecision(
        primary_source=None,
        authorized_sources=(),
        explicit_sources=(),
        evidence="none",
        needs_clarification=True,
        reason="test",
    )
    kept = {
        tool.name
        for tool in filter_tools_for_decision(
            [_Tool(name) for name in _policies()],
            decision,
            _policies(),
        )
    }

    assert kept == {"run_pandas", "get_zone_info", "load_skill"}


def test_source_for_tool_call_uses_policy_and_source_skills():
    from tools.source_scope import source_for_tool_call

    policies = _policies()
    assert source_for_tool_call("find_ecotaxa_projects", {}, policies) == "ecotaxa"
    assert source_for_tool_call("run_pandas", {}, policies) is None
    assert source_for_tool_call(
        "load_skill", {"skill_name": "ecotaxa_navigation"}, policies
    ) == "ecotaxa"
    assert source_for_tool_call(
        "load_skill", {"skill_name": "ecopart_query"}, policies
    ) == "ecopart"
    assert source_for_tool_call(
        "load_skill", {"skill_name": "amundsen_ctd_query"}, policies
    ) == "amundsen"
    assert source_for_tool_call(
        "load_skill", {"skill_name": "bio_oracle_query"}, policies
    ) == "bio_oracle"
    assert source_for_tool_call(
        "load_skill", {"skill_name": "ogsl_query"}, policies
    ) == "ogsl"
    assert source_for_tool_call(
        "load_skill", {"skill_name": "sql_workspace_query"}, policies
    ) == "sql"
    assert source_for_tool_call(
        "load_skill", {"skill_name": "graph_writer"}, policies
    ) is None


def test_rejection_is_identical_for_tool_and_source_skill():
    from tools.source_scope import source_rejection_for_call

    policies = _policies()
    tool_rejection = source_rejection_for_call(
        _ecotaxa_decision(), "query_bio_oracle", {}, policies
    )
    skill_rejection = source_rejection_for_call(
        _ecotaxa_decision(),
        "load_skill",
        {"skill_name": "bio_oracle_query"},
        policies,
    )

    assert tool_rejection is not None
    assert skill_rejection is not None
    assert "Bio-ORACLE" in tool_rejection
    assert "Bio-ORACLE" in skill_rejection
    assert source_rejection_for_call(
        _ecotaxa_decision(), "run_pandas", {}, policies
    ) is None
