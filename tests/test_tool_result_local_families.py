"""ToolResult contracts for local data, geography, and core tools."""

from __future__ import annotations

from langchain_core.messages import ToolMessage

LOCAL_TOOL_NAMES = {
    "load_file",
    "run_pandas",
    "run_graph",
    "get_zone_info",
    "filter_dataframe_by_zone",
    "query_copepod_knowledge_base",
    "lookup_marine_taxonomy",
    "load_skill",
    "export_deliverable",
}


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


def test_local_and_core_tools_declare_structured_results(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from tools.tool_catalog import build_tool_catalog

    catalog = build_tool_catalog("local-result-contract")
    by_name = {item.name: item for item in catalog.tools}
    for name in LOCAL_TOOL_NAMES:
        assert by_name[name].response_format == "content_and_artifact", name
        assert catalog.policy(name).result_schema == "tool_result_v1", name


def test_get_zone_info_preserves_dict_content_and_adds_success_artifact():
    from tools.geo_tools import get_zone_info
    from tools.tool_result import validate_tool_artifact

    direct = get_zone_info.invoke({"zone_name": "Baie d'Ungava"})
    message = _call(get_zone_info, "zone-1", zone_name="Baie d'Ungava")
    result = validate_tool_artifact(message.artifact)

    assert isinstance(direct, dict)
    assert direct["canonical"] == "Baie d'Ungava"
    assert result.status == "success"
    assert result.provenance["source"]
    assert result.metrics["bbox"] == direct["bbox"]


def test_local_preconditions_and_failures_have_explicit_statuses(tmp_path, monkeypatch):
    from tools.data_tools import make_tools
    from tools.deliverable_tool import export_deliverable
    from tools.session_store import SessionStore
    from tools.skill_tool import make_skill_tool
    from tools.tool_result import validate_tool_artifact

    store = SessionStore(tmp_path / "sessions")
    by_name = {item.name: item for item in make_tools("local-status", store=store)}

    load_message = _call(by_name["load_file"], "load-1", path=str(tmp_path / "missing.tsv"))
    pandas_message = _call(by_name["run_pandas"], "pandas-1", code="result = 1")
    skill_message = _call(
        make_skill_tool("local-status", store=store),
        "skill-1",
        skill_name="does_not_exist",
    )
    deliverable_message = _call(
        export_deliverable,
        "deliverable-1",
        content="# Rapport",
    )

    assert validate_tool_artifact(load_message.artifact).status == "error"
    assert validate_tool_artifact(pandas_message.artifact).status == "blocked"
    assert validate_tool_artifact(skill_message.artifact).status == "blocked"
    assert validate_tool_artifact(deliverable_message.artifact).status == "blocked"


def test_rag_empty_result_is_not_inferred_from_its_french_text(monkeypatch):
    import tools.rag_tool as rag_module
    from tools.tool_result import validate_tool_artifact

    monkeypatch.setattr(rag_module, "query_copepod_rag", lambda *_args, **_kwargs: [])
    item = rag_module.make_rag_tool()
    message = _call(item, "rag-1", question="question absente")

    result = validate_tool_artifact(message.artifact)
    assert result.status == "empty"
    assert message.content == "Aucun résultat trouvé dans la base de connaissances."
