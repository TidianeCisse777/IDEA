"""Structured-result contracts for the optional SQL tools."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest
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


def test_sql_tools_return_structured_results(tmp_path, monkeypatch):
    from tools.sql_workspace import make_sql_tools
    from tools.tool_result import validate_tool_artifact

    db_path = tmp_path / "source.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE casts (id INTEGER PRIMARY KEY, station TEXT)")
    connection.execute("INSERT INTO casts VALUES (1, 'A')")
    connection.commit()
    connection.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SQL_WORKSPACE_DIR", str(tmp_path / "workspace"))
    by_name = {item.name: item for item in make_sql_tools("sql-result")}

    listed = _call(by_name["list_sql_tables"], "sql-list")
    previewed = _call(by_name["preview_sql_table"], "sql-preview", table_name="casts", limit=10)
    blocked = _call(by_name["copy_sql_query_to_workspace"], "sql-copy", query="SELECT * FROM casts")

    assert validate_tool_artifact(listed.artifact).status == "success"
    assert validate_tool_artifact(previewed.artifact).status == "success"
    assert validate_tool_artifact(blocked.artifact).status == "blocked"


def test_all_25_policies_require_structured_results(monkeypatch):
    import tools.tool_catalog as catalog_module

    assert len(catalog_module.TOOL_POLICIES) == 25
    assert {policy.result_schema for policy in catalog_module.TOOL_POLICIES.values()} == {"tool_result_v1"}

    monkeypatch.setenv("DATABASE_URL", "")
    catalog = catalog_module.build_tool_catalog("no-legacy-results")
    invalid = dict(catalog_module.TOOL_POLICIES)
    invalid["run_graph"] = replace(invalid["run_graph"], result_schema="legacy_text")
    monkeypatch.setattr(catalog_module, "TOOL_POLICIES", invalid)
    with pytest.raises(ValueError, match="legacy result schema"):
        catalog_module.validate_catalog(
            catalog.names,
            optional_names=catalog_module.OPTIONAL_SQL_TOOL_NAMES,
            runtime_tools=catalog.tools,
        )
