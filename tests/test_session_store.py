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


def test_working_set_round_trip_and_evict():
    store = InMemorySessionStore()
    assert store.read_working_set("k") is None

    working_set = {
        "seen_files": ["a.csv"],
        "active_files": ["b.csv"],
        "latest_inspection_by_file": {"a.csv": "inspected"},
        "current_user_goal": "inspect b.csv",
    }

    store.write_working_set("k", working_set)
    assert store.read_working_set("k") == working_set

    store.evict("k")
    assert store.read_working_set("k") is None


def test_online_mode_defaults_to_false():
    store = InMemorySessionStore()
    assert store.get_online_mode("k") is False
    store.set_online_mode("k", True)
    assert store.get_online_mode("k") is True
    store.set_online_mode("k", False)
    assert store.get_online_mode("k") is False


def test_inspection_report_round_trip_and_isolation():
    store = InMemorySessionStore()
    assert store.read_inspection_report("k", "a.csv") is None
    assert store.list_inspection_reports("k") == []

    store.store_inspection_report("k", "a.csv", "# RAPPORT D'INSPECTION\nshape: 10 × 3\n")
    store.store_inspection_report("k", "b.csv", "# RAPPORT D'INSPECTION\nshape: 99 × 7\n")
    store.store_inspection_report("other", "a.csv", "# RAPPORT D'INSPECTION\nshape: 1 × 1\n")

    assert "10 × 3" in store.read_inspection_report("k", "a.csv")
    assert "99 × 7" in store.read_inspection_report("k", "b.csv")
    assert set(store.list_inspection_reports("k")) == {"a.csv", "b.csv"}
    # Cross-session isolation
    assert "1 × 1" in store.read_inspection_report("other", "a.csv")
    assert store.list_inspection_reports("other") == ["a.csv"]


def test_inspection_report_overwrites_on_store():
    store = InMemorySessionStore()
    store.store_inspection_report("k", "a.csv", "v1")
    store.store_inspection_report("k", "a.csv", "v2")
    assert store.read_inspection_report("k", "a.csv") == "v2"


def test_evict_clears_inspection_reports():
    store = InMemorySessionStore()
    store.store_inspection_report("k", "a.csv", "report-body")
    store.touch("k")
    store.evict("k")
    assert store.read_inspection_report("k", "a.csv") is None
    assert store.list_inspection_reports("k") == []
