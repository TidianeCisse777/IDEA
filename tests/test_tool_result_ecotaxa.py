"""ToolResult contracts for all EcoTaxa tools (family == "ecotaxa")."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
from langchain_core.messages import ToolMessage


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


def test_all_ecotaxa_tools_declare_structured_results(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from tools.tool_catalog import build_tool_catalog

    catalog = build_tool_catalog("ecotaxa-result-contract")
    names = {
        name for name, policy in catalog.policies.items()
        if policy.family == "ecotaxa"
    }
    by_name = {item.name: item for item in catalog.tools}

    assert len(names) == 33
    for name in names:
        assert by_name[name].response_format == "content_and_artifact", name
        assert catalog.policy(name).result_schema == "tool_result_v1", name


def test_ecotaxa_search_distinguishes_success_empty_and_error():
    from tools.copepod_sources import make_source_tools
    from tools.tool_result import validate_tool_artifact

    project = {
        "project_id": 42,
        "name": "UVP test",
        "instrument": "UVP6",
        "status": "active",
        "object_count": 10,
        "percent_validated": 100,
    }
    item = {tool.name: tool for tool in make_source_tools("ecotaxa-status")}["find_ecotaxa_projects"]

    with patch("tools.copepod_sources.search_projects", return_value=[project]):
        success_message = _call(item, "eco-success", title="UVP")
    with patch("tools.copepod_sources.search_projects", return_value=[]):
        empty_message = _call(item, "eco-empty", title="missing")
    with patch("tools.copepod_sources.search_projects", side_effect=RuntimeError("offline")):
        error_message = _call(item, "eco-error", title="UVP")

    success_result = validate_tool_artifact(success_message.artifact)
    assert success_result.status == "success"
    assert success_result.provenance["source"] == "ecotaxa"
    assert success_result.metrics["projects"] == 1
    assert validate_tool_artifact(empty_message.artifact).status == "empty"
    assert validate_tool_artifact(error_message.artifact).status == "error"


def test_ecotaxa_export_reports_persisted_dataset_and_artifact():
    from tools.copepod_sources import make_source_tools
    from tools.tool_result import validate_tool_artifact

    client = MagicMock()
    client.start_export.return_value = 7
    client.wait_for_job.return_value = {"state": "F"}
    client.download_tsv.return_value = pd.DataFrame({"object_id": ["o1"]})
    item = {tool.name: tool for tool in make_source_tools("ecotaxa-export-result")}["query_ecotaxa"]

    with patch("tools.copepod_sources.EcotaxaClient", return_value=client):
        message = _call(item, "eco-export", project_id=42)

    result = validate_tool_artifact(message.artifact)
    assert result.status == "success"
    assert result.data_ref == "df_ecotaxa_42"
    assert result.persisted is True
    assert result.artifact_refs
    assert result.provenance == {"source": "ecotaxa", "project_id": 42}
    assert result.metrics["rows"] == 1
