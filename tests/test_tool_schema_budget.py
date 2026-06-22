"""Regression tests for conservative LangChain tool schema budgets."""

from __future__ import annotations

import json


def _schema_tokens(tool) -> int:
    schema = {}
    if getattr(tool, "args_schema", None):
        schema = tool.args_schema.model_json_schema()
    payload = {
        "name": tool.name,
        "description": getattr(tool, "description", "") or "",
        "schema": schema,
    }
    return len(json.dumps(payload, ensure_ascii=False, sort_keys=True)) // 4


def test_conservative_tool_schema_budget(monkeypatch):
    monkeypatch.delenv("SESSION_STORE_DATABASE_URL", raising=False)

    from tools.bio_oracle_sources import make_bio_oracle_tools
    from tools.geo_tools import get_zone_info

    bio_tools = {tool.name: tool for tool in make_bio_oracle_tools("schema-budget")}
    tools = {
        "couple_zooplankton_bio_oracle": bio_tools["couple_zooplankton_bio_oracle"],
        "query_bio_oracle_zones": bio_tools["query_bio_oracle_zones"],
        "get_zone_info": get_zone_info,
    }

    budgets = {
        "couple_zooplankton_bio_oracle": 900,
        "query_bio_oracle_zones": 650,
        "get_zone_info": 700,
    }

    actual = {name: _schema_tokens(tool) for name, tool in tools.items()}

    assert actual == {
        name: tokens
        for name, tokens in actual.items()
        if tokens <= budgets[name]
    }
