"""Regression tests for source anchors versus derived analysis tables."""

from __future__ import annotations

import pandas as pd

from tools.data_tools import make_tools
from tools.dataset_registry import ECOTAXA_ECOPART, store_dataset
from tools.session_store import SessionStore


def test_persisting_four_column_summary_does_not_replace_wide_ecopart_anchor(
    tmp_path,
):
    """The Baie d'Ungava 933×217 join remains the implicit source anchor."""
    thread_id = "ungava-anchor-identity"
    store = SessionStore(tmp_path / "sessions")
    filler = {
        f"source_column_{index:03d}": range(933)
        for index in range(213)
    }
    joined = pd.DataFrame(
        {
            "profile_id": [
                "20241022-155403" if index < 450 else "20241022-190946"
                for index in range(933)
            ],
            "depth_bin": [float(index % 18) * 5 + 2.5 for index in range(933)],
            "object_id": [f"obj-{index}" for index in range(933)],
            "ecopart_Sampled volume [L]": [64.0] * 933,
            **filler,
        }
    )
    assert joined.shape == (933, 217)
    store_dataset(
        store,
        thread_id,
        joined,
        variable_name="df_ecotaxa_ecopart_1063",
        latest_alias=ECOTAXA_ECOPART,
        meta={
            "source": "join:ecotaxa+ecopart:1063",
            "grain": "one row per EcoTaxa object or sampled zero bin",
        },
    )
    tools = {tool.name: tool for tool in make_tools(thread_id, store=store)}

    _content, derived = tools["run_pandas"].invoke(
        {
            "code": (
                "result = (df_ecotaxa_ecopart_1063.groupby('profile_id', "
                "as_index=False).agg(object_count=('object_id', 'count'), "
                "sampled_volume_L=('ecopart_Sampled volume [L]', 'first'))); "
                "result['abundance_ind_m3'] = "
                "result['object_count'] / (result['sampled_volume_L'] / 1000)"
            ),
            "persist_as": "df_derived_copepoda_abundance_ind_m3_v2",
            "description": "Résumé d'abondance par profil.",
            "grain": "une ligne par profil",
            "filters": {"taxon": "Copepoda"},
        }
    )
    assert derived["status"] == "success"
    assert derived["metrics"]["columns"] == 4

    inspection, artifact = tools["run_pandas"].invoke(
        {
            "code": (
                "result = {'active_shape': df.shape, "
                "'anchor_shape': df_ecotaxa_ecopart_1063.shape, "
                "'derived_shape': "
                "df_derived_copepoda_abundance_ind_m3_v2.shape}"
            )
        }
    )

    assert artifact["status"] == "success"
    assert "'active_shape': (933, 217)" in inspection
    assert "'anchor_shape': (933, 217)" in inspection
    assert "'derived_shape': (2, 4)" in inspection


def test_executor_refreshes_a_named_anchor_after_same_object_changes(tmp_path):
    """The hot worker cannot retain a stale schema for a changed store payload."""
    thread_id = "anchor-worker-refresh"
    store = SessionStore(tmp_path / "sessions")
    anchor = pd.DataFrame({"profile_id": ["P-01"], "object_id": ["obj-1"]})
    store_dataset(
        store,
        thread_id,
        anchor,
        variable_name="df_ecotaxa_ecopart_1063",
        latest_alias=ECOTAXA_ECOPART,
        meta={"source": "join:ecotaxa+ecopart:1063"},
    )
    tools = {tool.name: tool for tool in make_tools(thread_id, store=store)}

    first, _artifact = tools["run_pandas"].invoke(
        {"code": "result = df_ecotaxa_ecopart_1063.shape"}
    )
    assert first == "(1, 2)"

    # SessionStore still owns the same Python object. A pure id()-based worker
    # cache misses this schema change and serves the old two-column payload.
    anchor["ecopart_Sampled volume [L]"] = 64.0
    anchor["depth_bin"] = 2.5

    refreshed, artifact = tools["run_pandas"].invoke(
        {"code": "result = df_ecotaxa_ecopart_1063.shape"}
    )

    assert artifact["status"] == "success"
    assert refreshed == "(1, 4)"
