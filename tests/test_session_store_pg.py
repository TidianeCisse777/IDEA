"""Tests TDD pour SessionStorePG.

Nécessite un PostgreSQL accessible. Skippé si SESSION_STORE_TEST_DATABASE_URL absent.
Lancer avec :
    SESSION_STORE_TEST_DATABASE_URL=postgresql://copepod:copepod_dev@localhost:5433/copepod_sessions pytest tests/test_session_store_pg.py -v
"""
from __future__ import annotations

import os
import pytest
import pandas as pd

_TEST_DSN = os.getenv("SESSION_STORE_TEST_DATABASE_URL", "")
_skip = pytest.mark.skipif(not _TEST_DSN, reason="SESSION_STORE_TEST_DATABASE_URL not set")

_PREFIX = "pytest_session_store_"


def _fresh_store(tmp_path):
    from tools.session_store_pg import SessionStorePG
    from sqlalchemy import create_engine, text
    store = SessionStorePG(_TEST_DSN, storage_dir=tmp_path / "pkl")
    with create_engine(_TEST_DSN).begin() as conn:
        conn.execute(text("DELETE FROM sessions WHERE session_key LIKE :p"), {"p": _PREFIX + "%"})
    return store


def _key(suffix: str) -> str:
    return f"{_PREFIX}{suffix}"


def test_clear_conversation_deletes_literal_family_in_one_transaction(tmp_path):
    from sqlalchemy import create_engine, text
    from tools.session_store_pg import SessionStorePG

    engine = create_engine(f"sqlite:///{tmp_path / 'sessions.sqlite'}")
    exact_path = tmp_path / "exact.pkl"
    child_path = tmp_path / "child.pkl"
    neighbor_path = tmp_path / "neighbor.pkl"
    for path in (exact_path, child_path, neighbor_path):
        pd.DataFrame({"value": [1]}).to_pickle(path)

    rows = [
        ("thread_%", str(exact_path)),
        ("thread_%:dataset:df", str(child_path)),
        ("thread_%other", str(neighbor_path)),
    ]
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE sessions (session_key TEXT PRIMARY KEY, storage_path TEXT)"
        ))
        for key, path in rows:
            conn.execute(
                text("INSERT INTO sessions VALUES (:key, :path)"),
                {"key": key, "path": path},
            )

    store = object.__new__(SessionStorePG)
    store._engine = engine
    store._storage_dir = tmp_path
    store._cache = {key: {"df": None, "meta": {}} for key, _ in rows}

    store.clear_conversation("thread_%")

    with engine.connect() as conn:
        remaining_keys = list(conn.execute(
            text("SELECT session_key FROM sessions ORDER BY session_key")
        ).scalars())

    assert remaining_keys == ["thread_%other"]
    assert not exact_path.exists()
    assert not child_path.exists()
    assert neighbor_path.exists()
    assert "thread_%" not in store._cache
    assert "thread_%:dataset:df" not in store._cache
    assert "thread_%other" in store._cache


@_skip
def test_clear_conversation_real_postgres_preserves_literal_neighbor(tmp_path):
    from tools.session_store_pg import SessionStorePG

    store = _fresh_store(tmp_path)
    root = _key("contract_%_root")
    child = f"{root}:dataset"
    neighbor = f"{root}-neighbor"
    sessions = {
        root: (pd.DataFrame({"value": [1]}), {"owner": "exact"}),
        child: (pd.DataFrame({"value": [2]}), {"owner": "child"}),
        neighbor: (pd.DataFrame({"value": [3]}), {"owner": "neighbor"}),
    }
    try:
        for key, (df, meta) in sessions.items():
            store.set(key, df, meta)
        paths = {key: store._pkl_path(key) for key in sessions}

        store.clear_conversation(root)

        assert root not in store._cache
        assert child not in store._cache
        assert neighbor in store._cache
        assert not paths[root].exists()
        assert not paths[child].exists()
        assert paths[neighbor].exists()

        restarted = SessionStorePG(_TEST_DSN, storage_dir=tmp_path / "pkl")
        assert restarted.get(root) is None
        assert restarted.get(child) is None
        persisted_neighbor = restarted.get(neighbor)
        assert persisted_neighbor is not None
        assert persisted_neighbor["df"].equals(sessions[neighbor][0])
        assert persisted_neighbor["meta"] == sessions[neighbor][1]
    finally:
        for key in sessions:
            store.clear(key)


@_skip
def test_set_get_roundtrip(tmp_path):
    store = _fresh_store(tmp_path)
    df = pd.DataFrame({"profile_id": ["ips_001"], "depth": [12.5]})
    meta = {"source": "test_source", "n_rows": 1}
    store.set(_key("abc"), df, meta)

    session = store.get(_key("abc"))
    assert session is not None
    assert session["meta"] == meta
    assert session["df"].equals(df)


@_skip
def test_get_returns_none_for_unknown_key(tmp_path):
    store = _fresh_store(tmp_path)
    assert store.get(_key("does_not_exist")) is None


@_skip
def test_persists_across_instances(tmp_path):
    from tools.session_store_pg import SessionStorePG
    store1 = _fresh_store(tmp_path)
    df = pd.DataFrame({"col": [1, 2]})
    store1.set(_key("persist"), df, {"source": "amundsen"})

    store2 = SessionStorePG(_TEST_DSN, storage_dir=tmp_path / "pkl")
    session = store2.get(_key("persist"))
    assert session is not None
    assert session["df"].equals(df)
    assert session["meta"]["source"] == "amundsen"


@_skip
def test_set_without_dataframe(tmp_path):
    store = _fresh_store(tmp_path)
    store.set(_key("no_df"), None, {"status": "empty"})

    session = store.get(_key("no_df"))
    assert session is not None
    assert session["df"] is None
    assert session["meta"]["status"] == "empty"


@_skip
def test_update_meta(tmp_path):
    store = _fresh_store(tmp_path)
    store.set(_key("upd"), None, {"source": "ctd", "n_rows": 10})
    store.update_meta(_key("upd"), {"n_rows": 99, "extra": True})

    session = store.get(_key("upd"))
    assert session["meta"]["source"] == "ctd"
    assert session["meta"]["n_rows"] == 99
    assert session["meta"]["extra"] is True


@_skip
def test_has(tmp_path):
    store = _fresh_store(tmp_path)
    assert not store.has(_key("new_key"))
    store.set(_key("new_key"), None, {})
    assert store.has(_key("new_key"))


@_skip
def test_clear(tmp_path):
    store = _fresh_store(tmp_path)
    df = pd.DataFrame({"x": [1]})
    store.set(_key("to_clear"), df, {"source": "bio_oracle"})
    pkl = store._pkl_path(_key("to_clear"))
    assert pkl.exists()

    store.clear(_key("to_clear"))
    assert not store.has(_key("to_clear"))
    assert not pkl.exists()


@_skip
def test_keys_prefix_filter(tmp_path):
    store = _fresh_store(tmp_path)
    store.set(_key("ecopart:105"), None, {})
    store.set(_key("ecopart:42"), None, {})
    store.set(_key("ecotaxa:1165"), None, {})

    prefix_keys = store.keys(_key("ecopart:"))
    assert sorted(prefix_keys) == [_key("ecopart:105"), _key("ecopart:42")]


@_skip
def test_keys_all(tmp_path):
    store = _fresh_store(tmp_path)
    store.set(_key("k1"), None, {})
    store.set(_key("k2"), None, {})

    all_keys = store.keys()
    assert _key("k1") in all_keys
    assert _key("k2") in all_keys


@_skip
def test_get_uses_in_memory_cache(tmp_path, monkeypatch):
    """Second get() on same key must not hit the DB (uses in-memory cache)."""
    store = _fresh_store(tmp_path)
    df = pd.DataFrame({"v": [42]})
    store.set(_key("cached"), df, {})

    call_count = 0
    original_connect = __import__("psycopg").connect

    def counting_connect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_connect(*args, **kwargs)

    monkeypatch.setattr("psycopg.connect", counting_connect)
    store.get(_key("cached"))
    assert call_count == 0, "in-memory cache should prevent DB access"
