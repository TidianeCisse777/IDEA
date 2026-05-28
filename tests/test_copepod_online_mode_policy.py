"""Tests for the Copepod Online Mode policy contract."""
from __future__ import annotations

import pytest

from core.session_store import InMemorySessionStore

pytestmark = pytest.mark.workflow


def test_online_mode_defaults_to_off_for_new_session():
    store = InMemorySessionStore()

    assert store.get_online_mode("u1:s1:copepod") is False


def test_online_mode_can_be_enabled_and_read_back():
    store = InMemorySessionStore()

    store.set_online_mode("u1:s1:copepod", True)

    assert store.get_online_mode("u1:s1:copepod") is True


def test_online_mode_is_isolated_per_session_key():
    store = InMemorySessionStore()

    store.set_online_mode("u1:s1:copepod", True)

    assert store.get_online_mode("u1:s2:copepod") is False


def test_online_mode_is_cleared_on_evict():
    store = InMemorySessionStore()

    store.set_online_mode("u1:s1:copepod", True)
    store.evict("u1:s1:copepod")

    assert store.get_online_mode("u1:s1:copepod") is False
