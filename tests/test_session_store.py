"""Tests for the lean InMemorySessionStore (Plan/artifact methods removed)."""
from __future__ import annotations

from core.session_store import InMemorySessionStore


def test_messages_round_trip():
    store = InMemorySessionStore()
    assert store.read_messages("k") is None
    store.write_messages("k", [{"role": "user", "content": "hi"}])
    assert store.read_messages("k") == [{"role": "user", "content": "hi"}]


def test_touch_and_last_active():
    store = InMemorySessionStore()
    assert store.get_last_active("k") is None
    store.touch("k")
    assert isinstance(store.get_last_active("k"), float)


def test_all_session_keys_lists_touched_only():
    store = InMemorySessionStore()
    store.touch("a")
    store.touch("b")
    assert set(store.all_session_keys()) == {"a", "b"}


def test_evict_clears_messages_timestamps_and_online_mode():
    store = InMemorySessionStore()
    store.write_messages("k", [{"role": "user", "content": "x"}])
    store.touch("k")
    store.set_online_mode("k", True)
    store.evict("k")
    assert store.read_messages("k") is None
    assert store.get_last_active("k") is None
    assert store.get_online_mode("k") is False


def test_online_mode_defaults_to_false():
    store = InMemorySessionStore()
    assert store.get_online_mode("k") is False
    store.set_online_mode("k", True)
    assert store.get_online_mode("k") is True
    store.set_online_mode("k", False)
    assert store.get_online_mode("k") is False
