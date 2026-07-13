"""TDD — persistance de SessionStore."""

import pandas as pd


def test_session_store_persists_dataframe_and_metadata(tmp_path):
    from tools.session_store import SessionStore

    store_dir = tmp_path / "sessions"
    store = SessionStore(storage_dir=store_dir)

    df = pd.DataFrame({"profile_id": ["ips_001"], "depth": [12.5]})
    meta = {"source": "bio_oracle:SSP245", "n_rows": 1}

    store.set("thread-abc", df, meta)

    reloaded = SessionStore(storage_dir=store_dir)
    session = reloaded.get("thread-abc")

    assert session is not None
    assert session["meta"] == meta
    assert session["df"].equals(df)


def test_session_store_clear_removes_persisted_state(tmp_path):
    from tools.session_store import SessionStore

    store_dir = tmp_path / "sessions"
    store = SessionStore(storage_dir=store_dir)

    df = pd.DataFrame({"profile_id": ["ips_001"], "depth": [12.5]})
    store.set("thread-xyz", df, {"source": "amundsen"})

    store.clear("thread-xyz")

    assert store.get("thread-xyz") is None
    assert not any(store_dir.glob("thread-xyz*"))


def test_session_store_lists_keys_by_prefix(tmp_path):
    from tools.session_store import SessionStore

    store = SessionStore(storage_dir=tmp_path / "sessions")
    df = pd.DataFrame({"value": [1]})
    store.set("thread:ecopart:105", df, {"source": "ecopart:105"})
    store.set("thread:ecopart:42", df, {"source": "ecopart:42"})
    store.set("thread:ecotaxa:1165", df, {"source": "ecotaxa:1165"})

    assert store.keys("thread:ecopart:") == [
        "thread:ecopart:105",
        "thread:ecopart:42",
    ]


def test_session_store_lists_persisted_keys_after_restart(tmp_path):
    from tools.session_store import SessionStore

    store_dir = tmp_path / "sessions"
    store = SessionStore(storage_dir=store_dir)
    df = pd.DataFrame({"value": [1]})
    store.set("thread:ecopart:105", df, {"source": "ecopart:105"})
    store.set("thread:ecopart:42", df, {"source": "ecopart:42"})

    reloaded = SessionStore(storage_dir=store_dir)

    assert reloaded.keys("thread:ecopart:") == [
        "thread:ecopart:105",
        "thread:ecopart:42",
    ]


def test_clear_conversation_removes_exact_and_colon_family_only(tmp_path):
    from tools.session_store import SessionStore

    store = SessionStore(storage_dir=tmp_path / "sessions")
    df = pd.DataFrame({"value": [1]})
    for key in (
        "thread-abc",
        "thread-abc:ecotaxa",
        "thread-abc:dataset:df_ecotaxa",
        "thread-abc-other",
        "thread-abcd:dataset:df_neighbor",
    ):
        store.set(key, df, {"key": key})

    store.clear_conversation("thread-abc")

    assert store.get("thread-abc") is None
    assert store.keys("thread-abc:") == []
    assert store.get("thread-abc-other") is not None
    assert store.get("thread-abcd:dataset:df_neighbor") is not None
