from __future__ import annotations

from unittest.mock import patch


def test_copepod_tool_registry_wraps_critical_tools_for_runtime_tracing(monkeypatch):
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_data  # noqa: F401

    monkeypatch.setenv("IDEA_RUNTIME_SESSION_KEY", "u1:s1:copepod")
    monkeypatch.setenv("IDEA_RUNTIME_ROUND", "3")
    code = registry.render({"copepod_data"})
    ns = {}
    exec(code, ns)

    assert ns["inspect_file"].__idea_traced__ is True
    assert ns["infer_column_roles"].__idea_traced__ is True
    assert ns["summarize_understanding"].__idea_traced__ is True

    with patch("core.copepod_observability.trace_copepod_tool_call") as trace_tool:
        result = ns["infer_column_roles"](
            [{"name": "object_depth_min", "dtype": "float64"}],
            metadata={"source": "test"},
        )

    assert "roles" in result
    trace_tool.assert_called_once()
    assert trace_tool.call_args.args[0] == "infer_column_roles"
    assert trace_tool.call_args.kwargs["session_key"] == "u1:s1:copepod"
    assert trace_tool.call_args.kwargs["metadata"]["round"] == "3"
    assert trace_tool.call_args.kwargs["metadata"]["elapsed_ms"] >= 0
    assert trace_tool.call_args.kwargs["input"]["args"][0][0]["name"] == "object_depth_min"
    assert "roles" in trace_tool.call_args.kwargs["output"]


def test_copepod_artifact_tool_tracing_uses_explicit_session_key(monkeypatch):
    from core.session_store import InMemorySessionStore
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_session_artifacts  # noqa: F401

    store = InMemorySessionStore()
    code = registry.render({"copepod_artifacts"})
    ns = {}
    exec(code, ns)

    with (
        patch("core.session_store.session_store", store),
        patch("core.copepod_observability.trace_copepod_event"),
        patch("core.copepod_observability.trace_copepod_tool_call") as trace_tool,
    ):
        draft = ns["create_data_understanding_draft"](
            "u1:s2:copepod",
            {"files": [{"original_filename": "a.tsv"}]},
        )

    assert draft["status"] == "draft"
    trace_tool.assert_called_once()
    assert trace_tool.call_args.args[0] == "create_data_understanding_draft"
    assert trace_tool.call_args.kwargs["session_key"] == "u1:s2:copepod"
    assert trace_tool.call_args.kwargs["output"]["status"] == "draft"


def test_copepod_tool_tracing_records_errors_without_swallowing(monkeypatch):
    from core.session_store import InMemorySessionStore
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_session_artifacts  # noqa: F401

    store = InMemorySessionStore()
    code = registry.render({"copepod_artifacts"})
    ns = {}
    exec(code, ns)

    with (
        patch("core.session_store.session_store", store),
        patch("core.copepod_observability.trace_copepod_event"),
        patch("core.copepod_observability.trace_copepod_tool_call") as trace_tool,
    ):
        result = ns["activate_data_understanding"]("u1:s3:copepod", "missing-version")

    assert result["activated"] is False
    assert trace_tool.call_args.args[0] == "activate_data_understanding"
    assert trace_tool.call_args.kwargs["output"]["activated"] is False
