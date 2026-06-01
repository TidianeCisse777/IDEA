"""
Tests for the interpreter lifecycle functions in core/interpreter_session.py.

Uses unittest.mock.patch to replace module-level singletons so tests remain
fast and dependency-free (no Redis, no OpenInterpreter required).

The ``interpreter`` package is a heavy external dependency not installed in CI;
we stub the entire module via sys.modules before importing the module under test.
"""
from __future__ import annotations

import sys
import types
import importlib.metadata as importlib_metadata
from unittest.mock import MagicMock, patch

from core.session_store import InMemorySessionStore

# Pydantic's EmailStr import path needs email-validator in this environment.
email_validator_stub = types.ModuleType("email_validator")
email_validator_stub.validate_email = lambda *args, **kwargs: None
sys.modules.setdefault("email_validator", email_validator_stub)

litellm_stub = types.ModuleType("litellm")
litellm_stub.completion = lambda **kwargs: {"choices": [{"message": {"content": "ok"}}]}
sys.modules.setdefault("litellm", litellm_stub)

_real_metadata_version = importlib_metadata.version


def _metadata_version(name: str) -> str:
    if name == "email-validator":
        return "2.0.0"
    return _real_metadata_version(name)


importlib_metadata.version = _metadata_version

# ---------------------------------------------------------------------------
# Stub the ``interpreter`` package so the module can be imported without it.
# ---------------------------------------------------------------------------

def _make_interpreter_stub():
    """Return a minimal fake ``interpreter`` package tree."""
    pkg = types.ModuleType("interpreter")
    core_pkg = types.ModuleType("interpreter.core")
    core_mod = types.ModuleType("interpreter.core.core")

    # Minimal OpenInterpreter stub
    class OpenInterpreter:  # noqa: D101
        def __init__(self):
            self.llm = MagicMock()
            self.computer = MagicMock()
            self.messages = []
            self.system_message = ""
            self.custom_instructions = ""
            self.auto_run = False
            self.max_output = 2048

        def reset(self):
            self.messages = []

    core_mod.OpenInterpreter = OpenInterpreter
    pkg.core = core_pkg
    core_pkg.core = core_mod
    return pkg, core_pkg, core_mod


_interpreter_pkg, _interpreter_core_pkg, _interpreter_core_mod = _make_interpreter_stub()
sys.modules.setdefault("interpreter", _interpreter_pkg)
sys.modules.setdefault("interpreter.core", _interpreter_core_pkg)
sys.modules.setdefault("interpreter.core.core", _interpreter_core_mod)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_clear_session_evicts_store_and_removes_dir(tmp_path):
    from core import interpreter_session as iss

    # Setup: fake session in store and filesystem
    store = InMemorySessionStore()
    store.write_messages("u:s:generic", [{"role": "user", "content": "hi"}])
    store.touch("u:s:generic")
    session_dir = tmp_path / "u" / "s"
    session_dir.mkdir(parents=True)

    with patch.object(iss, "session_store", store), \
         patch.object(iss, "interpreter_instances", {}), \
         patch("core.interpreter_session.session_dir_path", return_value=session_dir):
        iss.clear_session("u:s:generic")

    assert store.read_messages("u:s:generic") is None
    assert not session_dir.exists()


def test_cleanup_idle_removes_stale_session():
    import asyncio
    from core import interpreter_session as iss

    store = InMemorySessionStore()
    store.write_messages("u:s:generic", [])
    store.touch("u:s:generic")
    # Artificially age the session so it looks stale (timestamp = Unix epoch)
    store._timestamps["u:s:generic"] = 0.0

    instances = {"u:s:generic": MagicMock()}

    with patch.object(iss, "session_store", store), \
         patch.object(iss, "interpreter_instances", instances), \
         patch("core.interpreter_session.session_dir_path", return_value=None), \
         patch("core.interpreter_session.shutil.rmtree", return_value=None):
        asyncio.run(iss.cleanup_idle_sessions())

    assert "u:s:generic" not in instances


def test_llm_wrapper_preserves_multimodal_message_content():
    from core import interpreter_session as iss

    captured = {}

    def fake_completion(**params):
        captured["params"] = params
        return {"choices": [{"message": {"content": "ok"}}]}

    fake_profile = MagicMock()
    fake_profile.get_system_message.return_value = ""
    fake_profile.get_tool_code.return_value = ""
    fake_profile.configure_interpreter.return_value = None

    with (
        patch.object(iss, "get_profile", return_value=fake_profile),
        patch("litellm.completion", side_effect=fake_completion),
        patch.object(iss, "interpreter_instances", {}),
    ):
        interpreter = iss.get_or_create_interpreter(
            session_key="u:s:copepod",
            token=None,
            db=None,
            agent_type="copepod",
        )

        interpreter.llm.completions(
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyse cette image."},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,AAA"},
                        },
                    ],
                }
            ],
            instructions="system",
            stream=True,
        )

    messages = captured["params"]["messages"]
    assert isinstance(messages[1]["content"], list)
    assert messages[1]["content"][1]["type"] == "image_url"
    assert captured["params"]["stream_options"]["include_usage"] is True
    assert captured["params"]["repetition_penalty"] == 1.1


def test_llm_wrapper_normalizes_input_text_items_to_chat_content():
    from core import interpreter_session as iss

    captured = {}

    def fake_completion(**params):
        captured["params"] = params
        return {"choices": [{"message": {"content": "ok"}}]}

    fake_profile = MagicMock()
    fake_profile.get_system_message.return_value = ""
    fake_profile.get_tool_code.return_value = ""
    fake_profile.configure_interpreter.return_value = None

    with (
        patch.object(iss, "get_profile", return_value=fake_profile),
        patch("litellm.completion", side_effect=fake_completion),
        patch.object(iss, "interpreter_instances", {}),
    ):
        interpreter = iss.get_or_create_interpreter(
            session_key="u:s:copepod",
            token=None,
            db=None,
            agent_type="copepod",
        )

        interpreter.llm.completions(
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "hey"},
                    ],
                }
            ],
            instructions="system",
        )

    messages = captured["params"]["messages"]
    assert messages[1]["content"] == "hey"
    assert captured["params"]["repetition_penalty"] == 1.1


def test_llm_wrapper_normalizes_direct_messages_payloads():
    from core import interpreter_session as iss

    captured = {}

    class FakeLLM:
        def __init__(self):
            self.model = ""
            self.completions = self._completions

        def _completions(self, **params):
            captured["params"] = params
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeInterpreter:
        def __init__(self):
            self.llm = FakeLLM()
            self.computer = MagicMock()
            self.messages = []
            self.system_message = ""
            self.custom_instructions = ""
            self.auto_run = False
            self.max_output = 2048

        def reset(self):
            self.messages = []

    fake_profile = MagicMock()
    fake_profile.get_system_message.return_value = ""
    fake_profile.get_tool_code.return_value = ""
    fake_profile.configure_interpreter.return_value = None

    with (
        patch.object(iss, "get_profile", return_value=fake_profile),
        patch.object(iss, "OpenInterpreter", FakeInterpreter),
        patch.object(iss, "interpreter_instances", {}),
    ):
        interpreter = iss.get_or_create_interpreter(
            session_key="u:s:copepod",
            token=None,
            db=None,
            agent_type="copepod",
        )

        interpreter.llm.completions(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "hey"},
                    ],
                }
            ],
            stream=False,
        )

    messages = captured["params"]["messages"]
    assert messages[0]["content"] == "hey"
    assert captured["params"]["repetition_penalty"] == 1.1


def test_copepod_interpreter_uses_temperature_from_env():
    from core import interpreter_session as iss

    fake_profile = MagicMock()
    fake_profile.get_system_message.return_value = ""
    fake_profile.get_tool_code.return_value = ""
    fake_profile.configure_interpreter.return_value = None

    with (
        patch.object(iss.settings, "LLM_TEMPERATURE", 0.3),
        patch.object(iss.settings, "LLM_REPETITION_PENALTY", 1.1),
        patch.object(iss, "get_profile", return_value=fake_profile),
        patch.object(iss, "interpreter_instances", {}),
    ):
        interpreter = iss.get_or_create_interpreter(
            session_key="u:s:copepod",
            token=None,
            db=None,
            agent_type="copepod",
        )

    assert interpreter.llm.temperature == 0.3
    assert interpreter.llm.repetition_penalty == 1.1


def test_llm_wrapper_enables_usage_for_direct_streaming_messages():
    from core import interpreter_session as iss

    captured = {}

    class FakeLLM:
        def __init__(self):
            self.model = ""
            self.completions = self._completions

        def _completions(self, **params):
            captured["params"] = params
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeInterpreter:
        def __init__(self):
            self.llm = FakeLLM()
            self.computer = MagicMock()
            self.messages = []
            self.system_message = ""
            self.custom_instructions = ""
            self.auto_run = False
            self.max_output = 2048

        def reset(self):
            self.messages = []

    fake_profile = MagicMock()
    fake_profile.get_system_message.return_value = ""
    fake_profile.get_tool_code.return_value = ""
    fake_profile.configure_interpreter.return_value = None

    with (
        patch.object(iss, "get_profile", return_value=fake_profile),
        patch.object(iss, "OpenInterpreter", FakeInterpreter),
        patch.object(iss, "interpreter_instances", {}),
    ):
        interpreter = iss.get_or_create_interpreter(
            session_key="u:s:copepod",
            token=None,
            db=None,
            agent_type="copepod",
        )

        interpreter.llm.completions(
            messages=[{"role": "user", "content": "hey"}],
            stream=True,
        )

    assert captured["params"]["stream_options"]["include_usage"] is True
