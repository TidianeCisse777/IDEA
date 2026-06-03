"""Smoke tests for the surviving session routes (online-mode only)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure copepod agent is registered so the online-mode route accepts copepod sessions.
import agents.copepod_profile  # noqa: F401

from core.auth import get_auth_token
from core.session_store import InMemorySessionStore
from routers.session_routes import router as session_router


def _client(store: InMemorySessionStore) -> TestClient:
    app = FastAPI()
    app.include_router(session_router)
    app.dependency_overrides[get_auth_token] = lambda: "test-token"
    return TestClient(app)


def _headers(session_id: str = "s1", agent_type: str = "copepod") -> dict:
    return {"x-session-id": session_id, "x-agent-type": agent_type}


def test_online_mode_get_returns_disabled_by_default():
    store = InMemorySessionStore()
    fake_user = SimpleNamespace(id="u1")
    with patch("routers.session_routes.get_current_user", return_value=fake_user), \
         patch("routers.session_routes.session_store", store):
        client = _client(store)
        response = client.get("/session/online-mode", headers=_headers())
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_online_mode_put_persists_state():
    store = InMemorySessionStore()
    fake_user = SimpleNamespace(id="u1")
    with patch("routers.session_routes.get_current_user", return_value=fake_user), \
         patch("routers.session_routes.session_store", store):
        client = _client(store)
        put_response = client.put("/session/online-mode", json={"enabled": True}, headers=_headers())
        get_response = client.get("/session/online-mode", headers=_headers())
    assert put_response.status_code == 200
    assert get_response.status_code == 200
    assert get_response.json()["enabled"] is True


def test_online_mode_requires_copepod_agent():
    store = InMemorySessionStore()
    fake_user = SimpleNamespace(id="u1")
    with patch("routers.session_routes.get_current_user", return_value=fake_user), \
         patch("routers.session_routes.session_store", store):
        client = _client(store)
        response = client.get("/session/online-mode", headers=_headers(agent_type="generic"))
    assert response.status_code == 404


def test_session_id_required():
    store = InMemorySessionStore()
    client = _client(store)
    response = client.get("/session/online-mode")
    assert response.status_code == 400


def test_no_plan_or_analyse_route_remains():
    """POST to /session/mode must not be accepted: only the GET stub remains."""
    store = InMemorySessionStore()
    fake_user = SimpleNamespace(id="u1")
    with patch("routers.session_routes.get_current_user", return_value=fake_user), \
         patch("routers.session_routes.session_store", store):
        client = _client(store)
        response = client.post("/session/mode", json={"mode": "analyse"}, headers=_headers())
    # GET /session/mode exists as a stub → POST returns 405 (method not allowed),
    # which still proves the plan/analyse mutation endpoint is gone.
    assert response.status_code == 405
