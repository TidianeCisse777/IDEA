"""Structured-result contracts for the canonical enrichment tools."""

from __future__ import annotations

import pytest
from langchain_core.messages import ToolMessage


REMOTE_FAMILIES = {"ecopart", "amundsen", "bio_oracle", "ogsl"}


def _call(item, call_id: str, **arguments) -> ToolMessage:
    message = item.invoke({
        "type": "tool_call",
        "id": call_id,
        "name": item.name,
        "args": arguments,
    })
    assert isinstance(message, ToolMessage)
    return message


def test_eight_remote_tools_declare_structured_results(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from tools.tool_catalog import build_tool_catalog

    catalog = build_tool_catalog("remote-result-contract")
    names = {
        name for name, policy in catalog.policies.items()
        if policy.family in REMOTE_FAMILIES
    }
    by_name = {item.name: item for item in catalog.tools}

    assert len(names) == 8
    for name in names:
        assert by_name[name].response_format == "content_and_artifact"
        assert catalog.policy(name).result_schema == "tool_result_v1"


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("enrich_ecotaxa_with_ecopart_remote", {"confirmed": False}),
        ("enrich_with_amundsen_ctd", {}),
        ("enrich_with_bio_oracle", {}),
        ("enrich_with_ogsl", {}),
    ],
)
def test_enrichments_without_a_dataframe_are_blocked(monkeypatch, name, arguments):
    monkeypatch.setenv("DATABASE_URL", "")
    from tools.tool_catalog import build_tool_catalog
    from tools.tool_result import validate_tool_artifact

    item = {tool.name: tool for tool in build_tool_catalog("remote-blocked").tools}[name]
    message = _call(item, f"blocked-{name}", **arguments)

    assert validate_tool_artifact(message.artifact).status == "blocked"
