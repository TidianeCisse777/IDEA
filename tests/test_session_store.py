"""Tests for the InMemorySessionStore implementation of SessionStore."""
from core.session_store import InMemorySessionStore


def test_write_then_read():
    store = InMemorySessionStore()
    store.write_messages("user:sess:generic", [{"role": "user", "content": "hi"}])
    result = store.read_messages("user:sess:generic")
    assert result == [{"role": "user", "content": "hi"}]


def test_read_nonexistent_returns_none():
    store = InMemorySessionStore()
    assert store.read_messages("ghost:key") is None


def test_evict_clears_messages_and_timestamp():
    store = InMemorySessionStore()
    store.write_messages("k", [])
    store.touch("k")
    store.evict("k")
    assert store.read_messages("k") is None
    assert store.get_last_active("k") is None


def test_all_session_keys():
    store = InMemorySessionStore()
    store.touch("a:b:c")
    store.touch("d:e:f")
    keys = store.all_session_keys()
    assert "a:b:c" in keys
    assert "d:e:f" in keys


def test_get_session_mode_defaults_to_plan():
    store = InMemorySessionStore()
    assert store.get_session_mode("user:sess:copepod") == "plan"


def test_set_then_get_session_mode():
    store = InMemorySessionStore()
    store.set_session_mode("user:sess:copepod", "analyse")
    assert store.get_session_mode("user:sess:copepod") == "analyse"


def test_session_mode_isolated_per_key():
    store = InMemorySessionStore()
    store.set_session_mode("user1:sess1:copepod", "analyse")
    assert store.get_session_mode("user2:sess2:copepod") == "plan"


def test_session_mode_can_switch_back():
    store = InMemorySessionStore()
    store.set_session_mode("k", "analyse")
    store.set_session_mode("k", "plan")
    assert store.get_session_mode("k") == "plan"
