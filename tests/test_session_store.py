"""TDD — persistance de SessionStore."""

import json
import re

import pandas as pd
import pytest


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


@pytest.mark.parametrize(
    "insertion_order",
    [
        ("thread-abc:dataset", "thread-abc_dataset"),
        ("thread-abc_dataset", "thread-abc:dataset"),
    ],
)
def test_clear_conversation_preserves_colliding_neighbor_after_restart(
    tmp_path,
    insertion_order,
):
    from tools.session_store import SessionStore

    store_dir = tmp_path / "sessions"
    store = SessionStore(storage_dir=store_dir)
    sessions = {
        "thread-abc:dataset": (
            pd.DataFrame({"value": [1], "owner": ["child"]}),
            {"owner": "child"},
        ),
        "thread-abc_dataset": (
            pd.DataFrame({"value": [2], "owner": ["neighbor"]}),
            {"owner": "neighbor"},
        ),
    }
    for key in insertion_order:
        df, meta = sessions[key]
        store.set(key, df, meta)

    store.clear_conversation("thread-abc")

    reloaded = SessionStore(storage_dir=store_dir)
    assert reloaded.get("thread-abc:dataset") is None
    neighbor = reloaded.get("thread-abc_dataset")
    assert neighbor is not None
    assert neighbor["df"].equals(sessions["thread-abc_dataset"][0])
    assert neighbor["meta"] == sessions["thread-abc_dataset"][1]


def test_loads_and_migrates_matching_legacy_sanitized_entry(tmp_path):
    from tools.session_store import SessionStore

    store_dir = tmp_path / "sessions"
    store_dir.mkdir()
    key = "thread-legacy:dataset"
    legacy_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", key.strip())
    legacy_data_path = store_dir / f"{legacy_stem}.pkl"
    legacy_meta_path = store_dir / f"{legacy_stem}.json"
    expected_df = pd.DataFrame({"value": [7], "owner": ["legacy"]})
    expected_meta = {"owner": "legacy"}
    expected_df.to_pickle(legacy_data_path)
    legacy_meta_path.write_text(
        json.dumps({"session_key": key, "meta": expected_meta}),
        encoding="utf-8",
    )

    reloaded = SessionStore(storage_dir=store_dir)
    assert reloaded.keys() == [key]
    session = reloaded.get(key)

    assert session is not None
    assert session["df"].equals(expected_df)
    assert session["meta"] == expected_meta
    assert reloaded._data_path(key) != legacy_data_path
    assert reloaded._meta_path(key) != legacy_meta_path
    assert reloaded._data_path(key).exists()
    assert reloaded._meta_path(key).exists()
    assert not legacy_data_path.exists()
    assert not legacy_meta_path.exists()
    assert reloaded.keys() == [key]


def test_legacy_collision_is_not_loaded_or_cleared_for_another_key(tmp_path):
    from tools.session_store import SessionStore

    store_dir = tmp_path / "sessions"
    store_dir.mkdir()
    requested_key = "thread-abc:dataset"
    stored_key = "thread-abc_dataset"
    legacy_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", requested_key.strip())
    legacy_data_path = store_dir / f"{legacy_stem}.pkl"
    legacy_meta_path = store_dir / f"{legacy_stem}.json"
    expected_df = pd.DataFrame({"owner": ["neighbor"]})
    expected_df.to_pickle(legacy_data_path)
    legacy_meta_path.write_text(
        json.dumps({"session_key": stored_key, "meta": {"owner": "neighbor"}}),
        encoding="utf-8",
    )
    store = SessionStore(storage_dir=store_dir)

    assert store.get(requested_key) is None
    store.clear(requested_key)

    assert legacy_data_path.exists()
    assert legacy_meta_path.exists()
    neighbor = SessionStore(storage_dir=store_dir).get(stored_key)
    assert neighbor is not None
    assert neighbor["df"].equals(expected_df)


def test_long_key_can_be_reloaded_and_cleared_without_legacy_path_error(tmp_path):
    from tools.session_store import SessionStore

    store_dir = tmp_path / "sessions"
    key = "thread-" + ("x" * 993)
    expected_df = pd.DataFrame({"value": [1]})
    SessionStore(storage_dir=store_dir).set(key, expected_df, {"owner": "long"})

    reloaded = SessionStore(storage_dir=store_dir)
    session = reloaded.get(key)
    assert session is not None
    assert session["df"].equals(expected_df)
    reloaded.clear(key)

    assert reloaded.get(key) is None
    assert reloaded.has(key) is False
