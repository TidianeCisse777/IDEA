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
from routers.session_routes import router


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
    def test_post_mode_sets_analyse(self, client):
        tc, store = client
        resp = tc.post(
            "/session/mode",
            json={"mode": "analyse"},
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "analyse"
        assert store.get_session_mode("u1:s1:copepod") == "analyse"

    def test_post_mode_sets_plan(self, client):
        tc, store = client
        store.set_session_mode("u1:s1:copepod", "analyse")
        resp = tc.post(
            "/session/mode",
            json={"mode": "plan"},
            headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )
        assert resp.status_code == 200
        assert store.get_session_mode("u1:s1:copepod") == "plan"

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
        tc, _ = client
        resp = tc.post(
            "/session/mode",
            json={"mode": "analyse"},
            headers={"x-session-id": "s3", "x-agent-type": "copepod"},
        )
        data = resp.json()
        assert "session_key" in data
        assert "s3" in data["session_key"]

    def test_post_mode_persists_across_get(self, client):
        tc, _ = client
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
