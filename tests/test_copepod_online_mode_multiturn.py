"""
Multi-turn online mode consistency tests.

Verifies that online mode state changes made mid-session are immediately
reflected in subsequent LLM custom instructions — the core requirement for
multi-turn LLM/user conversations to behave like the evals define.
"""
from __future__ import annotations

import importlib

import pytest

from core.session_store import InMemorySessionStore
from utils.session_utils import make_session_key

pytestmark = pytest.mark.workflow


@pytest.fixture(autouse=True)
def _reload_profile():
    import agents.copepod_profile
    importlib.reload(agents.copepod_profile)


def _get_instructions(store: InMemorySessionStore, user_id: str, session_id: str) -> str:
    import agents.copepod_profile
    profile = agents.copepod_profile.CopepodProfile(session_store=store)
    return profile.get_custom_instructions(
        host="http://localhost",
        user_id=user_id,
        session_id=session_id,
        static_dir="/static",
        upload_dir="/uploads",
    )


# ── Behavior 1: offline→online change is visible in next instructions ────────

def test_online_mode_off_to_on_reflected_in_next_instructions():
    """Turn 1 sees OFF, toggle ON, Turn 2 sees ON — within the same session."""
    store = InMemorySessionStore()
    user_id, session_id = "u1", "s1"
    session_key = make_session_key(user_id, session_id, "copepod")

    # Turn 1 — online mode is OFF by default
    instructions_turn1 = _get_instructions(store, user_id, session_id)
    assert "Mode En Ligne: OFF" in instructions_turn1

    # Mid-session toggle to ON (simulates user enabling in account settings)
    store.set_online_mode(session_key, True)

    # Turn 2 — instructions must reflect the new state
    instructions_turn2 = _get_instructions(store, user_id, session_id)
    assert "Mode En Ligne: ON" in instructions_turn2


def test_online_mode_on_to_off_reflected_in_next_instructions():
    """Toggle back to OFF is also immediately visible."""
    store = InMemorySessionStore()
    user_id, session_id = "u1", "s1"
    session_key = make_session_key(user_id, session_id, "copepod")

    store.set_online_mode(session_key, True)
    assert "Mode En Ligne: ON" in _get_instructions(store, user_id, session_id)

    store.set_online_mode(session_key, False)
    assert "Mode En Ligne: OFF" in _get_instructions(store, user_id, session_id)


# ── Behavior 2: online mode is isolated per session (no cross-session bleed) ─

def test_online_mode_toggle_does_not_bleed_to_other_sessions():
    """Enabling online mode for session A must not affect session B."""
    store = InMemorySessionStore()
    key_a = make_session_key("u1", "s-a", "copepod")
    key_b = make_session_key("u1", "s-b", "copepod")

    store.set_online_mode(key_a, True)

    # Session A: ON
    instr_a = _get_instructions(store, "u1", "s-a")
    assert "Mode En Ligne: ON" in instr_a

    # Session B: still OFF
    instr_b = _get_instructions(store, "u1", "s-b")
    assert "Mode En Ligne: OFF" in instr_b


# ── Behavior 3: allowed sources are present in the system message ─────────────

def test_online_mode_allowed_sources_in_instructions_when_on():
    """When online mode is ON the instruction text mentions the allowed sources."""
    store = InMemorySessionStore()
    session_key = make_session_key("u1", "s1", "copepod")

    store.set_online_mode(session_key, True)

    instructions = _get_instructions(store, "u1", "s1")
    # The session_metadata block includes the allowlist
    assert "OGSL" in instructions
    assert "Bio-ORACLE" in instructions


# ── Behavior 4: multiple instruction calls within the same session are stable ─

def test_multiple_instructions_calls_without_toggle_stay_consistent():
    """Calling get_custom_instructions repeatedly with no toggle change is idempotent."""
    store = InMemorySessionStore()

    # Three consecutive calls — no toggle in between
    i1 = _get_instructions(store, "u1", "s1")
    i2 = _get_instructions(store, "u1", "s1")
    i3 = _get_instructions(store, "u1", "s1")

    assert i1 == i2 == i3
