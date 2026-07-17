"""ToolResult contracts for EcoPart, Amundsen, Bio-ORACLE, and OGSL."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import ToolMessage

REMOTE_FAMILIES = {"ecopart", "amundsen", "bio_oracle", "ogsl"}


def _call(item, call_id: str, **arguments) -> ToolMessage:
    message = item.invoke(
        {
            "type": "tool_call",
            "id": call_id,
            "name": item.name,
            "args": arguments,
        }
    )
    assert isinstance(message, ToolMessage)
    return message


def test_all_22_remote_family_tools_declare_structured_results(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from tools.tool_catalog import build_tool_catalog

    catalog = build_tool_catalog("remote-result-contract")
    names = {
        name for name, policy in catalog.policies.items()
        if policy.family in REMOTE_FAMILIES
    }
    by_name = {item.name: item for item in catalog.tools}

    assert len(names) == 22
    for name in names:
        assert by_name[name].response_format == "content_and_artifact", name
        assert catalog.policy(name).result_schema == "tool_result_v1", name


def test_ecopart_list_distinguishes_empty_and_error():
    from tools.ecopart_sources import make_ecopart_tools
    from tools.tool_result import validate_tool_artifact

    item = {tool.name: tool for tool in make_ecopart_tools("ecopart-status")}["list_ecopart_samples"]
    client = MagicMock()
    client.list_samples.return_value = []
    with patch("tools.ecopart_sources.EcopartClient", return_value=client):
        empty_message = _call(item, "ep-empty", project_id=42)
    client.list_samples.side_effect = RuntimeError("offline")
    with patch("tools.ecopart_sources.EcopartClient", return_value=client):
        error_message = _call(item, "ep-error", project_id=42)

    assert validate_tool_artifact(empty_message.artifact).status == "empty"
    assert validate_tool_artifact(error_message.artifact).status == "error"


def test_remote_list_tools_report_empty_without_text_parsing():
    from tools.amundsen_sources import make_amundsen_tools
    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.tool_result import validate_tool_artifact

    amundsen = {tool.name: tool for tool in make_amundsen_tools("am-empty")}["list_amundsen_datasets"]
    bio = {tool.name: tool for tool in make_bio_oracle_tools("bio-empty")}["list_bio_oracle_datasets"]
    with patch("tools.amundsen_sources._list_amundsen_datasets", return_value=[]):
        am_message = _call(amundsen, "am-empty")
    with patch("tools.bio_oracle_sources._list_bio_oracle_datasets", return_value=[]):
        bio_message = _call(bio, "bio-empty")

    assert validate_tool_artifact(am_message.artifact).status == "empty"
    assert validate_tool_artifact(bio_message.artifact).status == "empty"


def test_ogsl_missing_active_table_is_blocked():
    from tools.ogsl_sources import make_ogsl_tools
    from tools.tool_result import validate_tool_artifact

    item = {tool.name: tool for tool in make_ogsl_tools("ogsl-blocked")}["query_ogsl"]
    message = _call(
        item,
        "ogsl-blocked",
        station_column="station",
        time_column="time",
    )

    assert validate_tool_artifact(message.artifact).status == "blocked"
