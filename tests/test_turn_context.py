"""Typed per-turn state reconstruction (harness step 5)."""

import pandas as pd

from tools.dataset_registry import store_dataset
from tools.session_store import SessionStore


def _seed(tmp_path):
    store = SessionStore(tmp_path)
    thread_id = "tc"
    base = pd.DataFrame({
        "station": [1, 2, 3],
        "latitude": [60.0, 61.0, 74.0],
        "longitude": [-60.0, -61.0, -70.0],
    })
    store_dataset(
        store, thread_id, base,
        variable_name="df_file_base",
        meta={"source": "file:/d/base.tsv", "path": "/d/base.tsv", "n_rows": 3, "n_cols": 3},
        is_loaded_file=True,
    )
    store_dataset(
        store, thread_id, base.iloc[2:],
        variable_name="df_in_baffin_base",
        meta={"source": "filter_by_zone:baffin-bay", "zone_canonical": "baffin-bay", "n_rows": 1},
        latest_alias="df_in_baffin_base",
    )
    from tools.source_scope import activate_file_source

    activate_file_source(store, thread_id, origin_user_text="/d/base.tsv")
    return store, thread_id


def test_build_turn_context_bundles_state(tmp_path):
    from tools.turn_context import build_turn_context

    store, thread_id = _seed(tmp_path)
    msgs = [{"role": "user", "content": "carte des stations"}]
    ctx = build_turn_context(store, thread_id, msgs)

    assert ctx.file_loaded is True
    assert ctx.active_variable == "df_in_baffin_base"
    assert ("df_in_baffin_base", "baffin-bay", "1") in ctx.derived_zone_subsets
    assert ctx.authorized_sources == ("file",)
    assert ctx.primary_source == "file"
    assert "ACTIVE SOURCE SCOPE" in ctx.capsule
    assert "df_in_baffin_base" in ctx.capsule


def test_build_turn_context_no_file(tmp_path):
    from tools.turn_context import build_turn_context

    store = SessionStore(tmp_path)
    ctx = build_turn_context(store, "empty", [{"role": "user", "content": "salut"}])
    assert ctx.file_loaded is False
    assert ctx.active_variable is None
    assert ctx.derived_zone_subsets == ()
    assert ctx.capsule == ""
