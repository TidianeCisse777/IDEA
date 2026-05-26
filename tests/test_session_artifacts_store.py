"""Tests for versioned session artifacts in InMemorySessionStore."""
from core.session_store import InMemorySessionStore


def test_create_artifact_version_stores_draft_with_data_understanding_prefix():
    store = InMemorySessionStore()
    payload = {"summary": "observations"}

    artifact = store.create_artifact_version(
        "user:sess:copepod",
        "data_understanding",
        payload,
    )

    assert artifact["version_id"].startswith("du-")
    assert artifact["artifact_type"] == "data_understanding"
    assert artifact["status"] == "draft"
    assert artifact["created_at"] is not None
    assert artifact["activated_at"] is None
    assert artifact["payload"] == payload
    assert store.get_artifact_versions("user:sess:copepod", "data_understanding") == [
        artifact
    ]


def test_create_artifact_version_stores_draft_with_graph_context_prefix():
    store = InMemorySessionStore()

    artifact = store.create_artifact_version(
        "user:sess:copepod",
        "graph_context",
        {"nodes": []},
    )

    assert artifact["version_id"].startswith("gc-")
    assert artifact["artifact_type"] == "graph_context"
    assert artifact["status"] == "draft"


def test_activate_artifact_version_sets_single_active_and_supersedes_previous_active():
    store = InMemorySessionStore()
    first = store.create_artifact_version("session", "data_understanding", {"v": 1})
    second = store.create_artifact_version("session", "data_understanding", {"v": 2})

    activated_first = store.activate_artifact_version(
        "session",
        "data_understanding",
        first["version_id"],
    )
    activated_second = store.activate_artifact_version(
        "session",
        "data_understanding",
        second["version_id"],
    )

    assert activated_first["status"] == "superseded"
    assert activated_second["status"] == "active"
    assert activated_second["activated_at"] is not None
    assert store.get_active_artifact("session", "data_understanding") == activated_second
    assert [v["status"] for v in store.get_artifact_versions("session", "data_understanding")] == [
        "superseded",
        "active",
    ]


def test_has_active_copepod_plan_artifacts_requires_active_data_and_graph_artifacts():
    store = InMemorySessionStore()
    data = store.create_artifact_version("session", "data_understanding", {"data": True})
    graph = store.create_artifact_version(
        "session",
        "graph_context",
        {"data_understanding_version_id": data["version_id"], "graph": True},
    )

    assert store.has_active_copepod_plan_artifacts("session") is False

    store.activate_artifact_version("session", "data_understanding", data["version_id"])
    assert store.has_active_copepod_plan_artifacts("session") is False

    store.activate_artifact_version("session", "graph_context", graph["version_id"])
    assert store.has_active_copepod_plan_artifacts("session") is True


def test_has_active_copepod_plan_artifacts_requires_graph_to_reference_active_data():
    store = InMemorySessionStore()
    first_data = store.create_artifact_version(
        "session", "data_understanding", {"data": "old"}
    )
    second_data = store.create_artifact_version(
        "session", "data_understanding", {"data": "current"}
    )
    graph = store.create_artifact_version(
        "session",
        "graph_context",
        {"data_understanding_version_id": first_data["version_id"]},
    )

    store.activate_artifact_version(
        "session", "data_understanding", second_data["version_id"]
    )
    store.activate_artifact_version("session", "graph_context", graph["version_id"])

    assert store.has_active_copepod_plan_artifacts("session") is False


def test_has_active_copepod_plan_artifacts_rejects_graph_without_data_reference():
    store = InMemorySessionStore()
    data = store.create_artifact_version("session", "data_understanding", {"data": True})
    graph = store.create_artifact_version("session", "graph_context", {"graph": True})

    store.activate_artifact_version("session", "data_understanding", data["version_id"])
    store.activate_artifact_version("session", "graph_context", graph["version_id"])

    assert store.has_active_copepod_plan_artifacts("session") is False


def test_artifacts_are_isolated_per_session():
    store = InMemorySessionStore()
    artifact = store.create_artifact_version("session-a", "graph_context", {"a": 1})
    store.activate_artifact_version("session-a", "graph_context", artifact["version_id"])

    assert store.get_artifact_versions("session-b", "graph_context") == []
    assert store.get_active_artifact("session-b", "graph_context") is None


def test_failed_activation_does_not_supersede_current_active():
    store = InMemorySessionStore()
    current = store.create_artifact_version("session", "data_understanding", {"v": 1})
    store.activate_artifact_version("session", "data_understanding", current["version_id"])

    try:
        store.activate_artifact_version("session", "data_understanding", "du-missing")
    except KeyError:
        pass

    active = store.get_active_artifact("session", "data_understanding")
    assert active["version_id"] == current["version_id"]
    assert active["status"] == "active"


def test_evict_clears_artifact_state():
    store = InMemorySessionStore()
    data = store.create_artifact_version("session", "data_understanding", {"data": True})
    graph = store.create_artifact_version("session", "graph_context", {"graph": True})
    store.activate_artifact_version("session", "data_understanding", data["version_id"])
    store.activate_artifact_version("session", "graph_context", graph["version_id"])

    store.evict("session")

    assert store.get_artifact_versions("session", "data_understanding") == []
    assert store.get_artifact_versions("session", "graph_context") == []
    assert store.has_active_copepod_plan_artifacts("session") is False


def test_copepod_plan_phase_defaults_to_data_understanding_draft_required():
    store = InMemorySessionStore()

    assert (
        store.get_copepod_plan_phase("session")
        == "data_understanding_draft_required"
    )


def test_copepod_plan_phase_can_be_advanced_and_is_evicted_with_session():
    store = InMemorySessionStore()

    store.set_copepod_plan_phase(
        "session",
        "data_understanding_confirmation_required",
    )

    assert (
        store.get_copepod_plan_phase("session")
        == "data_understanding_confirmation_required"
    )

    store.evict("session")

    assert (
        store.get_copepod_plan_phase("session")
        == "data_understanding_draft_required"
    )
