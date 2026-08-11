"""Structured-result contracts for data, geography, and core tools."""

from __future__ import annotations

from langchain_core.messages import ToolMessage


LOCAL_TOOL_NAMES = {
    "load_file",
    "run_pandas",
    "run_graph",
    "get_zone_info",
    "filter_dataframe_by_zone",
    "split_dataframe_by_zone",
    "query_copepod_knowledge_base",
    "lookup_marine_taxonomy",
    "export_deliverable",
}


def _call(item, call_id: str, **arguments) -> ToolMessage:
    message = item.invoke({
        "type": "tool_call",
        "id": call_id,
        "name": item.name,
        "args": arguments,
    })
    assert isinstance(message, ToolMessage)
    return message


def test_local_and_core_tools_declare_structured_results(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from tools.tool_catalog import build_tool_catalog

    catalog = build_tool_catalog("local-result-contract")
    by_name = {item.name: item for item in catalog.tools}
    for name in LOCAL_TOOL_NAMES:
        assert catalog.policy(name).result_schema == "tool_result_v1"
        if name in {"load_file", "run_pandas"}:
            assert by_name[name].response_format == "content"
            assert by_name[name].extras["command_result_schema"] == "tool_result_v1"
        else:
            assert by_name[name].response_format == "content_and_artifact"


def test_local_preconditions_have_explicit_statuses(tmp_path):
    from tools.data_tools import make_tools
    from tools.deliverable_tool import export_deliverable
    from tools.session_store import SessionStore
    from tools.tool_result import validate_tool_artifact

    store = SessionStore(tmp_path / "sessions")
    by_name = {item.name: item for item in make_tools("local-status", store=store)}

    _, load_artifact = by_name["load_file"].invoke({"path": str(tmp_path / "missing.tsv")})
    _, pandas_artifact = by_name["run_pandas"].invoke({"code": "result = 1"})
    deliverable_message = _call(export_deliverable, "deliverable-1", content="# Rapport")

    assert validate_tool_artifact(load_artifact).status == "error"
    assert validate_tool_artifact(pandas_artifact).status == "blocked"
    assert validate_tool_artifact(deliverable_message.artifact).status == "blocked"


def test_rag_empty_result_is_structured(monkeypatch):
    import tools.rag_tool as rag_module
    from tools.tool_result import validate_tool_artifact

    monkeypatch.setattr(rag_module, "query_copepod_rag", lambda *_args, **_kwargs: [])
    item = rag_module.make_rag_tool()
    message = _call(item, "rag-1", question="question absente")

    assert validate_tool_artifact(message.artifact).status == "empty"
    assert message.content == "Aucun résultat trouvé dans la base de connaissances."
