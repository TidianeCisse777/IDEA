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
