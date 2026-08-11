"""Contrats 2A.2 des entrées de tools strictes et fail-closed."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


@pytest.fixture()
def catalog(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from tools.tool_catalog import build_tool_catalog

    return build_tool_catalog("strict-input-contracts")


def test_every_runtime_tool_forbids_extra_arguments_and_coercion(catalog):
    for item in catalog.tools:
        config = item.args_schema.model_config
        assert config.get("strict") is True, item.name
        assert config.get("extra") == "forbid", item.name

    by_name = {item.name: item for item in catalog.tools}
    with pytest.raises(ValidationError):
        by_name["query_ecotaxa"].invoke({"project_id": "105"})
    with pytest.raises(ValidationError):
        by_name["get_zone_info"].invoke(
            {"zone_name": "Labrador Sea", "unexpected": "ignored-before-2A.2"}
        )


def test_ecopart_sample_id_is_explicit(catalog):
    item = {tool.name: tool for tool in catalog.tools}["preview_ecopart_sample"]
    schema = item.args_schema.model_json_schema()

    assert "sample_id" in schema.get("required", [])
    assert "default" not in schema["properties"]["sample_id"]
    with pytest.raises(ValidationError):
        item.invoke({})


def test_strict_schema_preserves_safe_defaults(catalog):
    by_name = {item.name: item for item in catalog.tools}

    query_schema = by_name["query_ecotaxa"].args_schema.model_json_schema()
    graph_schema = by_name["run_graph"].args_schema.model_json_schema()

    assert query_schema["properties"]["status"]["default"] == "V"
    assert query_schema["properties"]["sample_ids"]["default"] is None
    assert graph_schema.get("required") == ["code"]


def test_catalog_validation_rejects_a_non_strict_schema(monkeypatch, catalog):
    import tools.tool_catalog as catalog_module

    item = catalog.tools[0]
    item.args_schema.model_config["strict"] = False
    with pytest.raises(ValueError, match="non-strict args schema"):
        catalog_module.validate_catalog(
            set(catalog.names),
            optional_names=catalog_module.OPTIONAL_SQL_TOOL_NAMES,
            runtime_tools=catalog.tools,
        )
