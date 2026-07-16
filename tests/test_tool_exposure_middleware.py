"""Runtime enforcement for deterministic tool exposure decisions."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from tools.dataset_registry import store_dataset
from tools.session_store import SessionStore
from tools.tool_result import success, validate_tool_artifact


def _request(name: str, text: str, *, call_id: str = "call"):
    return SimpleNamespace(
        tool_call={"name": name, "args": {}, "id": call_id},
        state={"messages": [HumanMessage(content=text)]},
    )


def _success(request):
    content, artifact = success("ok")
    return ToolMessage(
        content=content,
        artifact=artifact,
        tool_call_id=request.tool_call["id"],
    )


async def _asuccess(request):
    return _success(request)


def _loaded_store(tmp_path, thread_id: str) -> SessionStore:
    store = SessionStore(tmp_path)
    frame = pd.DataFrame({"latitude": [60.0], "longitude": [-60.0]})
    store_dataset(
        store,
        thread_id,
        frame,
        variable_name="df_file_demo",
        meta={
            "source": "file:/tmp/demo.tsv",
            "path": "/tmp/demo.tsv",
            "n_rows": 1,
            "n_cols": 2,
        },
        is_loaded_file=True,
    )
    return store


def test_hidden_legacy_tool_is_blocked_before_handler(monkeypatch, tmp_path):
    import agent as agent_module

    store = SessionStore(tmp_path)
    monkeypatch.setattr("tools.session_store.default_store", store)
    middleware = agent_module._ContextMiddleware(thread_id="hidden")
    request = _request("query_bio_oracle", "Utilise Bio-ORACLE")
    called = False

    def handler(_request):
        nonlocal called
        called = True
        return _success(_request)

    result = middleware.wrap_tool_call(request, handler)

    assert called is False
    artifact = validate_tool_artifact(result.artifact)
    assert artifact.status == "blocked"
    assert artifact.provenance["source"] == "tool_exposure_policy"


def test_canonical_enrichment_is_allowed_for_explicit_source_and_file(
    monkeypatch, tmp_path
):
    import agent as agent_module

    thread_id = "enrichment"
    store = _loaded_store(tmp_path, thread_id)
    monkeypatch.setattr("tools.session_store.default_store", store)
    middleware = agent_module._ContextMiddleware(thread_id=thread_id)
    request = _request(
        "enrich_with_bio_oracle",
        "Enrichis mon fichier avec Bio-ORACLE",
    )

    result = middleware.wrap_tool_call(request, _success)

    assert validate_tool_artifact(result.artifact).status == "success"


def test_graph_render_is_blocked_by_exposure_before_workflow_guard(
    monkeypatch, tmp_path
):
    import agent as agent_module

    thread_id = "graph-hidden"
    store = _loaded_store(tmp_path, thread_id)
    monkeypatch.setattr("tools.session_store.default_store", store)
    middleware = agent_module._ContextMiddleware(thread_id=thread_id)
    request = _request("run_graph", "Fais une carte")

    result = middleware.wrap_tool_call(request, _success)

    artifact = validate_tool_artifact(result.artifact)
    assert artifact.status == "blocked"
    assert artifact.provenance["source"] == "tool_exposure_policy"


@pytest.mark.asyncio
async def test_async_hidden_legacy_tool_is_blocked(monkeypatch, tmp_path):
    import agent as agent_module

    store = SessionStore(tmp_path)
    monkeypatch.setattr("tools.session_store.default_store", store)
    middleware = agent_module._ContextMiddleware(thread_id="async-hidden")
    request = _request("query_ogsl", "Utilise OGSL")

    result = await middleware.awrap_tool_call(request, _asuccess)

    artifact = validate_tool_artifact(result.artifact)
    assert artifact.status == "blocked"
    assert artifact.provenance["source"] == "tool_exposure_policy"


def test_source_scope_rejection_keeps_priority(monkeypatch, tmp_path):
    import agent as agent_module

    store = SessionStore(tmp_path)
    monkeypatch.setattr("tools.session_store.default_store", store)
    middleware = agent_module._ContextMiddleware(thread_id="source-first")
    request = _request("query_bio_oracle", "Sans Bio-ORACLE")

    result = middleware.wrap_tool_call(request, _success)

    artifact = validate_tool_artifact(result.artifact)
    assert artifact.status == "blocked"
    assert artifact.provenance["source"] == "source_policy"
