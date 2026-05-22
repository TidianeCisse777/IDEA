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
from unittest.mock import MagicMock, patch

from core.session_store import InMemorySessionStore

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
