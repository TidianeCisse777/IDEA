"""Regression tests for conservative LangChain tool schema budgets."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter


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


def test_complete_catalog_inventory_and_schema_budget(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")  # "" présent = non configuré, résiste à load_dotenv
    monkeypatch.delenv("SESSION_STORE_DATABASE_URL", raising=False)

    from tools.tool_catalog import build_tool_catalog

    catalog = build_tool_catalog("complete-schema-budget")
    family_counts = Counter(
        catalog.presentation(name).family for name in catalog.names
    )
    schema_tokens = {
        tool.name: _schema_tokens(tool) for tool in catalog.tools
    }

    assert len(catalog.tools) == len(catalog.names) == 59
    assert family_counts == {
        "data": 3,
        "ecotaxa": 28,
        "ecopart": 7,
        "amundsen": 6,
        "bio_oracle": 7,
        "ogsl": 2,
        "geography": 2,
        "core": 4,
    }
    assert max(schema_tokens.values()) <= 1_600
    # Plafond relevé de 26_000 pour absorber les 4 tools EcoTaxa/EcoPart
    # ajoutés sur main (audit_* + list_ecotaxa_project_samples), déjà en prod.
    assert sum(schema_tokens.values()) <= 27_000


def test_complete_catalog_with_sql_stays_within_schema_budget(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "catalog.sqlite"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE casts (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("SQL_WORKSPACE_DIR", str(tmp_path / "workspace"))

    from tools.tool_catalog import build_tool_catalog

    catalog = build_tool_catalog("complete-schema-budget-sql")
    schema_tokens = {
        tool.name: _schema_tokens(tool) for tool in catalog.tools
    }

    assert len(catalog.tools) == len(catalog.names) == 62
    assert sum(
        catalog.presentation(name).family == "sql" for name in catalog.names
    ) == 3
    assert max(schema_tokens.values()) <= 1_600
    assert sum(schema_tokens.values()) <= 28_000
