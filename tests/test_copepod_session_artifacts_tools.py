import pytest

from unittest.mock import patch

from core.session_store import InMemorySessionStore

pytestmark = pytest.mark.tool_contract


def _load_tools():
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_session_artifacts  # noqa: F401

    code = registry.render({"copepod_artifacts"})
    ns = {}
    exec(code, ns)
    return ns


def test_create_and_activate_data_understanding_via_tools():
    store = InMemorySessionStore()
    tools = _load_tools()

    with (
        patch("core.session_store.session_store", store),
        patch("core.copepod_observability.trace_copepod_event") as trace_event,
    ):
        draft = tools["create_data_understanding_draft"](
            "u1:s1:copepod",
            {
                "files": [
                    {
                        "file_path": "static/u1/s1/uploads/a.csv",
                        "original_filename": "a.csv",
                        "size_bytes": 12,
                        "content_hash": "sha256:abc",
                        "uploaded_at": "2026-05-26T10:00:00+00:00",
                        "inspection_tool_version": "inspect_file:v1",
                    }
                ]
            },
        )
        active = tools["activate_data_understanding"](
            "u1:s1:copepod", draft["version_id"]
        )

    assert draft["status"] == "draft"
    assert active["status"] == "active"
    assert (
        store.get_active_artifact("u1:s1:copepod", "data_understanding")[
            "version_id"
        ]
        == draft["version_id"]
    )
    draft_trace = trace_event.call_args_list[0]
    assert draft_trace.args[0] == "data_understanding_draft_created"
    assert draft_trace.kwargs["session_key"] == "u1:s1:copepod"
    assert draft_trace.kwargs["output"]["version_id"] == draft["version_id"]
    assert draft_trace.kwargs["output"]["status"] == "draft"
    active_trace = trace_event.call_args_list[1]
    assert active_trace.args[0] == "data_understanding_activated"
    assert active_trace.kwargs["session_key"] == "u1:s1:copepod"
    assert active_trace.kwargs["output"]["version_id"] == active["version_id"]
    assert active_trace.kwargs["output"]["status"] == "active"
    assert (
        store.get_copepod_plan_phase("u1:s1:copepod")
        == "graph_context_draft_required"
    )


def test_data_understanding_draft_advances_to_confirmation_phase():
    store = InMemorySessionStore()
    tools = _load_tools()
    session_key = "u1:s1:copepod"

    with patch("core.session_store.session_store", store):
        draft = tools["create_data_understanding_draft"](
            session_key,
            {"files": [{"original_filename": "a.tsv"}]},
        )

    assert draft["status"] == "draft"
    assert (
        store.get_copepod_plan_phase(session_key)
        == "data_understanding_confirmation_required"
    )


def test_data_understanding_activation_blocks_until_confirmation_phase():
    store = InMemorySessionStore()
    tools = _load_tools()
    session_key = "u1:s1:copepod"
    draft = store.create_artifact_version(
        session_key,
        "data_understanding",
        {"files": []},
    )

    with patch("core.session_store.session_store", store):
        result = tools["activate_data_understanding"](
            session_key,
            draft["version_id"],
        )

    assert result["activated"] is False
    assert "data_understanding_confirmation_required" in result["blocking_reason"]
    assert store.get_active_artifact(session_key, "data_understanding") is None


def test_create_graph_context_requires_data_understanding_version_reference():
    store = InMemorySessionStore()
    tools = _load_tools()
    session_key = "u1:s1:copepod"

    with (
        patch("core.session_store.session_store", store),
        patch("core.copepod_observability.trace_copepod_event") as trace_event,
    ):
        # Must have an active DU artifact before creating a GC draft.
        du = store.create_artifact_version(session_key, "data_understanding", {"columns": []})
        store.activate_artifact_version(session_key, "data_understanding", du["version_id"])
        store.set_copepod_plan_phase(session_key, "graph_context_draft_required")

        result = tools["create_graph_context_draft"](
            session_key,
            {
                "objective": "Distribution verticale",
                "data_understanding_version_id": du["version_id"],
                "language": "Python",
                "feasibility": "reliable",
            },
        )

    assert result["artifact_type"] == "graph_context"
    assert result["payload"]["data_understanding_version_id"] == du["version_id"]
    assert (
        store.get_copepod_plan_phase(session_key)
        == "graph_context_confirmation_required"
    )
    assert trace_event.call_args.args[0] == "graph_context_draft_created"
    assert trace_event.call_args.kwargs["session_key"] == session_key
    trace_output = trace_event.call_args.kwargs["output"]
    assert trace_output["version_id"] == result["version_id"]
    assert trace_output["status"] == "draft"
    assert trace_output["data_understanding_version_id"] == du["version_id"]


def test_create_graph_context_without_data_understanding_version_blocks():
    tools = _load_tools()
    with patch("core.copepod_observability.trace_copepod_event") as trace_event:
        result = tools["create_graph_context_draft"](
            "u1:s1:copepod",
            {"objective": "Distribution verticale"},
        )

    assert result["created"] is False
    assert "data_understanding_version_id" in result["blocking_reason"]
    trace_event.assert_called_with(
        "graph_context_draft_blocked",
        session_key="u1:s1:copepod",
        output={"blocking_reason": result["blocking_reason"]},
    )


def test_graph_context_draft_blocks_until_graph_context_draft_phase():
    store = InMemorySessionStore()
    tools = _load_tools()
    session_key = "u1:s1:copepod"
    du = store.create_artifact_version(session_key, "data_understanding", {"files": []})
    store.activate_artifact_version(session_key, "data_understanding", du["version_id"])

    with patch("core.session_store.session_store", store):
        result = tools["create_graph_context_draft"](
            session_key,
            {
                "data_understanding_version_id": du["version_id"],
                "objective": "Distribution verticale",
            },
        )

    assert result["created"] is False
    assert "graph_context_draft_required" in result["blocking_reason"]


def test_graph_context_activation_blocks_until_confirmation_phase():
    store = InMemorySessionStore()
    tools = _load_tools()
    session_key = "u1:s1:copepod"
    du = store.create_artifact_version(session_key, "data_understanding", {"files": []})
    store.activate_artifact_version(session_key, "data_understanding", du["version_id"])
    graph = store.create_artifact_version(
        session_key,
        "graph_context",
        {"data_understanding_version_id": du["version_id"]},
    )

    with patch("core.session_store.session_store", store):
        result = tools["activate_graph_context"](session_key, graph["version_id"])

    assert result["activated"] is False
    assert "graph_context_confirmation_required" in result["blocking_reason"]
    assert store.get_active_artifact(session_key, "graph_context") is None


def test_graph_context_activation_advances_to_plan_ready():
    store = InMemorySessionStore()
    tools = _load_tools()
    session_key = "u1:s1:copepod"
    du = store.create_artifact_version(session_key, "data_understanding", {"files": []})
    store.activate_artifact_version(session_key, "data_understanding", du["version_id"])
    graph = store.create_artifact_version(
        session_key,
        "graph_context",
        {"data_understanding_version_id": du["version_id"]},
    )
    store.set_copepod_plan_phase(session_key, "graph_context_confirmation_required")

    with patch("core.session_store.session_store", store):
        active = tools["activate_graph_context"](session_key, graph["version_id"])

    assert active["status"] == "active"
    assert store.get_copepod_plan_phase(session_key) == "plan_ready"


def test_get_active_artifact_tools_return_current_active_versions():
    store = InMemorySessionStore()
    tools = _load_tools()
    du = store.create_artifact_version("u1:s1:copepod", "data_understanding", {"files": []})
    gc = store.create_artifact_version(
        "u1:s1:copepod",
        "graph_context",
        {"data_understanding_version_id": du["version_id"]},
    )
    store.activate_artifact_version("u1:s1:copepod", "data_understanding", du["version_id"])
    store.activate_artifact_version("u1:s1:copepod", "graph_context", gc["version_id"])

    with patch("core.session_store.session_store", store):
        active_du = tools["get_active_data_understanding"]("u1:s1:copepod")
        active_gc = tools["get_active_graph_context"]("u1:s1:copepod")

    assert active_du["version_id"] == du["version_id"]
    assert active_gc["version_id"] == gc["version_id"]


def test_copepod_profile_renders_data_and_artifact_tools():
    import importlib

    import agents.copepod_profile
    from agents.registry import get_profile

    importlib.reload(agents.copepod_profile)
    code = get_profile("copepod").get_tool_code()

    assert "def inspect_file" in code
    assert "def infer_column_roles" in code
    assert "def describe_column" in code
    assert "def create_data_understanding_draft" in code
    assert "def activate_graph_context" in code
