"""
Tests for GET/POST /session/mode endpoints.

Auth and session_store are mocked — no Redis or DB required.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agents.copepod_profile  # noqa: F401 — initial registration
from core.session_store import InMemorySessionStore
from core.copepod_plan_workflow import PLAN_READY
from routers.session_routes import router

pytestmark = pytest.mark.workflow


@pytest.fixture(autouse=True)
def ensure_copepod_registered():
    """Re-register copepod in case another test file cleared the registry."""
    importlib.reload(agents.copepod_profile)


# ---------------------------------------------------------------------------
# App fixture — minimal FastAPI with only the session router
# ---------------------------------------------------------------------------

def _make_app(store: InMemorySessionStore, user_id: str = "u1") -> FastAPI:
    """Build a test app with auth bypassed and session_store replaced."""
    app = FastAPI()
    app.include_router(router)

    fake_user = MagicMock()
    fake_user.id = user_id

    app.dependency_overrides = {}

    import routers.session_routes as sr
    from core.auth import get_auth_token, get_current_user

    app.dependency_overrides[get_auth_token] = lambda: "test-token"
    app.dependency_overrides[get_current_user] = lambda token: fake_user

    return app, store


@pytest.fixture()
def client():
    store = InMemorySessionStore()
    app = FastAPI()
    app.include_router(router)

    fake_user = MagicMock()
    fake_user.id = "u1"

    from core.auth import get_auth_token

    app.dependency_overrides[get_auth_token] = lambda: "test-token"

    with (
        patch("routers.session_routes.get_current_user", return_value=fake_user),
        patch("routers.session_routes.session_store", store),
    ):
        yield TestClient(app), store


# ---------------------------------------------------------------------------
# GET /session/mode
# ---------------------------------------------------------------------------

class TestGetSessionMode:
    def test_get_mode_returns_plan_by_default(self, client):
        tc, _ = client
        resp = tc.get(
            "/session/mode",
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "plan"

    def test_get_mode_returns_session_key(self, client):
        tc, _ = client
        resp = tc.get(
            "/session/mode",
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )
        assert "session_key" in resp.json()
        assert "u1" in resp.json()["session_key"]
        assert "s1" in resp.json()["session_key"]

    def test_get_mode_missing_session_id_returns_400(self, client):
        tc, _ = client
        resp = tc.get("/session/mode")
        assert resp.status_code == 400

    def test_get_mode_reflects_stored_analyse(self, client):
        tc, store = client
        store.set_session_mode("u1:s2:copepod", "analyse")
        resp = tc.get(
            "/session/mode",
            headers={"x-session-id": "s2", "x-agent-type": "copepod"},
        )
        assert resp.json()["mode"] == "analyse"

    def test_get_mode_unknown_agent_type_falls_back_to_generic(self, client):
        tc, _ = client
        resp = tc.get(
            "/session/mode",
            headers={"x-session-id": "s1", "x-agent-type": "unknown_xyz"},
        )
        assert resp.status_code == 200
        assert "generic" in resp.json()["session_key"]


# ---------------------------------------------------------------------------
# POST /session/mode
# ---------------------------------------------------------------------------

class TestPostSessionMode:
    def _activate_required_copepod_artifacts(self, store, session_key: str) -> None:
        data = store.create_artifact_version(
            session_key,
            "data_understanding",
            {"files": [{"file_path": "static/u1/s1/uploads/a.csv"}]},
        )
        graph = store.create_artifact_version(
            session_key,
            "graph_context",
            {
                "data_understanding_version_id": data["version_id"],
                "objective": "vertical distribution",
            },
        )
        store.activate_artifact_version(
            session_key, "data_understanding", data["version_id"]
        )
        store.activate_artifact_version(session_key, "graph_context", graph["version_id"])
        store.set_copepod_plan_phase(session_key, PLAN_READY)

    def test_post_mode_sets_analyse(self, client):
        tc, store = client
        self._activate_required_copepod_artifacts(store, "u1:s1:copepod")
        resp = tc.post(
            "/session/mode",
            json={"mode": "analyse"},
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "analyse"
        assert store.get_session_mode("u1:s1:copepod") == "analyse"

    def test_post_mode_generic_sets_analyse_without_artifacts(self, client):
        tc, store = client
        resp = tc.post(
            "/session/mode",
            json={"mode": "analyse"},
            headers={"x-session-id": "s1", "x-agent-type": "generic"},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "analyse"
        assert store.get_session_mode("u1:s1:generic") == "analyse"

    @pytest.mark.parametrize(
        "active_artifacts",
        [
            set(),
            {"data_understanding"},
            {"graph_context"},
        ],
    )
    def test_post_mode_copepod_analyse_requires_active_plan_artifacts(
        self, client, active_artifacts
    ):
        tc, store = client
        session_key = "u1:s1:copepod"
        data = store.create_artifact_version(
            session_key, "data_understanding", {"files": []}
        )
        graph = store.create_artifact_version(
            session_key,
            "graph_context",
            {"data_understanding_version_id": data["version_id"]},
        )
        if "data_understanding" in active_artifacts:
            store.activate_artifact_version(
                session_key, "data_understanding", data["version_id"]
            )
        if "graph_context" in active_artifacts:
            store.activate_artifact_version(
                session_key, "graph_context", graph["version_id"]
            )

        with patch("routers.session_routes.trace_copepod_event") as trace_event:
            resp = tc.post(
                "/session/mode",
                json={"mode": "analyse"},
                headers={"x-session-id": "s1", "x-agent-type": "copepod"},
            )

        assert resp.status_code == 409
        detail = resp.json()["detail"].lower()
        if "data_understanding" not in active_artifacts:
            assert "active data understanding" in detail
        else:
            assert "active graph context" in detail
        assert store.get_session_mode(session_key) == "plan"
        trace_event.assert_called_once()
        assert trace_event.call_args.args[0] == "analyse_mode_blocked"
        assert trace_event.call_args.kwargs["session_key"] == session_key

    def test_post_mode_copepod_analyse_requires_graph_to_match_active_data(
        self, client
    ):
        tc, store = client
        session_key = "u1:s1:copepod"
        old_data = store.create_artifact_version(
            session_key, "data_understanding", {"files": ["old.tsv"]}
        )
        current_data = store.create_artifact_version(
            session_key, "data_understanding", {"files": ["current.tsv"]}
        )
        graph = store.create_artifact_version(
            session_key,
            "graph_context",
            {"data_understanding_version_id": old_data["version_id"]},
        )
        store.activate_artifact_version(
            session_key, "data_understanding", current_data["version_id"]
        )
        store.activate_artifact_version(
            session_key, "graph_context", graph["version_id"]
        )

        resp = tc.post(
            "/session/mode",
            json={"mode": "analyse"},
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )

        assert resp.status_code == 409
        assert "graph context" in resp.json()["detail"].lower()
        assert store.get_session_mode(session_key) == "plan"

    def test_post_mode_copepod_analyse_allowed_when_active_plan_artifacts_exist(
        self, client
    ):
        tc, store = client
        self._activate_required_copepod_artifacts(store, "u1:s1:copepod")

        with patch("routers.session_routes.trace_copepod_event") as trace_event:
            resp = tc.post(
                "/session/mode",
                json={"mode": "analyse"},
                headers={"x-session-id": "s1", "x-agent-type": "copepod"},
            )

        assert resp.status_code == 200
        assert resp.json()["mode"] == "analyse"
        assert store.get_session_mode("u1:s1:copepod") == "analyse"
        trace_event.assert_called_with(
            "analyse_mode_entered",
            session_key="u1:s1:copepod",
            output={"mode": "analyse"},
        )

    def test_post_mode_copepod_analyse_requires_plan_ready_phase(self, client):
        tc, store = client
        session_key = "u1:s1:copepod"
        data = store.create_artifact_version(
            session_key,
            "data_understanding",
            {"files": [{"file_path": "static/u1/s1/uploads/a.csv"}]},
        )
        graph = store.create_artifact_version(
            session_key,
            "graph_context",
            {
                "data_understanding_version_id": data["version_id"],
                "objective": "vertical distribution",
            },
        )
        store.activate_artifact_version(
            session_key, "data_understanding", data["version_id"]
        )
        store.activate_artifact_version(session_key, "graph_context", graph["version_id"])

        resp = tc.post(
            "/session/mode",
            json={"mode": "analyse"},
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )

        assert resp.status_code == 409
        assert "plan_ready" in resp.json()["detail"]
        assert store.get_session_mode(session_key) == "plan"

    def test_post_mode_generic_sets_plan_from_analyse(self, client):
        tc, store = client
        store.set_session_mode("u1:s1:generic", "analyse")
        resp = tc.post(
            "/session/mode",
            json={"mode": "plan"},
            headers={"x-session-id": "s1", "x-agent-type": "generic"},
        )
        assert resp.status_code == 200
        assert store.get_session_mode("u1:s1:generic") == "plan"

    def test_post_mode_copepod_cannot_switch_from_analyse_back_to_plan(self, client):
        tc, store = client
        store.set_session_mode("u1:s1:copepod", "analyse")
        resp = tc.post(
            "/session/mode",
            json={"mode": "plan"},
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )
        assert resp.status_code == 409
        assert "irreversible" in resp.json()["detail"].lower()
        assert store.get_session_mode("u1:s1:copepod") == "analyse"

    def test_post_invalid_mode_returns_400(self, client):
        tc, _ = client
        resp = tc.post(
            "/session/mode",
            json={"mode": "invalid_mode"},
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )
        assert resp.status_code == 400
        assert "invalid_mode" in resp.json()["detail"].lower()

    def test_post_mode_missing_session_id_returns_400(self, client):
        tc, _ = client
        resp = tc.post("/session/mode", json={"mode": "analyse"})
        assert resp.status_code == 400

    def test_post_mode_returns_session_key(self, client):
        tc, store = client
        self._activate_required_copepod_artifacts(store, "u1:s3:copepod")
        resp = tc.post(
            "/session/mode",
            json={"mode": "analyse"},
            headers={"x-session-id": "s3", "x-agent-type": "copepod"},
        )
        data = resp.json()
        assert "session_key" in data
        assert "s3" in data["session_key"]

    def test_post_mode_persists_across_get(self, client):
        tc, store = client
        self._activate_required_copepod_artifacts(store, "u1:s4:copepod")
        tc.post(
            "/session/mode",
            json={"mode": "analyse"},
            headers={"x-session-id": "s4", "x-agent-type": "copepod"},
        )
        resp = tc.get(
            "/session/mode",
            headers={"x-session-id": "s4", "x-agent-type": "copepod"},
        )
        assert resp.json()["mode"] == "analyse"


# ---------------------------------------------------------------------------
# GET/PUT /session/online-mode
# ---------------------------------------------------------------------------

class TestOnlineModeRoutes:
    def test_get_online_mode_defaults_off(self, client):
        tc, _ = client
        resp = tc.get(
            "/session/online-mode",
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["enabled"] is False
        assert payload["allowed_sources"] == ["ogsl", "bio_oracle"]

    def test_put_online_mode_can_enable_and_persist(self, client):
        tc, store = client
        resp = tc.put(
            "/session/online-mode",
            json={"enabled": True},
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["enabled"] is True
        assert store.get_online_mode("u1:s1:copepod") is True

    def test_put_online_mode_can_disable(self, client):
        tc, store = client
        store.set_online_mode("u1:s1:copepod", True)

        resp = tc.put(
            "/session/online-mode",
            json={"enabled": False},
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["enabled"] is False
        assert store.get_online_mode("u1:s1:copepod") is False


class TestGetSessionArtifacts:
    def test_get_data_understanding_returns_versions_and_active_for_copepod(
        self, client
    ):
        tc, store = client
        session_key = "u1:s1:copepod"
        first = store.create_artifact_version(
            session_key, "data_understanding", {"files": ["old.csv"]}
        )
        second = store.create_artifact_version(
            session_key, "data_understanding", {"files": ["new.csv"]}
        )
        active = store.activate_artifact_version(
            session_key, "data_understanding", second["version_id"]
        )

        resp = tc.get(
            "/session/artifacts/data-understanding",
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )

        assert resp.status_code == 200
        assert resp.json()["versions"] == [first, active]
        assert resp.json()["active"] == active

    def test_get_graph_context_returns_versions_and_active_for_copepod(self, client):
        tc, store = client
        session_key = "u1:s1:copepod"
        first = store.create_artifact_version(
            session_key, "graph_context", {"objective": "old"}
        )
        second = store.create_artifact_version(
            session_key, "graph_context", {"objective": "new"}
        )
        active = store.activate_artifact_version(
            session_key, "graph_context", second["version_id"]
        )

        resp = tc.get(
            "/session/artifacts/graph-context",
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )

        assert resp.status_code == 200
        assert resp.json()["versions"] == [first, active]
        assert resp.json()["active"] == active

    @pytest.mark.parametrize(
        "path",
        [
            "/session/artifacts/data-understanding",
            "/session/artifacts/graph-context",
        ],
    )
    def test_debug_artifact_routes_are_copepod_only(self, client, path):
        tc, _ = client
        resp = tc.get(
            path,
            headers={"x-session-id": "s1", "x-agent-type": "generic"},
        )
        assert resp.status_code == 404
