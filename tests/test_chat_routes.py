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

import base64
import importlib
import os
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import requests

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

# Force SQLAlchemy to use SQLite for the test import path so core.db does not
# require a Postgres driver in this isolated environment.
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

_core_auth_stub = ModuleType("core.auth")
def _stub_get_auth_token():
    return "test-token"

def _stub_get_current_user(token):
    return None

def _stub_get_db():
    yield None

_core_auth_stub.get_auth_token = _stub_get_auth_token  # type: ignore[attr-defined]
_core_auth_stub.get_current_user = _stub_get_current_user  # type: ignore[attr-defined]
_core_auth_stub.get_db = _stub_get_db  # type: ignore[attr-defined]
_core_crud_stub = ModuleType("core.crud")
_core_crud_stub.list_active_mcp_connections = MagicMock(return_value=[])  # type: ignore[attr-defined]
_core_crud_stub.__getattr__ = lambda name: MagicMock()  # type: ignore[attr-defined]
_core_mcp_stub = ModuleType("core.mcp")
_core_mcp_stub.mcp_manager = MagicMock()  # type: ignore[attr-defined]
_core_mcp_stub.__getattr__ = lambda name: MagicMock()  # type: ignore[attr-defined]
_models_stub = ModuleType("models")
_models_stub.MCPConnection = MagicMock()  # type: ignore[attr-defined]
_models_stub.User = MagicMock()  # type: ignore[attr-defined]
_models_stub.__getattr__ = lambda name: MagicMock()  # type: ignore[attr-defined]
for _name, _mod in [
    ("core.auth", _core_auth_stub),
    ("core.crud", _core_crud_stub),
    ("core.mcp", _core_mcp_stub),
    ("models", _models_stub),
]:
    sys.modules.setdefault(_name, _mod)

_litellm_stub = ModuleType("litellm")
_litellm_stub.completion = MagicMock()  # type: ignore[attr-defined]
_litellm_stub.transcription = MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("litellm", _litellm_stub)

_multipart_stub = ModuleType("multipart")
_multipart_stub.__version__ = "0.0.0"  # type: ignore[attr-defined]
_multipart_sub_stub = ModuleType("multipart.multipart")
_multipart_sub_stub.parse_options_header = MagicMock()  # type: ignore[attr-defined]
_multipart_stub.multipart = _multipart_sub_stub  # type: ignore[attr-defined]
for _name, _mod in [
    ("multipart", _multipart_stub),
    ("multipart.multipart", _multipart_sub_stub),
]:
    sys.modules.setdefault(_name, _mod)

# Stub psycopg2 so core.db can build the SQLAlchemy engine without requiring
# a real Postgres driver in the isolated test environment.
_psycopg2_stub = ModuleType("psycopg2")
_psycopg2_stub.__version__ = "2.9.10"  # type: ignore[attr-defined]
_psycopg2_stub.apilevel = "2.0"  # type: ignore[attr-defined]
_psycopg2_stub.threadsafety = 2  # type: ignore[attr-defined]
_psycopg2_stub.paramstyle = "pyformat"  # type: ignore[attr-defined]
_psycopg2_stub.connect = MagicMock()  # type: ignore[attr-defined]
_psycopg2_extensions_stub = ModuleType("psycopg2.extensions")
_psycopg2_extensions_stub.STATUS_READY = 1  # type: ignore[attr-defined]
_psycopg2_extensions_stub.register_adapter = MagicMock()  # type: ignore[attr-defined]
_psycopg2_extensions_stub.register_type = MagicMock()  # type: ignore[attr-defined]
_psycopg2_extensions_stub.adapt = MagicMock()  # type: ignore[attr-defined]
_psycopg2_extras_stub = ModuleType("psycopg2.extras")
_psycopg2_extras_stub.execute_batch = MagicMock()  # type: ignore[attr-defined]
_psycopg2_extras_stub.execute_values = MagicMock()  # type: ignore[attr-defined]
_psycopg2_stub.extensions = _psycopg2_extensions_stub  # type: ignore[attr-defined]
_psycopg2_stub.extras = _psycopg2_extras_stub  # type: ignore[attr-defined]
for _name, _mod in [
    ("psycopg2", _psycopg2_stub),
    ("psycopg2.extensions", _psycopg2_extensions_stub),
    ("psycopg2.extras", _psycopg2_extras_stub),
]:
    sys.modules.setdefault(_name, _mod)

_passlib_stub = ModuleType("passlib")
_passlib_context_stub = ModuleType("passlib.context")

class _FakeCryptContext:
    def __init__(self, *args, **kwargs):
        pass

    def verify(self, *args, **kwargs):
        return True

    def hash(self, value):
        return f"hashed:{value}"

_passlib_context_stub.CryptContext = _FakeCryptContext  # type: ignore[attr-defined]
_passlib_stub.context = _passlib_context_stub  # type: ignore[attr-defined]
for _name, _mod in [
    ("passlib", _passlib_stub),
    ("passlib.context", _passlib_context_stub),
]:
    sys.modules.setdefault(_name, _mod)

_cryptography_stub = ModuleType("cryptography")
_cryptography_fernet_stub = ModuleType("cryptography.fernet")

class _FakeInvalidToken(Exception):
    pass

class _FakeFernet:
    def __init__(self, *args, **kwargs):
        pass

    def encrypt(self, value):
        return value if isinstance(value, bytes) else str(value).encode("utf-8")

    def decrypt(self, value):
        return value

_cryptography_fernet_stub.Fernet = _FakeFernet  # type: ignore[attr-defined]
_cryptography_fernet_stub.InvalidToken = _FakeInvalidToken  # type: ignore[attr-defined]
_cryptography_stub.fernet = _cryptography_fernet_stub  # type: ignore[attr-defined]
for _name, _mod in [
    ("cryptography", _cryptography_stub),
    ("cryptography.fernet", _cryptography_fernet_stub),
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


class _FakeResponse:
    status_code = 200

    def json(self):
        return {}


def _fake_requests_get(*args, **kwargs):
    return _FakeResponse()


requests.get = _fake_requests_get
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
    _build_copepod_inspect_then_code_note,
    _build_copepod_session_resources_note,
    _session_resource_message_from_stream_event,
    _build_copepod_error_recovery_note,
    _build_copepod_report_read_retry_note,
    _build_copepod_upload_inspection_retry_note,
    _build_copepod_action_contract_retry_note,
    _build_copepod_graph_output_retry_note,
    _inject_copepod_system_note,
    _strip_system_messages,
    _extract_copepod_key_hints,
    _should_retry_copepod_error,
    _should_retry_copepod_report_read_without_code,
    _should_retry_copepod_upload_inspection_without_code,
    _should_retry_copepod_action_contract_without_code_or_questions,
    _should_retry_copepod_graph_output_without_display_or_deliverable,
    _update_copepod_working_set,
    _coerce_multimodal_message_content,
    _expand_multimodal_message_for_interpreter,
    _scrub_inspection_report_in_content,
    _scrub_inspection_reports_for_llm,
    _session_lock,
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
# Helper: _build_copepod_inspect_then_code_note
# ---------------------------------------------------------------------------

class TestCopepodInspectThenCodeNote:
    def test_returns_none_without_inspection_artifacts(self):
        note = _build_copepod_inspect_then_code_note(
            messages=[{"role": "user", "content": "fais une jointure"}],
            user_message="fais une jointure",
        )
        assert note is None

    def test_surfaces_join_keys_when_inspection_carries_them(self):
        messages = [
            {
                "role": "assistant",
                "content": (
                    "# RAPPORT D'INSPECTION\n"
                    "### Fichiers chargés\n"
                    "- **a.csv**\n"
                    "Clés de jointure potentielles : station | time | depth\n"
                ),
            }
        ]
        note = _build_copepod_inspect_then_code_note(
            messages=messages,
            user_message="fais une jointure entre les fichiers",
        )
        assert note is not None
        assert "Inspection context for this turn" in note
        assert "station | time | depth" in note
        # Permanent rules ("INSPECT required", "ask grill questions", …) MUST
        # NOT be restated here — they live in COPEPOD_SYSTEM_PROMPT.
        for forbidden in (
            "INSPECT required before code",
            "ask targeted grill questions",
            "Ask only questions that can change",
            "If the user says stop, go",
            "write the code block immediately",
        ):
            assert forbidden not in note

    def test_returns_none_when_inspection_has_no_extractable_hints(self):
        # An inspection report present but with no join keys → no useful
        # context to surface, return None rather than emit an empty header.
        messages = [
            {
                "role": "assistant",
                "content": (
                    "# RAPPORT D'INSPECTION\n"
                    "### Fichiers chargés\n"
                    "- **a.csv**\n"
                    "Colonnes: sample_id, depth_m, taxon\n"
                ),
            }
        ]
        note = _build_copepod_inspect_then_code_note(
            messages=messages,
            user_message="fais un graphe",
        )
        assert note is None

    def test_returns_recovery_note_for_traceback(self):
        note = _build_copepod_error_recovery_note(
            last_error_text="KeyError: 'station'",
            user_message="fais une jointure",
        )
        assert note is not None
        assert "recovery mode" in note.lower()
        assert "KeyError" in note
        assert "normalize the candidate keys" in note
        assert "Traceback key hint(s): station" in note

    def test_extracts_key_hints_from_common_join_tracebacks(self):
        hints = _extract_copepod_key_hints(
            "KeyError: 'station'\nNone of ['depth'] are in the columns"
        )
        assert hints == ["station", "depth"]

    def test_retry_gate_accepts_runtime_errors(self):
        assert _should_retry_copepod_error(
            "RuntimeError: upload failed",
            "fais une jointure entre les fichiers",
        )

    def test_recovery_note_mentions_encoding_retry_for_utf8_failures(self):
        note = _build_copepod_error_recovery_note(
            last_error_text="UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9 in position 4207",
            user_message="tester cette jointure",
        )
        assert note is not None
        assert "encoding='latin1'" in note
        assert "encoding='cp1252'" in note

    def test_recovery_note_for_encoding_requires_corrected_python(self):
        note = _build_copepod_error_recovery_note(
            last_error_text="UnicodeDecodeError: 'utf-8' codec can't decode byte 0xb5 in position 383",
            user_message="relance la jointure",
        )
        assert note is not None
        assert "Do not answer with a status-only message" in note
        assert "run corrected Python code" in note

    def test_report_read_retry_gate_catches_prose_only_deferral(self):
        assert _should_retry_copepod_report_read_without_code(
            user_message="FAIS MOI UN RESUME DU RAPPORT",
            assistant_text="Je dois relire le rapport out-of-context avant de répondre.",
            current_attempt_had_code=False,
            current_attempt_had_error=False,
        )

    def test_report_read_retry_gate_catches_hallucinated_key_columns_without_code(self):
        assert _should_retry_copepod_report_read_without_code(
            user_message="Quelles sont les colonnes clés ?",
            assistant_text="sample_id, station_name, cast_no, profile_no, lon, lat",
            current_attempt_had_code=False,
            current_attempt_had_error=False,
            known_columns=[
                "platform_name",
                "station",
                "amundsen_time",
                "amundsen_lat",
                "amundsen_lon",
                "amundsen_depth",
                "amundsen_temperature_degC",
            ],
        )

    def test_report_read_retry_gate_ignores_executed_attempts(self):
        assert not _should_retry_copepod_report_read_without_code(
            user_message="FAIS MOI UN RESUME DU RAPPORT",
            assistant_text="Je dois relire le rapport out-of-context avant de répondre.",
            current_attempt_had_code=True,
            current_attempt_had_error=False,
        )

    def test_report_read_retry_gate_accepts_answer_grounded_in_known_columns(self):
        assert not _should_retry_copepod_report_read_without_code(
            user_message="Quelles sont les colonnes clés ?",
            assistant_text="Colonnes clés : `station`, `amundsen_time`, `amundsen_depth`, `amundsen_temperature_degC`.",
            current_attempt_had_code=False,
            current_attempt_had_error=False,
            known_columns=[
                "platform_name",
                "station",
                "amundsen_time",
                "amundsen_depth",
                "amundsen_temperature_degC",
            ],
        )

    def test_report_read_retry_note_requires_get_inspection_report(self):
        note = _build_copepod_report_read_retry_note("la liste des colonnes clés.")
        assert "get_inspection_report" in note
        assert "Do not answer with another status-only message" in note
        assert "la liste des colonnes clés" in note

    def test_upload_inspection_retry_gate_catches_plan_without_code(self):
        assert _should_retry_copepod_upload_inspection_without_code(
            user_message="Files uploaded in this message:\n- donne_sample.csv (text/csv) | relative path: donne_sample.csv",
            pending_files=["donne_sample.csv | path: /app/static/u/s/uploads/donne_sample.csv"],
            current_attempt_had_code=False,
            current_attempt_had_error=False,
        )

    def test_upload_inspection_retry_gate_ignores_executed_attempts(self):
        assert not _should_retry_copepod_upload_inspection_without_code(
            user_message="Files uploaded in this message:\n- donne_sample.csv (text/csv) | relative path: donne_sample.csv",
            pending_files=["donne_sample.csv"],
            current_attempt_had_code=True,
            current_attempt_had_error=False,
        )

    def test_upload_inspection_retry_gate_ignores_readback_text(self):
        assert not _should_retry_copepod_upload_inspection_without_code(
            user_message="Donne moi les colonnes environnementales",
            pending_files=["donne_sample.csv"],
            current_attempt_had_code=False,
            current_attempt_had_error=False,
        )

    def test_upload_inspection_retry_note_requires_inspect_and_report(self):
        note = _build_copepod_upload_inspection_retry_note(["donne_sample.csv"])
        assert "inspect_and_report" in note
        assert "Do not answer with another plan-only or status-only message" in note
        assert "donne_sample.csv" in note

    def test_action_contract_retry_gate_catches_action_prose_without_code_or_questions(self):
        assert _should_retry_copepod_action_contract_without_code_or_questions(
            user_message="fais un graphe de l'abondance par station",
            assistant_text="Je peux faire un graphe avec les colonnes disponibles.",
            current_attempt_had_code=False,
            current_attempt_had_error=False,
        )

    def test_action_contract_retry_gate_allows_numbered_questions(self):
        assert not _should_retry_copepod_action_contract_without_code_or_questions(
            user_message="fais un graphe",
            assistant_text="**Plan**\n- Je dois fixer les axes.\n\n1. Quelle variable utiliser en Y ?",
            current_attempt_had_code=False,
            current_attempt_had_error=False,
        )

    def test_action_contract_retry_gate_ignores_status_questions(self):
        assert not _should_retry_copepod_action_contract_without_code_or_questions(
            user_message="quels fichiers as-tu ?",
            assistant_text="Un fichier est chargé.",
            current_attempt_had_code=False,
            current_attempt_had_error=False,
        )

    def test_action_contract_retry_note_requires_plan_code_or_numbered_questions(self):
        note = _build_copepod_action_contract_retry_note("fais un graphe")
        assert "**Plan**" in note
        assert "Python code block" in note
        assert "numbered questions" in note
        assert "fais un graphe" in note

    def test_graph_output_retry_gate_catches_matplotlib_without_show(self):
        assert _should_retry_copepod_graph_output_without_display_or_deliverable(
            user_message="fais un graphe de l'abondance",
            assistant_text="",
            code_texts=[
                "import matplotlib.pyplot as plt\n"
                "plt.plot([1, 2])\n"
                "plt.savefig('/tmp/g.png')\n"
                "print('DELIVERABLE: ' + json.dumps({'type': 'graph', 'title': 'G', 'file': '/tmp/g.png'}))"
            ],
            current_attempt_had_code=True,
            current_attempt_had_error=False,
            current_attempt_had_image=False,
            current_attempt_had_graph_deliverable=True,
        )

    def test_graph_output_retry_gate_catches_graph_without_deliverable(self):
        assert _should_retry_copepod_graph_output_without_display_or_deliverable(
            user_message="fais un graphe de l'abondance",
            assistant_text="",
            code_texts=[
                "import matplotlib.pyplot as plt\n"
                "plt.plot([1, 2])\n"
                "plt.savefig('/tmp/g.png')\n"
                "plt.show()\n"
            ],
            current_attempt_had_code=True,
            current_attempt_had_error=False,
            current_attempt_had_image=True,
            current_attempt_had_graph_deliverable=False,
        )

    def test_graph_output_retry_gate_allows_matplotlib_show_and_graph_card(self):
        assert not _should_retry_copepod_graph_output_without_display_or_deliverable(
            user_message="fais un graphe de l'abondance",
            assistant_text="",
            code_texts=[
                "import matplotlib.pyplot as plt\n"
                "plt.plot([1, 2])\n"
                "plt.savefig('/tmp/g.png')\n"
                "plt.show()\n"
                "print('DELIVERABLE: ' + json.dumps({'type': 'graph', 'title': 'G', 'file': '/tmp/g.png'}))"
            ],
            current_attempt_had_code=True,
            current_attempt_had_error=False,
            current_attempt_had_image=False,
            current_attempt_had_graph_deliverable=True,
        )

    def test_graph_output_retry_note_requires_display_and_graph_deliverable(self):
        note = _build_copepod_graph_output_retry_note("fais un graphe")
        assert "plt.show()" in note
        assert "DELIVERABLE:" in note
        assert "`graph`" in note

    def test_system_note_is_merged_into_leading_system_prompt(self):
        messages = [
            {"role": "system", "type": "message", "content": "base prompt"},
            {"role": "user", "type": "message", "content": "hello"},
            {"role": "system", "type": "message", "content": "late note"},
            {"role": "assistant", "type": "message", "content": "reply"},
        ]
        merged = _inject_copepod_system_note(messages, "inspect-then-code note")
        system_positions = [i for i, msg in enumerate(merged) if msg.get("role") == "system"]
        assert system_positions == [0]
        assert "base prompt" in merged[0]["content"]
        assert "late note" in merged[0]["content"]
        assert "inspect-then-code note" in merged[0]["content"]

    def test_restored_messages_drop_system_entries_before_llm_call(self):
        messages = [
            {"role": "system", "type": "message", "content": "base prompt"},
            {"role": "user", "type": "message", "content": "hello"},
            {"role": "assistant", "type": "message", "content": "reply"},
        ]
        stripped = _strip_system_messages(messages)
        assert [msg["role"] for msg in stripped] == ["user", "assistant"]
        assert all(msg["role"] != "system" for msg in stripped)


# ---------------------------------------------------------------------------
# Helper: _build_copepod_session_resources_note
# ---------------------------------------------------------------------------

class TestCopepodSessionResourcesNote:
    def test_returns_none_without_resource_signals(self):
        note = _build_copepod_session_resources_note([
            {"role": "user", "type": "message", "content": "fais un graphe"},
            {"role": "assistant", "type": "message", "content": "Uploadez un fichier pour commencer."},
        ])
        assert note is None

    def test_compacts_upload_report_deliverable_image_and_file_artifacts(self):
        note = _build_copepod_session_resources_note(
            [
                {
                    "role": "user",
                    "type": "message",
                    "content": (
                        "Analyse.\n\n"
                        "Files uploaded in this message:\n"
                        "- sample.csv (text/csv) | relative path: sample.csv\n"
                        "Use these paths when referencing the uploaded files."
                    ),
                },
                {
                    "role": "assistant",
                    "type": "message",
                    "content": (
                        "# RAPPORT D'INSPECTION\n\n"
                        "- **file_path** : `/app/static/u1/s1/uploads/sample.csv`\n"
                        "- **format** : `csv`  •  **n_rows** : `120`  •  **n_columns** : `12`\n"
                        "- **source_type_guess** : `likely_neolabs_taxon` (confidence: `high`)\n"
                        "## Columns (12)\n\n"
                        "| # | Column | Dtype |\n"
                        "|---|--------|-------|\n"
                        "| 1 | `sample_id` | object |\n"
                        "| 2 | `station` | object |\n"
                        "| 3 | `depth` | float64 |\n"
                        "Clés de jointure potentielles : sample_id | station\n"
                    ),
                },
                {
                    "role": "computer",
                    "type": "deliverable",
                    "content": '{"type":"graph","title":"Abondance par profondeur","file":"/app/static/u1/s1/abundance_depth.png"}',
                },
                {
                    "role": "computer",
                    "type": "image",
                    "format": "path",
                    "content": "/app/static/u1/s1/abundance_depth.png",
                },
                {
                    "role": "computer",
                    "type": "file",
                    "format": "csv-download",
                    "content": "/static/u1/s1/joined.csv",
                },
            ],
            user_id="u1",
            session_id="s1",
        )

        assert note is not None
        assert "## Copepod Working Set" in note
        assert "This is the canonical session state" in note
        assert "current_user_goal:" in note
        assert "seen_files:" in note
        assert "Pending files requiring immediate `inspect_and_report`:" in note
        assert "active_files" not in note
        # latest_inspection_by_file: section is intentionally NOT rendered into
        # the prompt — the LLM was paraphrasing the compact summary into
        # user-visible prose. State is still persisted internally.
        assert "latest_inspection_by_file:" not in note
        assert "likely_neolabs_taxon" not in note  # source value no longer leaks via prompt
        assert "Do not ask the user to re-upload" in note
        assert "sample.csv" in note
        assert "path: /app/static/u1/s1/uploads/sample.csv" in note
        assert "Deliverables:" in note
        assert "Abondance par profondeur" in note
        assert "Graph/image artifacts:" in note
        assert "File artifacts:" in note
        assert "preserve the source artifact" in note
        assert "Inspection reports:" not in note
        assert "RAPPORT D'INSPECTION" not in note

    def test_renders_inspected_columns_as_exact_facts(self, client):
        tc, store = client
        session_key = "u1:s1:copepod"
        store.write_working_set(
            session_key,
            {
                "seen_files": ["sample.csv"],
                "active_files": ["sample.csv"],
                "latest_inspection_by_file": {"sample.csv": "sample.csv | likely_neolabs_taxon | 120 × 12"},
                "current_user_goal": "inspect sample.csv",
            },
        )
        store.store_inspection_data(
            session_key,
            "sample.csv",
            {
                "columns": [
                    {"name": "sample_id"},
                    {"name": "station"},
                    {"name": "depth"},
                ]
            },
        )

        note = _build_copepod_session_resources_note(
            [
                {
                    "role": "user",
                    "type": "message",
                    "content": (
                        "Files uploaded in this message:\n"
                        "Session ID: s1\n"
                        "Base path: ./static/{user_id}/s1/uploads\n"
                        "- sample.csv (text/csv) | relative path: sample.csv\n"
                        "Use these paths when referencing the uploaded files."
                    ),
                }
            ],
            session_key=session_key,
            user_id="u1",
            session_id="s1",
        )

        assert note is not None
        assert "Inspected file columns (exact facts available for readback and graph_readiness):" in note
        assert "sample.csv : sample_id, station, depth" in note
        assert "do not narrate to user" not in note

    def test_separates_new_uploads_from_already_present_files(self):
        note = _build_copepod_session_resources_note(
            [
                {
                    "role": "user",
                    "type": "message",
                    "content": (
                        "Files uploaded in this message:\n"
                        "Session ID: s1\n"
                        "Base path: ./static/{user_id}/s1/uploads\n"
                        "- sample.csv (text/csv) | relative path: sample.csv\n"
                        "Use these paths when referencing the uploaded files."
                    ),
                },
                {
                    "role": "assistant",
                    "type": "message",
                    "content": (
                        "# RAPPORT D'INSPECTION\n\n"
                        "- **file_path** : `/app/static/u1/s1/uploads/sample.csv`\n"
                        "- **format** : `csv`  •  **n_rows** : `12`  •  **n_columns** : `3`\n"
                        "- **source_type_guess** : `likely_neolabs_taxon` (confidence: `high`)\n"
                    ),
                },
                {
                    "role": "user",
                    "type": "message",
                    "content": (
                        "Files uploaded in this message:\n"
                        "Session ID: s1\n"
                        "Base path: ./static/{user_id}/s1/uploads\n"
                        "- SAMPLE.csv (text/csv) | relative path: SAMPLE.csv\n"
                        "- fresh.csv (text/csv) | relative path: fresh.csv\n"
                        "Use these paths when referencing the uploaded files."
                    ),
                },
            ],
            user_id="u1",
            session_id="s1",
        )

        assert note is not None
        assert "Files uploaded in this message (inspect these new filenames only):" in note
        assert "Files with existing reports in this session (skip inspection silently):" in note

        new_section = note.split(
            "Files uploaded in this message (inspect these new filenames only):",
            1,
        )[1].split("Files with existing reports in this session (skip inspection silently):", 1)[0]
        skip_section = note.split("Files with existing reports in this session (skip inspection silently):", 1)[1]

        assert "fresh.csv" in new_section
        assert "SAMPLE.csv" not in new_section
        assert "SAMPLE.csv" in skip_section
        assert "already inspected" not in note.lower()

    def test_returns_no_new_files_on_followup_without_new_uploads(self, client):
        tc, store = client
        session_key = "u1:s1:copepod"
        store.write_working_set(
            session_key,
            {
                "seen_files": ["sample.csv"],
                "active_files": ["sample.csv"],
                "latest_inspection_by_file": {},
                "current_user_goal": "inspect sample.csv",
            },
        )

        note, pending = _build_copepod_session_resources_note(
            [
                {
                    "role": "user",
                    "type": "message",
                    "content": "Please inspect the file already uploaded.",
                }
            ],
            session_key=session_key,
            user_id="u1",
            session_id="s1",
            return_new_files=True,
        )

        assert note is not None
        assert "Pending files requiring immediate `inspect_and_report`:" in note
        assert "active_files" not in note
        assert pending == []

    def test_includes_existing_graph_image_as_source_for_correction(self):
        note = _build_copepod_session_resources_note(
            [
                {
                    "role": "computer",
                    "type": "image",
                    "format": "path",
                    "content": "/app/static/u1/s1/graph-source.png",
                },
                {
                    "role": "computer",
                    "type": "deliverable",
                    "content": '{"type":"graph","title":"Graph source","file":"/app/static/u1/s1/graph-source.png"}',
                },
            ],
            user_id="u1",
            session_id="s1",
        )

        assert note is not None
        assert "Graph/image artifacts:" in note
        assert "/app/static/u1/s1/graph-source.png" in note
        assert "preserve the source artifact" in note

    def test_limits_artifacts_without_mentioning_conversation_history(self):
        messages = []
        for i in range(20):
            messages.append({
                "role": "computer",
                "type": "deliverable",
                "content": f'{{"type":"graph","title":"Graph {i}","file":"/app/static/g{i}.png"}}',
            })

        note = _build_copepod_session_resources_note(messages)

        assert note is not None
        assert "Graph 19" in note
        assert "Graph 0" not in note
        assert "conversation history" not in note

    def test_stream_deliverable_event_is_persistable_resource(self):
        event = {
            "role": "computer",
            "type": "deliverable",
            "content": '{"type":"graph","title":"Boite moustache","file":"/app/static/u1/s1/boxplot.png"}',
        }

        resource = _session_resource_message_from_stream_event(event)

        assert resource == event

    def test_base64_image_event_is_not_persisted_as_resource(self):
        event = {
            "role": "computer",
            "type": "image",
            "format": "base64.png",
            "content": "large-base64",
        }

        assert _session_resource_message_from_stream_event(event) is None

    def test_column_injection_appears_when_session_key_and_inspection_data_present(self, client):
        """Column names from inspection data are injected into the note for graph_readiness."""
        tc, store = client
        session_key = "u1:s1:copepod"
        store.store_inspection_data(session_key, "sample.csv", {
            "columns": [
                {"name": "sample_id"},
                {"name": "object_depth"},
                {"name": "fre_area"},
            ]
        })

        note = _build_copepod_session_resources_note(
            [
                {
                    "role": "user",
                    "type": "message",
                    "content": (
                        "Files uploaded in this message:\n"
                        "- sample.csv (text/csv) | relative path: sample.csv\n"
                        "Use these paths when referencing the uploaded files."
                    ),
                },
                {
                    "role": "assistant",
                    "type": "message",
                    "content": (
                        "# RAPPORT D'INSPECTION\n\n"
                        "- **file_path** : `/app/static/u1/s1/uploads/sample.csv`\n"
                        "- **format** : `csv`  •  **n_rows** : `100`  •  **n_columns** : `3`\n"
                        "- **source_type_guess** : `likely_neolabs_taxon` (confidence: `high`)\n"
                    ),
                },
            ],
            session_key=session_key,
            user_id="u1",
            session_id="s1",
        )

        with patch("routers.chat_routes.session_store", store):
            note = _build_copepod_session_resources_note(
                [
                    {
                        "role": "user",
                        "type": "message",
                        "content": (
                            "Files uploaded in this message:\n"
                            "- sample.csv (text/csv) | relative path: sample.csv\n"
                            "Use these paths when referencing the uploaded files."
                        ),
                    },
                    {
                        "role": "assistant",
                        "type": "message",
                        "content": (
                            "# RAPPORT D'INSPECTION\n\n"
                            "- **file_path** : `/app/static/u1/s1/uploads/sample.csv`\n"
                            "- **format** : `csv`  •  **n_rows** : `100`  •  **n_columns** : `3`\n"
                            "- **source_type_guess** : `likely_neolabs_taxon` (confidence: `high`)\n"
                        ),
                    },
                ],
                session_key=session_key,
                user_id="u1",
                session_id="s1",
            )

        assert note is not None
        assert "Inspected file columns" in note
        assert "sample.csv" in note
        assert "sample_id" in note
        assert "object_depth" in note
        assert "fre_area" in note

    def test_column_injection_remains_compact_and_readback_ready(self, client):
        """Compact inspection facts may include source type, but not raw internals."""
        tc, store = client
        session_key = "u1:s1:copepod"
        store.write_working_set(
            session_key,
            {
                "seen_files": ["sample.csv"],
                "active_files": ["sample.csv"],
                "latest_inspection_by_file": {"sample.csv": "sample.csv | likely_neolabs_taxon | 120 × 12"},
                "current_user_goal": "inspect sample.csv",
            },
        )
        store.store_inspection_data(session_key, "sample.csv", {
            "columns": [{"name": "col_a"}, {"name": "col_b"}],
            "source_type_guess": {"value": "likely_neolabs_taxon", "confidence": "high", "evidence": []},
            "n_rows": 500,
        })

        with patch("routers.chat_routes.session_store", store):
            note = _build_copepod_session_resources_note(
                [
                    {
                        "role": "user",
                        "type": "message",
                        "content": (
                            "Files uploaded in this message:\n"
                            "- sample.csv (text/csv) | relative path: sample.csv\n"
                            "Use these paths when referencing the uploaded files."
                        ),
                    },
                    {
                        "role": "assistant",
                        "type": "message",
                        "content": (
                            "# RAPPORT D'INSPECTION\n\n"
                            "- **file_path** : `/app/static/u1/s1/uploads/sample.csv`\n"
                            "- **source_type_guess** : `likely_neolabs_taxon` (confidence: `high`)\n"
                        ),
                    },
                ],
                session_key=session_key,
                user_id="u1",
                session_id="s1",
            )

        assert note is not None
        assert "col_a" in note
        assert "col_b" in note
        assert "Inspected file summary (readback-ready):" in note
        assert "source=`likely_neolabs_taxon`" in note
        assert "500" not in note
        assert "latest_inspection_by_file:" not in note

    def test_compact_inspection_summary_is_readback_ready(self, client):
        tc, store = client
        session_key = "u1:s1:copepod"
        store.write_working_set(
            session_key,
            {
                "seen_files": ["sample.csv"],
                "active_files": ["sample.csv"],
                "latest_inspection_by_file": {"sample.csv": "sample.csv | likely_neolabs_taxon | 120 × 12"},
                "current_user_goal": "inspect sample.csv",
            },
        )
        store.store_inspection_data(
            session_key,
            "sample.csv",
            {
                "file_path": "/app/static/u1/s1/uploads/sample.csv",
                "format": "csv",
                "n_rows": 120,
                "n_columns": 12,
                "columns": [
                    {"name": "sample_id", "semantic_guess": "sample_id", "confidence": "high", "missing_count": 0, "missing_rate": 0.0},
                    {"name": "station", "semantic_guess": "station", "confidence": "medium", "missing_count": 0, "missing_rate": 0.0},
                    {"name": "depth", "semantic_guess": "", "confidence": "low", "missing_count": 2, "missing_rate": 0.167},
                ],
                "warnings": ["Encoding inferred"],
                "source_type_guess": {"value": "likely_neolabs_taxon", "confidence": "high", "evidence": []},
            },
        )

        note = _build_copepod_session_resources_note(
            [
                {
                    "role": "user",
                    "type": "message",
                    "content": (
                        "Files uploaded in this message:\n"
                        "- sample.csv (text/csv) | relative path: sample.csv\n"
                        "Use these paths when referencing the uploaded files."
                    ),
                },
                {
                    "role": "assistant",
                    "type": "message",
                    "content": (
                        "# RAPPORT D'INSPECTION\n\n"
                        "- **file_path** : `/app/static/u1/s1/uploads/sample.csv`\n"
                        "- **format** : `csv`  •  **n_rows** : `120`  •  **n_columns** : `12`\n"
                        "- **source_type_guess** : `likely_neolabs_taxon` (confidence: `high`)\n"
                    ),
                },
            ],
            session_key=session_key,
            user_id="u1",
            session_id="s1",
        )

        assert note is not None
        assert "Inspected file summary (readback-ready):" in note
        assert "shape=`120 × 12`" in note
        assert "warnings=`1`" in note
        assert "grounding=`2 auto / 1 clarify`" in note
        assert "missing=`depth 16.7%`" in note
        assert "sample_id" in note
        assert "station" in note
        assert "depth" in note
        assert "latest_inspection_by_file:" not in note

    def test_column_injection_absent_without_session_key(self):
        """Without session_key the store is not queried — no columns injected."""
        note = _build_copepod_session_resources_note(
            [
                {
                    "role": "user",
                    "type": "message",
                    "content": (
                        "Files uploaded in this message:\n"
                        "- sample.csv (text/csv) | relative path: sample.csv\n"
                        "Use these paths when referencing the uploaded files."
                    ),
                },
                {
                    "role": "assistant",
                    "type": "message",
                    "content": (
                        "# RAPPORT D'INSPECTION\n\n"
                        "- **file_path** : `/app/static/u1/s1/uploads/sample.csv`\n"
                        "- **source_type_guess** : `likely_neolabs_taxon`\n"
                    ),
                },
            ],
            user_id="u1",
            session_id="s1",
            # no session_key
        )

        assert note is not None
        assert "Inspected file columns" not in note


# ---------------------------------------------------------------------------
# Helper: _scrub_inspection_report_in_content / _scrub_inspection_reports_for_llm
# ---------------------------------------------------------------------------

class TestScrubInspectionReportInContent:
    def test_passthrough_when_no_report_marker(self):
        content = "Just some prose without any report."
        scrubbed, extracted = _scrub_inspection_report_in_content(content)
        assert scrubbed == content
        assert extracted == []

    def test_replaces_single_report_with_stub_and_extracts_filename(self):
        content = (
            "# RAPPORT D'INSPECTION\n\n"
            "- **file_path** : `/app/static/u1/s1/uploads/donne_sample.csv`\n"
            "- **n_rows** : `6105` • **n_columns** : `33`\n"
            "- **source_type_guess** : `likely_neolabs_taxon` (confidence: `high`)\n"
            "## Synthèse ...\n"
        )
        scrubbed, extracted = _scrub_inspection_report_in_content(content)

        assert "# RAPPORT D'INSPECTION" not in scrubbed
        assert "6105" not in scrubbed
        assert "likely_neolabs_taxon" not in scrubbed
        assert "[Inspection report for donne_sample.csv" in scrubbed
        assert "get_inspection_report('donne_sample.csv')" in scrubbed

        assert len(extracted) == 1
        filename, full_block = extracted[0]
        assert filename == "donne_sample.csv"
        assert "likely_neolabs_taxon" in full_block

    def test_handles_multiple_reports_in_one_content(self):
        content = (
            "# RAPPORT D'INSPECTION\n\n"
            "- **file_path** : `/uploads/a.csv`\n"
            "- **n_rows** : `10`\n\n"
            "# RAPPORT D'INSPECTION\n\n"
            "- **file_path** : `/uploads/b.csv`\n"
            "- **n_rows** : `20`\n"
        )
        scrubbed, extracted = _scrub_inspection_report_in_content(content)
        assert scrubbed.count("[Inspection report for") == 2
        assert "[Inspection report for a.csv" in scrubbed
        assert "[Inspection report for b.csv" in scrubbed
        assert [name for name, _ in extracted] == ["a.csv", "b.csv"]


class TestScrubInspectionReportsForLLM:
    def test_scrubs_assistant_message_and_persists_to_store(self):
        from core.session_store import InMemorySessionStore
        from routers import chat_routes as cr

        store = InMemorySessionStore()
        with patch.object(cr, "session_store", store):
            messages = [
                {"role": "user", "content": "analyse"},
                {
                    "role": "assistant",
                    "content": (
                        "# RAPPORT D'INSPECTION\n\n"
                        "- **file_path** : `/uploads/sample.csv`\n"
                        "- **n_rows** : `100` • **n_columns** : `5`\n"
                        "- **source_type_guess** : `likely_ecotaxa` (confidence: `high`)\n"
                    ),
                },
            ]

            scrubbed = _scrub_inspection_reports_for_llm(messages, session_key="u1:s1:copepod")

        assert scrubbed[0] == {"role": "user", "content": "analyse"}
        assert "# RAPPORT D'INSPECTION" not in scrubbed[1]["content"]
        assert "likely_ecotaxa" not in scrubbed[1]["content"]
        assert "[Inspection report for sample.csv" in scrubbed[1]["content"]

        # Side effect: full report persisted in the store
        stored = store.read_inspection_report("u1:s1:copepod", "sample.csv")
        assert stored is not None
        assert "likely_ecotaxa" in stored
        assert "n_rows" in stored

    def test_no_persistence_when_session_key_is_none(self):
        from core.session_store import InMemorySessionStore
        from routers import chat_routes as cr

        store = InMemorySessionStore()
        with patch.object(cr, "session_store", store):
            messages = [{
                "role": "assistant",
                "content": (
                    "# RAPPORT D'INSPECTION\n"
                    "- **file_path** : `/uploads/x.csv`\n"
                ),
            }]
            scrubbed = _scrub_inspection_reports_for_llm(messages, session_key=None)

        assert "[Inspection report for x.csv" in scrubbed[0]["content"]
        assert store.list_inspection_reports("u1:s1:copepod") == []

    def test_messages_without_reports_pass_through_unchanged(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "plain reply"},
            {"role": "computer", "type": "image", "format": "path", "content": "/img.png"},
        ]
        scrubbed = _scrub_inspection_reports_for_llm(messages)
        assert scrubbed == messages

    def test_non_dict_entries_are_preserved(self):
        sentinel = "not-a-dict"
        scrubbed = _scrub_inspection_reports_for_llm([sentinel])  # type: ignore[list-item]
        assert scrubbed == [sentinel]

    def test_truncated_console_output_is_still_scrubbed_via_fallback_filename(self):
        """When OpenInterpreter clips the header off a long report, we must
        still scrub the synthesis fragment that survives in the tail."""
        from core.session_store import InMemorySessionStore
        from routers import chat_routes as cr

        truncated = (
            "Output truncated. Showing the last 4096 characters. You should try "
            "again and use computer.ai.summarize(output) over the output.\n\n"
            "| 32 | `analysis_id` | object | ...\n\n"
            "## Synthèse\n\n"
            "```json\n"
            '{"file": "donne_sample.csv", "source_type": "likely_neolabs_taxon"}\n'
            "```\n"
        )

        store = InMemorySessionStore()
        with patch.object(cr, "session_store", store):
            messages = [
                {"role": "user", "content": (
                    "Files uploaded in this message:\n"
                    "- donne_sample.csv (text/csv) | relative path: donne_sample.csv\n"
                )},
                {"role": "assistant", "type": "code", "format": "python", "content": (
                    'inspect_and_report(file_paths=["/app/static/u1/s1/uploads/donne_sample.csv"])'
                )},
                {"role": "computer", "type": "console", "format": "output", "content": truncated},
            ]

            scrubbed = _scrub_inspection_reports_for_llm(messages, session_key="u1:s1:copepod")

        # The truncated console output must be replaced with a fragment stub.
        assert "## Synthèse" not in scrubbed[2]["content"]
        assert "likely_neolabs_taxon" not in scrubbed[2]["content"]
        assert "[Inspection report fragment for donne_sample.csv" in scrubbed[2]["content"]
        # Filename inferred from the upload block (and confirmed by the
        # inspect_and_report call argument).
        assert "get_inspection_report('donne_sample.csv')" in scrubbed[2]["content"]
        # Full truncated body is persisted out-of-context.
        stored = store.read_inspection_report("u1:s1:copepod", "donne_sample.csv")
        assert stored is not None and "likely_neolabs_taxon" in stored

    def test_truncated_report_without_known_filename_is_still_scrubbed_but_not_stored(self):
        from core.session_store import InMemorySessionStore
        from routers import chat_routes as cr

        truncated = (
            "Output truncated. Showing the last 4096 characters.\n"
            "## Synthèse\n```json\n{\"x\": 1}\n```\n"
        )

        store = InMemorySessionStore()
        with patch.object(cr, "session_store", store):
            scrubbed = _scrub_inspection_reports_for_llm(
                [{"role": "computer", "content": truncated}],
                session_key="u1:s1:copepod",
            )

        # Content is still scrubbed (LLM cannot see the synthesis)
        assert "## Synthèse" not in scrubbed[0]["content"]
        assert "[Inspection report fragment for unknown" in scrubbed[0]["content"]
        # But nothing is stored because we have no usable key.
        assert store.list_inspection_reports("u1:s1:copepod") == []


class TestCopepodWorkingSetReducer:
    def test_tracks_seen_files_and_current_goal(self, client):
        tc, store = client
        session_key = "u1:s1:copepod"
        store.write_working_set(
            session_key,
            {
                "seen_files": ["donne_sample.csv"],
                "active_files": ["donne_sample.csv"],
                "latest_inspection_by_file": {
                    "donne_sample.csv": "donne_sample.csv | path: /app/static/u1/s1/uploads/donne_sample.csv"
                },
                "current_user_goal": "inspect new file",
            },
        )

        messages = [
            {
                "role": "user",
                "type": "message",
                "content": (
                    "Please inspect the new upload.\n\n"
                    "Files uploaded in this message:\n"
                    "- donne_sample.csv (text/csv) | relative path: donne_sample.csv\n"
                    "- sample_ca-cioos_ccin-12713_Jeu_de_donn_es_ERDDAP.csv (text/csv) | relative path: sample_ca-cioos_ccin-12713_Jeu_de_donn_es_ERDDAP.csv\n"
                ),
            }
        ]

        updated = _update_copepod_working_set(
            session_key=session_key,
            messages=messages,
            user_id="u1",
            session_id="s1",
        )

        assert updated["current_user_goal"] == "Please inspect the new upload."
        assert updated["seen_files"] == [
            "donne_sample.csv",
            "sample_ca-cioos_ccin-12713_Jeu_de_donn_es_ERDDAP.csv",
        ]
        assert updated["active_files"] == [
            "sample_ca-cioos_ccin-12713_Jeu_de_donn_es_ERDDAP.csv",
        ]
        assert set(updated) == {
            "seen_files",
            "active_files",
            "latest_inspection_by_file",
            "current_user_goal",
        }
        assert store.read_working_set(session_key) == updated

    def test_preserves_pending_active_files_until_inspection_report_exists(self, client):
        tc, store = client
        session_key = "u1:s1:copepod"
        store.write_working_set(
            session_key,
            {
                "seen_files": ["sample.csv"],
                "active_files": ["sample.csv"],
                "latest_inspection_by_file": {},
                "current_user_goal": "inspect sample.csv",
            },
        )

        updated = _update_copepod_working_set(
            session_key=session_key,
            messages=[
                {
                    "role": "user",
                    "type": "message",
                    "content": "Please inspect it.",
                }
            ],
            user_id="u1",
            session_id="s1",
        )

        assert updated["active_files"] == ["sample.csv"]
        assert updated["seen_files"] == ["sample.csv"]

    def test_clears_pending_active_file_once_report_is_present(self, client):
        tc, store = client
        session_key = "u1:s1:copepod"
        store.write_working_set(
            session_key,
            {
                "seen_files": ["sample.csv"],
                "active_files": ["sample.csv"],
                "latest_inspection_by_file": {},
                "current_user_goal": "inspect sample.csv",
            },
        )

        updated = _update_copepod_working_set(
            session_key=session_key,
            messages=[
                {
                    "role": "assistant",
                    "type": "message",
                    "content": (
                        "# RAPPORT D'INSPECTION\n\n"
                        "- **file_path** : `/app/static/u1/s1/uploads/sample.csv`\n"
                        "- **format** : `csv`  •  **n_rows** : `12`  •  **n_columns** : `3`\n"
                        "- **source_type_guess** : `likely_neolabs_taxon` (confidence: `high`)\n"
                    ),
                }
            ],
            user_id="u1",
            session_id="s1",
        )

        assert updated["active_files"] == []
        assert "sample.csv" in updated["latest_inspection_by_file"]

    def test_stores_rich_readback_summary_from_inspection_report(self, client):
        tc, store = client
        session_key = "u1:s1:copepod"
        store.write_working_set(
            session_key,
            {
                "seen_files": ["sample.csv"],
                "active_files": ["sample.csv"],
                "latest_inspection_by_file": {},
                "current_user_goal": "inspect sample.csv",
            },
        )

        updated = _update_copepod_working_set(
            session_key=session_key,
            messages=[
                {
                    "role": "assistant",
                    "type": "message",
                    "content": (
                        "# RAPPORT D'INSPECTION\n"
                        "<!-- report-title: 📄 CTD Amundsen — sample (120 × 12) -->\n\n"
                        "- **file_path** : `/app/static/u1/s1/uploads/sample.csv`\n"
                        "- **format** : `csv`  •  **n_rows** : `120`  •  **n_columns** : `12`\n"
                        "- **source_type_guess** : `likely_neolabs_taxon` (confidence: `high`)\n"
                        "## Columns (12)\n\n"
                        "| # | Column | Dtype |\n"
                        "|---|--------|-------|\n"
                        "| 1 | `sample_id` | object |\n"
                        "| 2 | `station` | object |\n"
                        "| 3 | `depth` | float64 |\n"
                        "Clés de jointure potentielles : sample_id | station\n\n"
                        "## Synthèse\n\n"
                        "```json\n"
                        "{\n"
                        '  "column_grounding": {"rag_defined": 2, "auto_resolved": 1, "needs_clarification": 0, "unresolved": []},\n'
                        '  "warnings": 1\n'
                        "}\n"
                        "```\n"
                    ),
                }
            ],
            user_id="u1",
            session_id="s1",
        )

        summary = updated["latest_inspection_by_file"].get("sample.csv", "")
        assert "sample.csv" in summary
        assert "likely_neolabs_taxon" in summary
        assert "120 × 12" in summary
        assert "columns: sample_id, station, depth" in summary
        assert "grounding: 2 RAG / 1 auto / 0 clarify" in summary
        assert "warnings: 1" in summary

    def test_rich_readback_summary_looks_up_stored_inspection_by_stem(self, client):
        tc, store = client
        session_key = "u1:s1:copepod"
        store.write_working_set(
            session_key,
            {
                "seen_files": ["sample.csv"],
                "active_files": ["sample.csv"],
                "latest_inspection_by_file": {"sample.csv": "sample.csv | likely_neolabs_taxon | 120 × 12"},
                "current_user_goal": "inspect sample.csv",
            },
        )
        store.store_inspection_data(
            session_key,
            "sample",
            {
                "file_path": "/app/static/u1/s1/uploads/sample.csv",
                "format": "csv",
                "n_rows": 120,
                "n_columns": 12,
                "columns": [
                    {"name": "sample_id", "semantic_guess": "sample_id", "confidence": "high", "missing_count": 0, "missing_rate": 0.0},
                    {"name": "station", "semantic_guess": "station", "confidence": "medium", "missing_count": 0, "missing_rate": 0.0},
                    {"name": "depth", "semantic_guess": "", "confidence": "low", "missing_count": 2, "missing_rate": 0.167},
                ],
                "warnings": ["Encoding inferred"],
                "source_type_guess": {"value": "likely_neolabs_taxon", "confidence": "high", "evidence": []},
            },
        )

        note = _build_copepod_session_resources_note(
            [
                {
                    "role": "user",
                    "type": "message",
                    "content": (
                        "Files uploaded in this message:\n"
                        "- sample.csv (text/csv) | relative path: sample.csv\n"
                        "Use these paths when referencing the uploaded files."
                    ),
                },
                {
                    "role": "assistant",
                    "type": "message",
                    "content": (
                        "# RAPPORT D'INSPECTION\n"
                        "<!-- report-title: 📄 CTD Amundsen — sample (120 × 12) -->\n\n"
                        "- **file_path** : `/app/static/u1/s1/uploads/sample.csv`\n"
                        "- **format** : `csv`  •  **n_rows** : `120`  •  **n_columns** : `12`\n"
                        "- **source_type_guess** : `likely_neolabs_taxon` (confidence: `high`)\n"
                        "## Columns (12)\n\n"
                        "| # | Column | Dtype |\n"
                        "|---|--------|-------|\n"
                        "| 1 | `sample_id` | object |\n"
                        "| 2 | `station` | object |\n"
                        "| 3 | `depth` | float64 |\n"
                        "## Synthèse\n\n"
                        "```json\n"
                        "{\n"
                        '  "column_grounding": {"rag_defined": 2, "auto_resolved": 1, "needs_clarification": 0, "unresolved": []},\n'
                        '  "warnings": 1\n'
                        "}\n"
                        "```\n"
                    ),
                },
            ],
            session_key=session_key,
            user_id="u1",
            session_id="s1",
        )

        assert note is not None
        assert "Inspected file summary (readback-ready):" in note
        assert "sample_id" in note
        assert "grounding=`2 auto / 1 clarify`" in note
        assert "warnings=`1`" in note

    def test_clears_pending_active_file_when_history_has_inspection_stub(self, client):
        tc, store = client
        session_key = "u1:s1:copepod"
        store.write_working_set(
            session_key,
            {
                "seen_files": ["sample.csv"],
                "active_files": ["sample.csv"],
                "latest_inspection_by_file": {},
                "current_user_goal": "quelles sont les colonnes clés ?",
            },
        )

        updated = _update_copepod_working_set(
            session_key=session_key,
            messages=[
                {
                    "role": "assistant",
                    "type": "message",
                    "content": (
                        "[Inspection report for sample.csv — stored out-of-context. "
                        "Call `get_inspection_report('sample.csv')` to view shape, columns, "
                        "RAG definitions if needed.]"
                    ),
                }
            ],
            user_id="u1",
            session_id="s1",
        )

        assert updated["active_files"] == []
        assert updated["seen_files"] == ["sample.csv"]


class TestCopepodSystemMessageComposition:
    def test_runtime_notes_are_prepended_before_base_prompt(self):
        from routers.chat_routes import _compose_copepod_system_message

        composed = _compose_copepod_system_message(
            "BASE PROMPT",
            "SESSION NOTE 1",
            None,
            "SESSION NOTE 2",
        )

        assert composed.startswith("SESSION NOTE 1\n\nSESSION NOTE 2\n\nBASE PROMPT")


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
        assert stored[0]["role"] == "user"
        assert stored[0]["type"] == "message"
        assert stored[0]["content"] == "question"

    def test_empty_messages_list_returns_zero_count(self, client):
        tc, _ = client
        resp = tc.post(
            "/load-conversation",
            json={"messages": []},
            headers={"x-session-id": "s-empty"},
        )
        assert resp.status_code == 200
        assert resp.json()["message_count"] == 0


class TestMultimodalAttachmentHydration:
    def test_image_attachment_block_becomes_multimodal_content(self, tmp_path):
        static_dir = tmp_path / "static"
        image_path = static_dir / "u1" / "s1" / "uploads" / "figure.png"
        image_path.parent.mkdir(parents=True)
        image_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO6X3XcAAAAASUVORK5CYII="
        )
        image_path.write_bytes(image_bytes)

        message = {
            "role": "user",
            "content": (
                "Analyse ceci.\n\n"
                "Files uploaded in this message:\n"
                "Session ID: s1\n"
                "Base path: ./static/{user_id}/s1/uploads\n"
                "- figure.png (image/png) | relative path: figure.png\n"
                "Use these paths when referencing the uploaded files."
            ),
        }

        hydrated = _coerce_multimodal_message_content(
            message,
            user_id="u1",
            session_id="s1",
            static_dir=static_dir,
        )

        assert isinstance(hydrated["content"], list)
        assert hydrated["content"][0] == {"type": "text", "text": "Analyse ceci."}
        assert hydrated["content"][1]["type"] == "image_url"
        assert hydrated["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_legacy_multimodal_content_is_expanded_into_native_messages(self, tmp_path):
        static_dir = tmp_path / "static"
        image_path = static_dir / "u1" / "s1" / "uploads" / "figure.png"
        image_path.parent.mkdir(parents=True)
        image_path.write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO6X3XcAAAAASUVORK5CYII="
            )
        )

        message = {
            "role": "user",
            "content": [
                {"type": "text", "text": "Analyse ceci."},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        }

        expanded = _expand_multimodal_message_for_interpreter(
            message,
            user_id="u1",
            session_id="s1",
            static_dir=static_dir,
        )

        assert len(expanded) == 2
        assert expanded[0] == {"role": "user", "type": "message", "content": "Analyse ceci."}
        assert expanded[1]["type"] == "image"
        assert expanded[1]["format"].startswith("base64.")
        assert not any(isinstance(msg.get("content"), list) for msg in expanded)


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

    def test_chat_hydrates_image_attachments_before_llm_call(self, tmp_path):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)
        fake_interpreter.system_message = "base prompt"

        static_dir = tmp_path / "static"
        image_path = static_dir / "u1" / "s1" / "uploads" / "figure.png"
        image_path.parent.mkdir(parents=True)
        image_path.write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO6X3XcAAAAASUVORK5CYII="
            )
        )

        captured = {}

        def fake_chat(message, stream=True):
            captured["message"] = message
            captured["system_message"] = fake_interpreter.system_message
            fake_interpreter.messages = list(message)
            return iter([
                {"start": True, "end": True, "role": "assistant", "type": "message", "content": "ok"}
            ])

        fake_interpreter.chat = fake_chat
        fake_tracer = MagicMock()
        fake_tracer.observe_stream.side_effect = lambda events: events
        fake_tracer.record_mcp_tool_run.return_value = None
        fake_tracer.record_event.return_value = None
        fake_tracer.record_route_error.return_value = None
        fake_tracer.close.return_value = None

        async def fake_gather(db):
            return [], {}

        message = {
            "role": "user",
            "content": (
                "Analyse cette image.\n\n"
                "Files uploaded in this message:\n"
                "Session ID: s1\n"
                "Base path: ./static/{user_id}/s1/uploads\n"
                "- figure.png (image/png) | relative path: figure.png\n"
                "Use these paths when referencing the uploaded files."
            ),
        }

        with (
            patch("routers.chat_routes.STATIC_DIR", static_dir),
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [message]},
                headers={"x-session-id": "s1"},
            )

        assert resp.status_code == 200
        assert isinstance(captured["message"], list)
        assert captured["message"][0] == {
            "role": "user",
            "type": "message",
            "content": "Analyse cette image.",
        }
        assert captured["message"][1]["type"] == "image"
        assert captured["message"][1]["format"] == "path"
        assert captured["message"][1]["content"].endswith("figure.png")
        assert not any(isinstance(msg.get("content"), list) for msg in captured["message"])

    def test_chat_preserves_non_image_upload_block_for_llm_call(self, tmp_path):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)
        fake_interpreter.system_message = "base prompt"

        static_dir = tmp_path / "static"
        csv_path = static_dir / "u1" / "s1" / "uploads" / "sample.csv"
        csv_path.parent.mkdir(parents=True)
        csv_path.write_text("a,b\n1,2\n")

        captured = {}

        def fake_chat(message, stream=True):
            captured["message"] = message
            captured["system_message"] = fake_interpreter.system_message
            fake_interpreter.messages = list(message)
            return iter([
                {"start": True, "end": True, "role": "assistant", "type": "message", "content": "ok"}
            ])

        fake_interpreter.chat = fake_chat
        fake_tracer = MagicMock()
        fake_tracer.observe_stream.side_effect = lambda events: events
        fake_tracer.record_mcp_tool_run.return_value = None
        fake_tracer.record_event.return_value = None
        fake_tracer.record_route_error.return_value = None
        fake_tracer.close.return_value = None

        async def fake_gather(db):
            return [], {}

        message = {
            "role": "user",
            "content": (
                "Analyse ce fichier.\n\n"
                "Files uploaded in this message:\n"
                "Session ID: s1\n"
                "Base path: ./static/{user_id}/s1/uploads\n"
                "- sample.csv (text/csv) | relative path: sample.csv\n"
                "Use these paths when referencing the uploaded files.\n"
                "Session rule: for every filename without an inspection report, call inspect_and_report immediately. If a filename already has a report, skip its inspection silently. If a filename is pending inspection, inspect it now in the same turn; do not wait for the user to repeat \"inspect\"."
            ),
        }

        with (
            patch("routers.chat_routes.STATIC_DIR", static_dir),
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [message]},
                headers={"x-session-id": "s1"},
            )

        assert resp.status_code == 200
        assert isinstance(captured["message"], list)
        assert isinstance(captured["message"][-1]["content"], str)
        assert captured["message"][-1]["content"] == "Analyse ce fichier."
        assert store.read_messages("u1:s1:generic")[-1]["content"].startswith("Analyse ce fichier.")

    def test_chat_writes_runtime_session_logs(self, tmp_path):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)
        fake_interpreter.system_message = "base prompt"

        def fake_chat(message, stream=True):
            fake_interpreter.messages = list(message)
            return iter([
                {"start": True, "end": True, "role": "assistant", "type": "message", "content": "ok"},
            ])

        fake_interpreter.chat = fake_chat

        async def fake_gather(db):
            return [], {}

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.RUNTIME_LOGS_ROOT", tmp_path),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "hello runtime logs"}]},
                headers={"x-session-id": "s1"},
            )

        assert resp.status_code == 200
        session_dir = tmp_path / "sessions" / "s1"
        assert (session_dir / "events.jsonl").exists()
        assert (session_dir / "turns.log").exists()
        assert (session_dir / "session_summary.json").exists()
        assert "hello runtime logs" in (session_dir / "turns.log").read_text(encoding="utf-8")

    def test_chat_injects_inspect_then_code_note_before_join_code(self):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)

        store.write_messages(
            "u1:s1:copepod",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "content": (
                        "# RAPPORT D'INSPECTION\n"
                        "### Fichiers chargés\n"
                        "- **a.csv**\n"
                        "Clés de jointure potentielles : station | time | depth\n"
                    ),
                }
            ],
        )
        fake_interpreter.system_message = "base prompt"

        captured = {}

        def fake_chat(message, stream=True):
            captured["message"] = message
            captured["system_message"] = fake_interpreter.system_message
            fake_interpreter.messages = list(message)
            return iter([
                {"start": True, "end": True, "role": "assistant", "type": "message", "content": "ok"}
            ])

        fake_interpreter.chat = fake_chat
        fake_tracer = MagicMock()
        fake_tracer.observe_stream.side_effect = lambda events: events
        fake_tracer.record_mcp_tool_run.return_value = None
        fake_tracer.record_event.return_value = None
        fake_tracer.record_route_error.return_value = None
        fake_tracer.close.return_value = None

        async def fake_gather(db):
            return [], {}

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "fais une jointure"}]},
                headers={"x-session-id": "s1", "x-agent-type": "copepod"},
            )

        assert resp.status_code == 200
        assert isinstance(captured["message"], list)
        assert all(msg.get("role") != "system" for msg in captured["message"])
        # Post-consolidation: the dynamic note contains ONLY concrete hints
        # (join keys, file context), not restated rules. The "inspect-then-code"
        # discipline lives in COPEPOD_SYSTEM_PROMPT.
        assert "Inspection context for this turn" in captured["system_message"]
        assert "station | time | depth" in captured["system_message"]

    def test_chat_injects_current_session_resources_before_copepod_call(self):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)

        store.write_messages(
            "u1:s1:copepod",
            [
                {
                    "role": "user",
                    "type": "message",
                    "content": (
                        "Analyse.\n\n"
                        "Files uploaded in this message:\n"
                        "- sample.csv (text/csv) | relative path: sample.csv\n"
                        "Use these paths when referencing the uploaded files."
                    ),
                },
                {
                    "role": "computer",
                    "type": "deliverable",
                    "content": '{"type":"graph","title":"Carte produite","file":"/app/static/u1/s1/map.png"}',
                },
            ],
        )
        fake_interpreter.system_message = "base prompt"

        captured = {}

        def fake_chat(message, stream=True):
            if "system_message" not in captured:
                captured["message"] = message
                captured["system_message"] = fake_interpreter.system_message
            fake_interpreter.messages = list(message)
            # Return a code block so the retry logic doesn't fire
            return iter([
                {"start": True, "end": True, "role": "assistant", "type": "code", "format": "python", "content": "print('ok')"},
                {"start": True, "end": True, "role": "computer", "type": "console", "format": "output", "content": "ok"},
                {"start": True, "end": True, "role": "assistant", "type": "message", "content": "ok"},
            ])

        fake_interpreter.chat = fake_chat
        fake_tracer = MagicMock()
        fake_tracer.observe_stream.side_effect = lambda events: events
        fake_tracer.record_mcp_tool_run.return_value = None
        fake_tracer.record_event.return_value = None
        fake_tracer.record_route_error.return_value = None
        fake_tracer.close.return_value = None

        async def fake_gather(db):
            return [], {}

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "fais un graphe"}]},
                headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )

        assert resp.status_code == 200
        assert all(msg.get("role") != "system" for msg in captured["message"])
        assert "## Copepod Working Set" in captured["system_message"]
        assert "current_user_goal:" in captured["system_message"]
        assert "Deliverables:" in captured["system_message"]
        assert "Carte produite" in captured["system_message"]
        assert "Do not ask the user to re-upload" in captured["system_message"]

    def test_chat_injects_resources_from_current_turn_payload(self):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)
        fake_interpreter.system_message = "base prompt"

        captured = {}

        def fake_chat(message, stream=True):
            captured["message"] = message
            captured["system_message"] = fake_interpreter.system_message
            fake_interpreter.messages = list(message)
            return iter([
                {"start": True, "end": True, "role": "assistant", "type": "message", "content": "ok"}
            ])

        fake_interpreter.chat = fake_chat
        fake_tracer = MagicMock()
        fake_tracer.observe_stream.side_effect = lambda events: events
        fake_tracer.record_mcp_tool_run.return_value = None
        fake_tracer.record_event.return_value = None
        fake_tracer.record_route_error.return_value = None
        fake_tracer.close.return_value = None

        async def fake_gather(db):
            return [], {}

        current_message = {
            "role": "user",
            "content": (
                "Analyse ce fichier.\n\n"
                "Files uploaded in this message:\n"
                "- current.csv (text/csv) | relative path: current.csv\n"
                "Use these paths when referencing the uploaded files."
            ),
        }

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [current_message]},
                headers={"x-session-id": "s1", "x-agent-type": "copepod"},
        )

        assert resp.status_code == 200
        assert "## Copepod Working Set" in captured["system_message"]
        assert "current_user_goal:" in captured["system_message"]
        assert "current.csv" in captured["system_message"]
        assert "path: /app/static/u1/s1/uploads/current.csv" in captured["system_message"]

    def test_chat_persists_stream_deliverable_for_next_turn_resources(self):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)
        fake_interpreter.system_message = "base prompt"

        captured_system_messages = []
        call_count = 0

        def fake_chat(message, stream=True):
            nonlocal call_count
            call_count += 1
            captured_system_messages.append(fake_interpreter.system_message)
            fake_interpreter.messages = list(message)
            if call_count == 1:
                return iter([
                    {
                        "role": "computer",
                        "type": "deliverable",
                        "start": True,
                        "end": True,
                        "content": (
                            '{"type":"graph","title":"Boîte à moustaches — profondeur par stade",'
                            '"file":"/app/static/u1/s1/uploads/boxplot.png",'
                            '"file_url":"/static/u1/s1/uploads/boxplot.png",'
                            '"filename":"boxplot.png"}'
                        ),
                    }
                ])
            return iter([
                {"start": True, "end": True, "role": "assistant", "type": "message", "content": "ok"}
            ])

        fake_interpreter.chat = fake_chat
        fake_tracer = MagicMock()
        fake_tracer.observe_stream.side_effect = lambda events: events
        fake_tracer.record_mcp_tool_run.return_value = None
        fake_tracer.record_event.return_value = None
        fake_tracer.record_route_error.return_value = None
        fake_tracer.close.return_value = None

        async def fake_gather(db):
            return [], {}

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            first = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "fais une boite moustache"}]},
                headers={"x-session-id": "s1", "x-agent-type": "copepod"},
            )
            second = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "reprends le dernier graphe"}]},
                headers={"x-session-id": "s1", "x-agent-type": "copepod"},
            )

        assert first.status_code == 200
        assert second.status_code == 200
        persisted = store.read_messages("u1:s1:copepod") or []
        assert any(
            msg.get("type") == "deliverable"
            and "Boîte à moustaches" in msg.get("content", "")
            for msg in persisted
        )
        assert "Deliverables:" in captured_system_messages[-1]
        assert "Boîte à moustaches" in captured_system_messages[-1]
        assert "Graph/image artifacts:" in captured_system_messages[-1]
        assert "boxplot.png" in captured_system_messages[-1]

    def test_chat_retries_after_join_key_error(self):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)

        store.write_messages(
            "u1:s1:copepod",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "content": (
                        "# RAPPORT D'INSPECTION\n"
                        "### Fichiers chargés\n"
                        "- **a.csv**\n"
                        "Clés de jointure potentielles : station | time | depth\n"
                    ),
                }
            ],
        )
        fake_interpreter.system_message = "base prompt"

        captured_calls = []
        captured_system_messages = []

        def fake_chat(message, stream=True):
            captured_calls.append(message)
            captured_system_messages.append(fake_interpreter.system_message)
            fake_interpreter.messages = list(message)
            if len(captured_calls) == 1:
                return iter([
                    {"start": True, "end": True, "role": "assistant", "type": "message", "content": "attempting join"},
                    {"error": "KeyError: 'station'"},
                ])
            return iter([
                {"start": True, "end": True, "role": "assistant", "type": "message", "content": "retry ok"},
            ])

        fake_interpreter.chat = fake_chat
        fake_tracer = MagicMock()
        fake_tracer.record_mcp_tool_run.return_value = None
        fake_tracer.record_event.return_value = None
        fake_tracer.record_route_error.return_value = None
        fake_tracer.close.return_value = None

        async def fake_gather(db):
            return [], {}

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "fais une jointure"}]},
                headers={"x-session-id": "s1", "x-agent-type": "copepod"},
            )

        assert resp.status_code == 200
        assert len(captured_calls) == 2
        assert all(msg.get("role") != "system" for msg in captured_calls[0])
        assert all(msg.get("role") != "system" for msg in captured_calls[1])
        # First attempt: dynamic note surfaces concrete inspection context.
        assert "inspection context for this turn" in captured_system_messages[0].lower()
        assert "recovery mode" in captured_system_messages[1].lower()
        assert "KeyError" in captured_system_messages[1]
        assert "retry ok" in resp.text

    def test_chat_retries_again_after_a_second_error(self):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)

        store.write_messages(
            "u1:s1:copepod",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "content": (
                        "# RAPPORT D'INSPECTION\n"
                        "### Fichiers chargés\n"
                        "- **a.csv**\n"
                        "Clés de jointure potentielles : station | time | depth\n"
                    ),
                }
            ],
        )
        fake_interpreter.system_message = "base prompt"

        captured_calls = []
        captured_system_messages = []

        def fake_chat(message, stream=True):
            captured_calls.append(message)
            captured_system_messages.append(fake_interpreter.system_message)
            fake_interpreter.messages = list(message)
            if len(captured_calls) == 1:
                return iter([
                    {"start": True, "end": True, "role": "assistant", "type": "message", "content": "attempting join"},
                    {"error": "KeyError: 'station'"},
                ])
            if len(captured_calls) == 2:
                return iter([
                    {"start": True, "end": True, "role": "assistant", "type": "message", "content": "retrying join"},
                    {"error": "ValueError: normalization failed"},
                ])
            return iter([
                {"start": True, "end": True, "role": "assistant", "type": "message", "content": "third try ok"},
            ])

        fake_interpreter.chat = fake_chat
        fake_tracer = MagicMock()
        fake_tracer.record_mcp_tool_run.return_value = None
        fake_tracer.record_event.return_value = None
        fake_tracer.record_route_error.return_value = None
        fake_tracer.close.return_value = None

        async def fake_gather(db):
            return [], {}

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "fais une jointure"}]},
                headers={"x-session-id": "s1", "x-agent-type": "copepod"},
            )

        assert resp.status_code == 200
        assert len(captured_calls) == 3
        assert all(msg.get("role") != "system" for msg in captured_calls[0])
        assert all(msg.get("role") != "system" for msg in captured_calls[1])
        assert all(msg.get("role") != "system" for msg in captured_calls[2])
        assert "inspection context for this turn" in captured_system_messages[0].lower()
        assert "recovery mode" in captured_system_messages[1].lower()
        assert "KeyError" in captured_system_messages[1]
        assert "recovery mode" in captured_system_messages[2].lower()
        assert "ValueError" in captured_system_messages[2]
        assert "third try ok" in resp.text

    def test_chat_retries_when_encoding_recovery_returns_status_without_code(self):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)

        fake_interpreter.system_message = "base prompt"

        captured_calls = []
        captured_system_messages = []

        def fake_chat(message, stream=True):
            captured_calls.append(message)
            captured_system_messages.append(fake_interpreter.system_message)
            fake_interpreter.messages = list(message)
            if len(captured_calls) == 1:
                return iter([
                    {"start": True, "end": True, "role": "assistant", "type": "message", "content": "attempting join"},
                    {
                        "start": True,
                        "end": True,
                        "role": "computer",
                        "type": "console",
                        "content": "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xb5 in position 383",
                    },
                ])
            if len(captured_calls) == 2:
                return iter([
                    {
                        "start": True,
                        "end": True,
                        "role": "assistant",
                        "type": "message",
                        "content": "Encodage CSV incompatible avec utf-8 ; la jointure n’est pas encore faite.",
                    },
                ])
            return iter([
                {"start": True, "end": True, "role": "assistant", "type": "code", "format": "python", "content": "pd.read_csv(path, encoding='cp1252')"},
                {"start": True, "end": True, "role": "assistant", "type": "message", "content": "retry code ok"},
            ])

        fake_interpreter.chat = fake_chat
        fake_tracer = MagicMock()
        fake_tracer.record_mcp_tool_run.return_value = None
        fake_tracer.record_event.return_value = None
        fake_tracer.record_route_error.return_value = None
        fake_tracer.close.return_value = None

        async def fake_gather(db):
            return [], {}

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "fais la jointure"}]},
                headers={"x-session-id": "s1", "x-agent-type": "copepod"},
            )

        assert resp.status_code == 200
        assert len(captured_calls) == 3
        assert "recovery mode" in captured_system_messages[1].lower()
        assert "recovery mode" in captured_system_messages[2].lower()
        assert "must run corrected Python code" in captured_system_messages[2]
        assert "retry code ok" in resp.text

    def test_chat_retries_clear_action_response_without_code_or_numbered_questions(self):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)

        fake_interpreter.system_message = "base prompt"

        captured_calls = []
        captured_system_messages = []

        def fake_chat(message, stream=True):
            captured_calls.append(message)
            captured_system_messages.append(fake_interpreter.system_message)
            fake_interpreter.messages = list(message)
            if len(captured_calls) == 1:
                return iter([
                    {
                        "start": True,
                        "end": True,
                        "role": "assistant",
                        "type": "message",
                        "content": "Je peux faire ce graphe avec les colonnes disponibles.",
                    },
                ])
            return iter([
                {
                    "start": True,
                    "end": True,
                    "role": "assistant",
                    "type": "code",
                    "format": "python",
                    "content": (
                        "import json\n"
                        "import matplotlib.pyplot as plt\n"
                        "plt.plot([1, 2])\n"
                        "plt.savefig('/tmp/graph.png')\n"
                        "plt.show()\n"
                        "print('DELIVERABLE: ' + json.dumps({'type': 'graph', 'title': 'Graph', 'file': '/tmp/graph.png'}))"
                    ),
                },
                {
                    "start": True,
                    "end": True,
                    "role": "assistant",
                    "type": "message",
                    "content": "retry graph ok",
                },
            ])

        fake_interpreter.chat = fake_chat
        fake_tracer = MagicMock()
        fake_tracer.record_mcp_tool_run.return_value = None
        fake_tracer.record_event.return_value = None
        fake_tracer.record_route_error.return_value = None
        fake_tracer.close.return_value = None

        async def fake_gather(db):
            return [], {}

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "fais un graphe de l'abondance"}]},
                headers={"x-session-id": "s1", "x-agent-type": "copepod"},
            )

        assert resp.status_code == 200
        assert len(captured_calls) == 2
        assert "plan + code contract" in captured_system_messages[1].lower()
        assert "numbered questions" in captured_system_messages[1]
        assert "retry graph ok" in resp.text

    def test_chat_retries_graph_code_without_show_or_deliverable(self):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)

        fake_interpreter.system_message = "base prompt"

        captured_calls = []
        captured_system_messages = []

        def fake_chat(message, stream=True):
            captured_calls.append(message)
            captured_system_messages.append(fake_interpreter.system_message)
            fake_interpreter.messages = list(message)
            if len(captured_calls) == 1:
                return iter([
                    {
                        "start": True,
                        "end": True,
                        "role": "assistant",
                        "type": "code",
                        "format": "python",
                        "content": (
                            "import matplotlib.pyplot as plt\n"
                            "plt.plot([1, 2])\n"
                            "plt.savefig('/tmp/graph.png')\n"
                        ),
                    },
                    {
                        "start": True,
                        "end": True,
                        "role": "assistant",
                        "type": "message",
                        "content": "graph saved",
                    },
                ])
            return iter([
                {
                    "start": True,
                    "end": True,
                    "role": "assistant",
                    "type": "code",
                    "format": "python",
                    "content": (
                        "import json\n"
                        "import matplotlib.pyplot as plt\n"
                        "plt.plot([1, 2])\n"
                        "plt.savefig('/tmp/graph.png')\n"
                        "plt.show()\n"
                        "print('DELIVERABLE: ' + json.dumps({'type': 'graph', 'title': 'Graph', 'file': '/tmp/graph.png'}))"
                    ),
                },
                {
                    "start": True,
                    "end": True,
                    "role": "assistant",
                    "type": "message",
                    "content": "retry graph displayed",
                },
            ])

        fake_interpreter.chat = fake_chat
        fake_tracer = MagicMock()
        fake_tracer.record_mcp_tool_run.return_value = None
        fake_tracer.record_event.return_value = None
        fake_tracer.record_route_error.return_value = None
        fake_tracer.close.return_value = None

        async def fake_gather(db):
            return [], {}

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "fais un graphe de l'abondance"}]},
                headers={"x-session-id": "s1", "x-agent-type": "copepod"},
            )

        assert resp.status_code == 200
        assert len(captured_calls) == 2
        assert "graph output contract" in captured_system_messages[1].lower()
        assert "plt.show()" in captured_system_messages[1]
        assert "retry graph displayed" in resp.text

    def test_chat_strips_restored_system_messages_for_generic_agent(self):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)

        store.write_messages(
            "u1:s1:generic",
            [
                {"role": "system", "type": "message", "content": "legacy system note"},
                {"role": "user", "type": "message", "content": "hello"},
            ],
        )
        fake_interpreter.system_message = "base prompt"

        captured = {}

        def fake_chat(message, stream=True):
            captured["message"] = message
            captured["system_message"] = fake_interpreter.system_message
            fake_interpreter.messages = list(message)
            return iter([
                {"start": True, "end": True, "role": "assistant", "type": "message", "content": "ok"}
            ])

        fake_interpreter.chat = fake_chat
        fake_tracer = MagicMock()
        fake_tracer.record_mcp_tool_run.return_value = None
        fake_tracer.record_event.return_value = None
        fake_tracer.record_route_error.return_value = None
        fake_tracer.close.return_value = None

        async def fake_gather(db):
            return [], {}

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "hello"}]},
                headers={"x-session-id": "s1", "x-agent-type": "generic"},
            )

        assert resp.status_code == 200
        assert isinstance(captured["message"], list)
        assert all(msg.get("role") != "system" for msg in captured["message"])
        assert captured["system_message"] == "base prompt"

    def test_chat_emits_generation_summary_with_usage_metadata(self):
        store = InMemorySessionStore()
        app, fake_user, fake_interpreter, fake_profile = _make_chat_client(store)

        captured = {}

        def fake_chat(message, stream=True):
            captured["message"] = message
            return iter([
                {"start": True, "end": True, "role": "assistant", "type": "message", "content": "ok"},
                {
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                        "cost": 0.000123,
                    }
                },
            ])

        fake_interpreter.chat = fake_chat
        fake_tracer = MagicMock()
        fake_tracer.observe_stream.side_effect = lambda events: events
        fake_tracer.record_mcp_tool_run.return_value = None
        fake_tracer.record_event.return_value = None
        fake_tracer.record_route_error.return_value = None
        fake_tracer.close.return_value = None

        async def fake_gather(db):
            return [], {}

        with (
            patch("routers.chat_routes.get_current_user", return_value=fake_user),
            patch("routers.chat_routes.session_store", store),
            patch("routers.chat_routes.get_or_create_interpreter", return_value=fake_interpreter),
            patch("routers.chat_routes.gather_available_mcp_tools", new=fake_gather),
            patch("routers.chat_routes.ensure_user_pqa_settings"),
            patch("routers.chat_routes.get_profile", return_value=fake_profile),
            patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer),
            patch("routers.chat_routes.chat_stream_events", side_effect=lambda events: events),
        ):
            tc = TestClient(app)
            resp = tc.post(
                "/chat",
                json={"messages": [{"role": "user", "content": "hello"}]},
                headers={"x-session-id": "s1"},
            )

        assert resp.status_code == 200
        assert '"type": "generation_summary"' in resp.text
        assert '"prompt_tokens": 10' in resp.text
        assert '"completion_tokens": 20' in resp.text


# ---------------------------------------------------------------------------
# Per-session lock for concurrent /chat turns (P3 — race condition fix)
# ---------------------------------------------------------------------------

class TestSessionLock:
    """The per-session_key threading.Lock protects the shared OpenInterpreter
    from concurrent mutations of `.system_message` and `.messages` when two
    requests on the same session land at the same time. Regression-critical:
    if a fresh Lock is returned on every call, the protection is meaningless.
    """

    def test_same_session_key_returns_same_lock_instance(self):
        lock_a = _session_lock("user-1:session-abc:copepod")
        lock_b = _session_lock("user-1:session-abc:copepod")
        assert lock_a is lock_b

    def test_different_session_keys_return_different_locks(self):
        lock_a = _session_lock("user-1:session-abc:copepod")
        lock_b = _session_lock("user-1:session-xyz:copepod")
        assert lock_a is not lock_b

    def test_lock_serialises_two_threads_on_same_session(self):
        """Two threads that try to enter the lock for the same session_key
        must NOT overlap their critical section. We record entry/exit times
        and assert no interleaving."""
        import threading
        import time

        key = "user-1:session-concurrent:copepod"
        intervals: list[tuple[float, float]] = []
        intervals_lock = threading.Lock()
        ready = threading.Barrier(2)

        def worker():
            ready.wait()
            with _session_lock(key):
                start = time.monotonic()
                # Simulate a critical section (mutating shared state).
                time.sleep(0.05)
                end = time.monotonic()
                with intervals_lock:
                    intervals.append((start, end))

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(intervals) == 2
        (s1, e1), (s2, e2) = sorted(intervals)
        # The second critical section must start AFTER the first one ended.
        # If the lock didn't work, e1 > s2 would be possible (overlap).
        assert s2 >= e1, (
            f"Critical sections overlapped: first=({s1}, {e1}), second=({s2}, {e2})"
        )

    def test_different_sessions_do_not_block_each_other(self):
        """Threads on different session_keys must run in parallel, otherwise
        a slow user would block every other user globally."""
        import threading
        import time

        intervals: list[tuple[float, float]] = []
        intervals_lock = threading.Lock()
        ready = threading.Barrier(2)

        def worker(key: str):
            ready.wait()
            with _session_lock(key):
                start = time.monotonic()
                time.sleep(0.05)
                end = time.monotonic()
                with intervals_lock:
                    intervals.append((start, end))

        t1 = threading.Thread(target=worker, args=("user-1:s1:copepod",))
        t2 = threading.Thread(target=worker, args=("user-2:s2:copepod",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(intervals) == 2
        (s1, e1), (s2, e2) = sorted(intervals)
        # Independent sessions: their critical sections SHOULD overlap.
        assert s2 < e1, (
            f"Different sessions were serialised — lock leaks across keys: "
            f"first=({s1}, {e1}), second=({s2}, {e2})"
        )


# ---------------------------------------------------------------------------
# _measure_context_chars
# ---------------------------------------------------------------------------

class TestMeasureContextChars:
    from routers.chat_routes import _measure_context_chars

    def _call(self, chat_input=None, base_sys="", runtime_sys="", custom=""):
        from routers.chat_routes import _measure_context_chars
        return _measure_context_chars(
            chat_input=chat_input or [],
            base_system_message=base_sys,
            runtime_system_message=runtime_sys,
            custom_instructions=custom,
        )

    def test_empty_inputs_return_zero(self):
        assert self._call() == 0

    def test_counts_base_system_message(self):
        result = self._call(base_sys="a" * 100)
        assert result == 100

    def test_counts_custom_instructions(self):
        result = self._call(custom="b" * 200)
        assert result == 200

    def test_counts_runtime_system_message(self):
        result = self._call(runtime_sys="c" * 50)
        assert result == 50

    def test_counts_chat_input_content(self):
        chat_input = [
            {"role": "user", "content": "hello"},       # 5 chars
            {"role": "assistant", "content": "world"},  # 5 chars
        ]
        assert self._call(chat_input=chat_input) == 10

    def test_all_components_summed(self):
        chat_input = [{"role": "user", "content": "x" * 100}]
        result = self._call(
            chat_input=chat_input,
            base_sys="a" * 1000,
            runtime_sys="b" * 500,
            custom="c" * 2000,
        )
        assert result == 100 + 1000 + 500 + 2000

    def test_none_values_treated_as_empty(self):
        assert self._call(base_sys=None, runtime_sys=None, custom=None) == 0

    def test_non_dict_messages_skipped(self):
        chat_input = [
            {"role": "user", "content": "hello"},
            "not a dict",
            None,
        ]
        assert self._call(chat_input=chat_input) == 5

    def test_missing_content_key_skipped(self):
        chat_input = [{"role": "system"}, {"role": "user", "content": "hi"}]
        assert self._call(chat_input=chat_input) == 2

    def test_none_content_skipped(self):
        chat_input = [{"role": "user", "content": None}]
        assert self._call(chat_input=chat_input) == 0

    def test_realistic_copepod_turn_order_of_magnitude(self):
        """At turn 1, full copepod context should be in the 20k–60k char range."""
        base_sys = "x" * 4000       # copepod prompt ~3-4k chars
        custom = "x" * 12000        # tool signatures ~10-15k chars
        runtime_sys = "x" * 2000   # working set note
        history = [{"role": "user", "content": "x" * 500}]
        result = self._call(
            chat_input=history,
            base_sys=base_sys,
            runtime_sys=runtime_sys,
            custom=custom,
        )
        assert 15_000 < result < 100_000


# ---------------------------------------------------------------------------
# _strip_old_base64_image_messages
# ---------------------------------------------------------------------------

class TestStripOldBase64ImageMessages:

    def _call(self, messages, keep_last=1):
        from routers.chat_routes import _strip_old_base64_image_messages
        return _strip_old_base64_image_messages(messages, keep_last=keep_last)

    def _b64_msg(self, content="iVBORw0Kfake"):
        return {"role": "computer", "type": "image", "format": "base64.png", "content": content}

    def _path_msg(self, path="/app/static/graph.png"):
        return {"role": "computer", "type": "image", "format": "path", "content": path}

    def _text_msg(self, content="hello"):
        return {"role": "assistant", "type": "message", "content": content}

    # --- comportement 1 : liste vide
    def test_empty_list_returns_empty(self):
        assert self._call([]) == []

    # --- comportement 2 : une seule image base64 → gardée (keep_last=1)
    def test_single_base64_image_kept_with_keep_last_1(self):
        msg = self._b64_msg()
        result = self._call([msg])
        assert result == [msg]

    # --- comportement 3 : deux images base64 → première supprimée, dernière gardée
    def test_two_base64_images_keeps_only_last(self):
        old = self._b64_msg("iVBORold")
        new = self._b64_msg("iVBORnew")
        result = self._call([old, new])
        assert old not in result
        assert new in result

    # --- comportement 4 : les messages path ne sont jamais supprimés
    def test_path_images_never_stripped(self):
        path_msg = self._path_msg()
        b64_old = self._b64_msg("iVBORold")
        b64_new = self._b64_msg("iVBORnew")
        result = self._call([path_msg, b64_old, b64_new])
        assert path_msg in result

    # --- comportement 5 : les messages non-image sont préservés
    def test_non_image_messages_preserved(self):
        text = self._text_msg()
        b64_old = self._b64_msg("iVBORold")
        b64_new = self._b64_msg("iVBORnew")
        result = self._call([text, b64_old, b64_new])
        assert text in result

    # --- comportement 6 : keep_last=0 supprime toutes les base64
    def test_keep_last_0_strips_all_base64(self):
        b64 = self._b64_msg()
        result = self._call([b64], keep_last=0)
        assert b64 not in result

    # --- comportement 7 : keep_last=2 garde les deux dernières
    def test_keep_last_2_keeps_two_most_recent(self):
        msgs = [self._b64_msg(f"iVBOR{i}") for i in range(4)]
        result = self._call(msgs, keep_last=2)
        assert msgs[0] not in result
        assert msgs[1] not in result
        assert msgs[2] in result
        assert msgs[3] in result

    # --- comportement 8 : content "data:image/..." est aussi reconnu comme base64
    def test_data_url_content_treated_as_base64(self):
        data_url_msg = {"role": "computer", "type": "image", "format": "base64.png",
                        "content": "data:image/png;base64,abc123"}
        result = self._call([data_url_msg], keep_last=0)
        assert data_url_msg not in result

    # --- comportement 9 : ordre préservé
    def test_order_preserved(self):
        text1 = self._text_msg("first")
        b64 = self._b64_msg()
        text2 = self._text_msg("last")
        result = self._call([text1, b64, text2])
        assert result.index(text1) < result.index(text2)

    # --- comportement 10 : ne mute pas la liste originale
    def test_does_not_mutate_original(self):
        msgs = [self._b64_msg("old"), self._b64_msg("new")]
        original_len = len(msgs)
        self._call(msgs)
        assert len(msgs) == original_len


# ---------------------------------------------------------------------------
# _truncate_after_emit_deliverable
# ---------------------------------------------------------------------------

class TestTruncateAfterEmitDeliverable:

    def _call(self, code):
        from routers.chat_routes import _truncate_after_emit_deliverable
        return _truncate_after_emit_deliverable(code)

    # Cycle 1 — tracer bullet : print après supprimé
    def test_strips_print_after_single_line_emit(self):
        code = 'emit_deliverable(type="graph", title="T")\nprint("done")'
        result = self._call(code)
        assert 'emit_deliverable' in result
        assert 'print("done")' not in result

    # Cycle 2 — pas de emit_deliverable → inchangé
    def test_no_emit_deliverable_unchanged(self):
        code = 'plt.savefig(out)\nprint("done")'
        assert self._call(code) == code

    # Cycle 3 — emit_deliverable multiligne
    def test_multiline_emit_deliverable_strips_after(self):
        code = (
            'emit_deliverable(\n'
            '    type="graph",\n'
            '    title="T",\n'
            '    file=out\n'
            ')\n'
            'print("trailing")\n'
            'print("more")'
        )
        result = self._call(code)
        assert 'print("trailing")' not in result
        assert 'print("more")' not in result
        assert 'emit_deliverable' in result

    # Cycle 4 — rien après → no-op
    def test_nothing_after_emit_is_noop(self):
        code = 'emit_deliverable(type="graph", title="T", file=out)'
        result = self._call(code)
        assert 'emit_deliverable' in result
        assert result.strip().endswith(')')

    # Cycle 5 — code avant préservé
    def test_code_before_emit_preserved(self):
        code = 'plt.savefig(out)\nemit_deliverable(type="graph")\nprint("x")'
        result = self._call(code)
        assert 'plt.savefig(out)' in result
        assert 'print("x")' not in result

    # Cycle 6 — parenthèses dans string pas confondues
    def test_parens_inside_string_not_confused(self):
        code = 'emit_deliverable(type="graph", title="T(S)")\nprint("x")'
        result = self._call(code)
        assert 'print("x")' not in result
        assert 'emit_deliverable' in result

    # Cycle 7 — chaîne vide
    def test_empty_string(self):
        assert self._call('') == ''

    # Cycle 8 — commentaires avec parens pas confondus
    def test_comment_parens_not_confused(self):
        code = (
            'emit_deliverable(\n'
            '    type="graph"  # champ (requis)\n'
            ')\n'
            'print("after")'
        )
        result = self._call(code)
        assert 'print("after")' not in result


class TestScrubConsoleNoise:
    def _call(self, content: str) -> str:
        from routers.chat_routes import _scrub_console_noise
        return _scrub_console_noise(content)

    def test_onnxruntime_line_removed(self):
        content = "onnxruntime cpu id_info warning: Unknown CPU vendor\nsome real output"
        result = self._call(content)
        assert "onnxruntime" not in result
        assert "some real output" in result

    def test_deliverable_line_removed(self):
        content = 'DELIVERABLE: {"type": "graph"}\nsome real output'
        result = self._call(content)
        assert "DELIVERABLE:" not in result
        assert "some real output" in result

    def test_displayed_on_user_line_removed(self):
        content = "Displayed on the user's machine\ndata: 123"
        result = self._call(content)
        assert "Displayed on the user" not in result
        assert "data: 123" in result

    def test_chromadb_line_removed(self):
        result = self._call("chromadb: Using embedded DuckDB\nreal output")
        assert "chromadb" not in result
        assert "real output" in result

    def test_userwarning_line_removed(self):
        result = self._call("UserWarning: something deprecated\nreal output")
        assert "UserWarning" not in result

    def test_deprecationwarning_line_removed(self):
        result = self._call("DeprecationWarning: use X instead\nreal output")
        assert "DeprecationWarning" not in result

    def test_tqdm_line_removed(self):
        result = self._call("tqdm: 100%|████| 10/10\nreal output")
        assert "tqdm" not in result

    def test_no_noise_content_unchanged(self):
        content = "shape: (1004, 16)\ncolumns: [a, b, c]"
        result = self._call(content)
        assert result == content

    def test_empty_string_unchanged(self):
        assert self._call("") == ""

    def test_all_noise_returns_empty(self):
        content = "onnxruntime warning\nDELIVERABLE: {}\ntqdm: 0%"
        result = self._call(content)
        assert result.strip() == ""

    def test_indented_noise_line_removed(self):
        content = "  onnxruntime cpu warning\nreal output"
        result = self._call(content)
        assert "onnxruntime" not in result
        assert "real output" in result


class TestAssistantTextHasNumberedQuestions:
    def _call(self, text: str) -> bool:
        from routers.chat_routes import _assistant_text_has_numbered_questions
        return _assistant_text_has_numbered_questions(text)

    def test_numbered_steps_without_question_marks_return_false(self):
        text = (
            "On peut commencer par :\n"
            "1. isoler les copepodes\n"
            "2. récupérer l'abondance totale\n"
            "3. relier ça à la température\n"
            "4. faire un graphe clair\n"
        )
        assert self._call(text) is False

    def test_numbered_questions_with_question_mark_return_true(self):
        text = (
            "J'ai besoin de précisions :\n"
            "1. Quel est le format attendu ?\n"
            "2. Quelle colonne de température utiliser ?\n"
        )
        assert self._call(text) is True

    def test_mixed_steps_and_one_question_returns_true(self):
        text = (
            "1. isoler les copepodes\n"
            "2. Quelle fraction d'abondance veux-tu utiliser ?\n"
        )
        assert self._call(text) is True

    def test_empty_string_returns_false(self):
        assert self._call("") is False

    def test_no_numbered_items_returns_false(self):
        assert self._call("- bullet a\n- bullet b\nsome prose") is False

    def test_real_session_plan_returns_false(self):
        # Exact pattern from session-yslaa2w2x T7 that was wrongly blocking retries
        text = (
            "On peut commencer par :\n\n"
            "1. isoler les copepodes\n"
            "2. récupérer l'abondance totale\n"
            "3. relier ça à la température\n"
            "4. faire un graphe clair\n\n"
            "Si tu veux, je peux faire directement un **premier graphe simple**."
        )
        assert self._call(text) is False
