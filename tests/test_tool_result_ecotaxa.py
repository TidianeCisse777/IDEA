"""Structured-result contracts for the canonical EcoTaxa tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
from langchain_core.messages import ToolMessage


def _call(item, call_id: str, **arguments) -> ToolMessage:
    message = item.invoke({
        "type": "tool_call",
        "id": call_id,
        "name": item.name,
        "args": arguments,
    })
    assert isinstance(message, ToolMessage)
    return message


def test_five_ecotaxa_tools_use_structured_results(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from tools.tool_catalog import build_tool_catalog

    catalog = build_tool_catalog("ecotaxa-result-contract")
    names = {
        name for name, policy in catalog.policies.items()
        if policy.family == "ecotaxa"
    }
    by_name = {item.name: item for item in catalog.tools}

    assert names == {
        "describe_ecotaxa_cache_table",
        "export_ecotaxa_samples",
        "list_ecotaxa_cache_tables",
        "query_ecotaxa",
        "query_ecotaxa_cache",
    }
    for name in names:
        assert by_name[name].response_format == "content_and_artifact"
        assert catalog.policy(name).result_schema == "tool_result_v1"


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
