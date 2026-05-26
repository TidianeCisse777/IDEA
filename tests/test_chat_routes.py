"""
Tests for chat_routes.py:
- Pure helper functions (_pretty_json, _format_mcp_result, _summarize_mcp_result,
  _extract_json_payload, _render_repo_table)
- /history endpoint
- /clear endpoint
- /load-conversation endpoint
- /chat guard paths (no LLM streaming)

Auth and session_store are mocked — no Redis or DB required.
"""
from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Stub the `interpreter` package before it is imported by chat_routes ───────
# The installed interpreter package pulls in html2text + many heavy deps that
# are not available in the test environment.  We inject a minimal stub so the
# module-level `from interpreter.core.core import OpenInterpreter` succeeds.
_interp_stub = ModuleType("interpreter")
_core_stub    = ModuleType("interpreter.core")
_cc_stub      = ModuleType("interpreter.core.core")
_cc_stub.OpenInterpreter = MagicMock  # type: ignore[attr-defined]
_interp_stub.core = _core_stub  # type: ignore[attr-defined]
_core_stub.core = _cc_stub  # type: ignore[attr-defined]
for _name, _mod in [
    ("interpreter", _interp_stub),
    ("interpreter.core", _core_stub),
    ("interpreter.core.core", _cc_stub),
]:
    sys.modules.setdefault(_name, _mod)

# Stub paperqa and its sub-modules (rag_store.py imports all of these)
_paperqa_stub = ModuleType("paperqa")
_paperqa_stub.Settings = MagicMock       # type: ignore[attr-defined]
_paperqa_stub.Docs = MagicMock           # type: ignore[attr-defined]
_pqa_settings_stub = ModuleType("paperqa.settings")
_pqa_settings_stub.AgentSettings = MagicMock   # type: ignore[attr-defined]
_pqa_settings_stub.IndexSettings = MagicMock   # type: ignore[attr-defined]
_pqa_agents_stub = ModuleType("paperqa.agents")
_pqa_search_stub = ModuleType("paperqa.agents.search")
_pqa_search_stub.get_directory_index = MagicMock  # type: ignore[attr-defined]
_pqa_search_stub.SearchIndex = MagicMock          # type: ignore[attr-defined]
for _name, _mod in [
    ("paperqa", _paperqa_stub),
    ("paperqa.settings", _pqa_settings_stub),
    ("paperqa.agents", _pqa_agents_stub),
    ("paperqa.agents.search", _pqa_search_stub),
]:
    sys.modules.setdefault(_name, _mod)
for _heavy in ["html2text"]:
    sys.modules.setdefault(_heavy, ModuleType(_heavy))
# ─────────────────────────────────────────────────────────────────────────────

import agents.copepod_profile  # noqa: F401 — ensures copepod is registered
import agents.generic_profile  # noqa: F401 — ensures generic is registered
from core.auth import get_auth_token
from core.session_store import InMemorySessionStore
from routers.chat_routes import (
    _extract_json_payload,
    _format_mcp_result,
    _pretty_json,
    _render_repo_table,
    _summarize_mcp_result,
    router,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def ensure_agents_registered():
    """Re-register both profiles in case another test cleared the registry."""
    importlib.reload(agents.generic_profile)
    importlib.reload(agents.copepod_profile)


@pytest.fixture()
def client():
    """Minimal FastAPI app with auth + session_store mocked."""
    store = InMemorySessionStore()
    app = FastAPI()
    app.include_router(router)

    fake_user = MagicMock()
    fake_user.id = "u1"

    app.dependency_overrides[get_auth_token] = lambda: "test-token"

    with (
        patch("routers.chat_routes.get_current_user", return_value=fake_user),
        patch("routers.chat_routes.session_store", store),
        patch("routers.chat_routes.clear_session", side_effect=lambda key: store.evict(key)),
    ):
        yield TestClient(app), store


@pytest.fixture()
def unauth_client():
    """Client where get_current_user returns None (invalid token)."""
    store = InMemorySessionStore()
    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[get_auth_token] = lambda: "bad-token"

    with (
        patch("routers.chat_routes.get_current_user", return_value=None),
        patch("routers.chat_routes.session_store", store),
    ):
        yield TestClient(app), store


# ---------------------------------------------------------------------------
# Helper: _pretty_json
# ---------------------------------------------------------------------------

class TestPrettyJson:
    def test_simple_dict_rendered(self):
        out = _pretty_json({"key": "value"})
        assert '"key"' in out
        assert '"value"' in out

    def test_truncates_at_max_length(self):
        big = {"data": "x" * 5000}
        out = _pretty_json(big, max_length=100)
        assert len(out) == 100
        assert out.endswith("...")

    def test_exact_max_length_not_truncated(self):
        # A string of exactly max_length chars should not be truncated
        text = "a" * 10
        out = _pretty_json(text, max_length=100)
        # JSON encoding of a 10-char string adds quotes → 12 chars, under limit
        assert not out.endswith("...")

    def test_non_serialisable_falls_back_to_str(self):
        class _Obj:
            def __repr__(self):
                return "unserializable"

        out = _pretty_json(_Obj())
        assert "unserializable" in out

    def test_list_input(self):
        out = _pretty_json([1, 2, 3])
        assert "1" in out and "2" in out and "3" in out


# ---------------------------------------------------------------------------
# Helper: _format_mcp_result
# ---------------------------------------------------------------------------

class TestFormatMcpResult:
    def test_structured_content_path(self):
        result = {"structuredContent": {"items": [1, 2]}}
        out = _format_mcp_result(result)
        assert "items" in out

    def test_content_list_with_json_text(self):
        result = {"content": [{"type": "text", "text": '{"key": "val"}'}]}
        out = _format_mcp_result(result)
        assert '"key"' in out

    def test_content_list_with_plain_text(self):
        result = {"content": [{"type": "text", "text": "plain answer"}]}
        out = _format_mcp_result(result)
        assert "plain answer" in out

    def test_plain_dict_fallback(self):
        result = {"foo": "bar"}
        out = _format_mcp_result(result)
        assert "foo" in out

    def test_error_fallback_on_non_dict(self):
        # Should not raise even for weird input
        out = _format_mcp_result(None)
        assert isinstance(out, str)

    def test_empty_content_list_falls_through(self):
        result = {"content": []}
        out = _format_mcp_result(result)
        assert isinstance(out, str)


# ---------------------------------------------------------------------------
# Helper: _summarize_mcp_result
# ---------------------------------------------------------------------------

class TestSummarizeMcpResult:
    def test_is_error_returns_error(self):
        result = {"isError": True}
        assert _summarize_mcp_result(result) == "error"

    def test_items_list_returns_count(self):
        result = {"items": [1, 2, 3]}
        assert _summarize_mcp_result(result) == "3 items"

    def test_login_field_returns_login(self):
        result = {"login": "octocat"}
        assert _summarize_mcp_result(result) == "login octocat"

    def test_nested_login_in_details(self):
        result = {"details": {"login": "torvalds"}}
        assert _summarize_mcp_result(result) == "login torvalds"

    def test_default_returns_done(self):
        assert _summarize_mcp_result({"other": "stuff"}) == "done"

    def test_error_in_content_list(self):
        result = {"content": [{"text": '{"isError": true}'}]}
        assert _summarize_mcp_result(result) == "error"

    def test_items_in_content_list(self):
        result = {"content": [{"text": '{"items": ["a","b"]}'}]}
        assert _summarize_mcp_result(result) == "2 items"

    def test_exception_returns_done(self):
        # Passing completely broken input should never raise
        assert _summarize_mcp_result(object()) == "done"


# ---------------------------------------------------------------------------
# Helper: _extract_json_payload
# ---------------------------------------------------------------------------

class TestExtractJsonPayload:
    def test_structured_content_extracted(self):
        result = {"structuredContent": {"repos": []}}
        out = _extract_json_payload(result)
        assert out == {"repos": []}

    def test_content_list_json_text_extracted(self):
        result = {"content": [{"text": '{"key": 1}'}]}
        out = _extract_json_payload(result)
        assert out == {"key": 1}

    def test_content_list_array_json_extracted(self):
        result = {"content": [{"text": '[1, 2, 3]'}]}
        out = _extract_json_payload(result)
        assert out == [1, 2, 3]

    def test_plain_dict_passthrough(self):
        result = {"plain": "value"}
        out = _extract_json_payload(result)
        assert out == {"plain": "value"}

    def test_non_dict_passthrough(self):
        assert _extract_json_payload("hello") == "hello"
        assert _extract_json_payload(42) == 42


# ---------------------------------------------------------------------------
# Helper: _render_repo_table
# ---------------------------------------------------------------------------

class TestRenderRepoTable:
    def _payload(self, items):
        return {"items": items}

    def test_renders_header_line(self):
        out = _render_repo_table(self._payload([]))
        assert "name" in out and "visibility" in out

    def test_renders_repo_row(self):
        repo = {
            "name": "my-repo",
            "private": False,
            "updated_at": "2024-01-01T00:00:00Z",
            "html_url": "https://github.com/u/my-repo",
            "description": "A test repo",
        }
        out = _render_repo_table(self._payload([repo]))
        assert "my-repo" in out
        assert "public" in out

    def test_private_repo_shows_private(self):
        repo = {"name": "secret", "private": True}
        out = _render_repo_table(self._payload([repo]))
        assert "private" in out

    def test_empty_items_shows_no_repos_found(self):
        out = _render_repo_table(self._payload([]))
        assert "no repositories found" in out

    def test_list_input_instead_of_dict(self):
        repos = [{"name": "r1"}, {"name": "r2"}]
        out = _render_repo_table(repos)
        assert "r1" in out and "r2" in out


# ---------------------------------------------------------------------------
# /history endpoint
# ---------------------------------------------------------------------------

class TestHistoryEndpoint:
    def test_returns_stored_messages(self, client):
        tc, store = client
        store.write_messages("u1:s1:generic", [{"role": "user", "content": "hello"}])
        resp = tc.get("/history", headers={"x-session-id": "s1"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["content"] == "hello"

    def test_returns_empty_list_when_no_messages(self, client):
        tc, _ = client
        resp = tc.get("/history", headers={"x-session-id": "s-new"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_error_when_no_session_id(self, client):
        tc, _ = client
        resp = tc.get("/history")
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_returns_error_on_invalid_token(self, unauth_client):
        tc, _ = unauth_client
        resp = tc.get("/history", headers={"x-session-id": "s1"})
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_returns_multiple_messages(self, client):
        tc, store = client
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        store.write_messages("u1:s2:generic", msgs)
        resp = tc.get("/history", headers={"x-session-id": "s2"})
        assert len(resp.json()) == 2


# ---------------------------------------------------------------------------
# /clear endpoint
# ---------------------------------------------------------------------------

class TestClearEndpoint:
    def test_returns_400_when_missing_session_id(self, client):
        tc, _ = client
        resp = tc.post("/clear")
        assert resp.status_code == 400

    def test_returns_401_when_invalid_token(self, unauth_client):
        tc, _ = unauth_client
        resp = tc.post("/clear", headers={"x-session-id": "s1"})
        assert resp.status_code == 401

    def test_clears_session_messages(self, client):
        tc, store = client
        store.write_messages("u1:s1:generic", [{"role": "user", "content": "old"}])
        resp = tc.post("/clear", headers={"x-session-id": "s1"})
        assert resp.status_code == 200
        assert resp.json() == {"status": "Chat history cleared"}

    def test_session_is_emptied_after_clear(self, client):
        tc, store = client
        store.write_messages("u1:s3:generic", [{"role": "user", "content": "old"}])
        tc.post("/clear", headers={"x-session-id": "s3"})
        # After clear, the session should have no stored messages
        assert store.read_messages("u1:s3:generic") is None

    def test_clear_on_empty_session_still_succeeds(self, client):
        tc, _ = client
        resp = tc.post("/clear", headers={"x-session-id": "s-never-used"})
        assert resp.status_code == 200
        assert resp.json() == {"status": "Chat history cleared"}


# ---------------------------------------------------------------------------
# /load-conversation endpoint
# ---------------------------------------------------------------------------

class TestLoadConversationEndpoint:
    def test_returns_400_when_missing_session_id(self, client):
        tc, _ = client
        resp = tc.post("/load-conversation", json={"messages": []})
        assert resp.status_code == 400

    def test_returns_401_when_invalid_token(self, unauth_client):
        tc, _ = unauth_client
        resp = tc.post(
            "/load-conversation",
            json={"messages": []},
            headers={"x-session-id": "s1"},
        )
        assert resp.status_code == 401

    def test_loads_user_and_assistant_messages(self, client):
        tc, store = client
        msgs = [
            {"role": "user", "content": "Hello", "message_type": "message"},
            {"role": "assistant", "content": "Hi there", "message_type": "message"},
        ]
        resp = tc.post(
            "/load-conversation",
            json={"messages": msgs},
            headers={"x-session-id": "s1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "Conversation loaded"
        assert data["message_count"] == 2

    def test_filters_console_active_line(self, client):
        tc, store = client
        msgs = [
            {"role": "user", "content": "Hello"},
            # this should be filtered
            {"role": "assistant", "content": "x", "message_type": "console", "message_format": "active_line"},
        ]
        resp = tc.post(
            "/load-conversation",
            json={"messages": msgs},
            headers={"x-session-id": "s1"},
        )
        assert resp.json()["message_count"] == 1

    def test_filters_computer_console_messages(self, client):
        tc, store = client
        msgs = [
            {"role": "user", "content": "run code"},
            {"role": "computer", "content": "stdout line", "message_type": "console"},
        ]
        resp = tc.post(
            "/load-conversation",
            json={"messages": msgs},
            headers={"x-session-id": "s1"},
        )
        assert resp.json()["message_count"] == 1

    def test_converts_non_console_computer_to_user_role(self, client):
        tc, store = client
        msgs = [
            {
                "role": "computer",
                "content": "some image",
                "message_type": "image",
                "message_format": "base64.png",
            }
        ]
        resp = tc.post(
            "/load-conversation",
            json={"messages": msgs},
            headers={"x-session-id": "s1"},
        )
        assert resp.status_code == 200
        stored = store.read_messages("u1:s1:generic")
        assert stored is not None
        assert stored[0]["role"] == "user"
        assert stored[0]["type"] == "image"

    def test_messages_written_to_store(self, client):
        tc, store = client
        msgs = [{"role": "user", "content": "test message"}]
        tc.post(
            "/load-conversation",
            json={"messages": msgs},
            headers={"x-session-id": "s-load"},
        )
        stored = store.read_messages("u1:s-load:generic")
        assert stored is not None
        assert len(stored) == 1
        assert stored[0]["content"] == "test message"

    def test_user_message_has_correct_shape(self, client):
        tc, store = client
        msgs = [{"role": "user", "content": "question"}]
        tc.post(
            "/load-conversation",
            json={"messages": msgs},
            headers={"x-session-id": "s-shape"},
        )
        stored = store.read_messages("u1:s-shape:generic")
        assert stored[0] == {"role": "user", "type": "message", "content": "question"}

    def test_empty_messages_list_returns_zero_count(self, client):
        tc, _ = client
        resp = tc.post(
            "/load-conversation",
            json={"messages": []},
            headers={"x-session-id": "s-empty"},
        )
        assert resp.status_code == 200
        assert resp.json()["message_count"] == 0


# ---------------------------------------------------------------------------
# /chat endpoint — guard paths only (no LLM streaming)
# ---------------------------------------------------------------------------

def _make_chat_client(store: InMemorySessionStore, user=None):
    """Build a TestClient with all heavy /chat dependencies mocked."""
    app = FastAPI()
    app.include_router(router)

    if user is None:
        fake_user = MagicMock()
        fake_user.id = "u1"
    else:
        fake_user = user

    app.dependency_overrides[get_auth_token] = lambda: "test-token"

    fake_interpreter = MagicMock()
    fake_interpreter.messages = []
    fake_interpreter.llm = MagicMock()
    fake_interpreter.llm.model = "gpt-4o"

    fake_profile = MagicMock()
    fake_profile.get_custom_instructions.return_value = ""

    return app, fake_user, fake_interpreter, fake_profile


class TestChatGuardPaths:
    def test_returns_400_when_missing_session_id(self):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)

        async def fake_gather(db):
            return [], {}

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )
        assert resp.status_code == 400

    def test_returns_400_when_no_messages(self):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)

        async def fake_gather(db):
            return [], {}

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": []},
                headers={"x-session-id": "s1"},
            )
        assert resp.status_code == 400

    def test_returns_401_when_invalid_token(self):
        store = InMemorySessionStore()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_auth_token] = lambda: "bad-token"

        async def fake_gather(db):
            return [], {}

        fake_interpreter = MagicMock()
        fake_profile = MagicMock()
        fake_profile.get_custom_instructions.return_value = ""

        with (
            patch("routers.chat_routes.get_current_user", return_value=None),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "hello"}]},
                headers={"x-session-id": "s1"},
            )
        assert resp.status_code == 401
