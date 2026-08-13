"""Lifecycle contracts for derived DataFrames kept by one conversation."""

from __future__ import annotations

import pandas as pd

from tools.dataframe_cleanup import advance_dataframe_cleanup, hidden_dataframes
from tools.session_store import SessionStore


def _store_frame(
    store: SessionStore,
    thread_id: str,
    variable: str,
    *,
    source: str,
) -> None:
    store.set(
        f"{thread_id}:dataset:{variable}",
        pd.DataFrame({"value": [1]}),
        {"variable_name": variable, "source": source},
    )


def test_session_exposes_at_most_twenty_derived_dataframes(tmp_path):
    store = SessionStore(tmp_path)
    thread_id = "twenty-live-derived"
    _store_frame(
        store,
        thread_id,
        "df_file_source",
        source="file:/uploads/source.tsv",
    )
    for index in range(25):
        _store_frame(
            store,
            thread_id,
            f"df_derived_{index:02d}",
            source="analysis:explicit-derived",
        )

    advance_dataframe_cleanup(store, thread_id, marker="turn-1")

    hidden = hidden_dataframes(store, thread_id)
    visible_derived = {
        f"df_derived_{index:02d}" for index in range(25)
    } - hidden
    assert len(visible_derived) == 20
    assert "df_file_source" not in hidden


def test_file_and_export_dataframes_remain_permanent(tmp_path):
    store = SessionStore(tmp_path)
    thread_id = "permanent-files-and-exports"
    permanent_sources = {
        "df_uploaded_file": "file:/uploads/source.tsv",
        "df_ecotaxa_export": "ecotaxa_export_campaign",
        "df_ecopart_export": "ecopart:14844",
        "df_amundsen_export": "amundsen_profiles",
    }
    for variable, source in permanent_sources.items():
        _store_frame(store, thread_id, variable, source=source)
    for index in range(25):
        _store_frame(
            store,
            thread_id,
            f"df_derived_{index:02d}",
            source="analysis:explicit-derived",
        )

    for turn in range(1, 26):
        advance_dataframe_cleanup(
            store,
            thread_id,
            marker=f"turn-{turn}",
        )

    hidden = hidden_dataframes(store, thread_id)
    for variable in permanent_sources:
        assert variable not in hidden
        assert store.get(f"{thread_id}:dataset:{variable}") is not None


def test_enrichment_dataframes_remain_permanent(tmp_path):
    store = SessionStore(tmp_path)
    thread_id = "permanent-enrichments"
    permanent_enrichments = {
        "df_amundsen_enriched": "amundsen_enrichment",
        "df_bio_oracle_enriched": "bio_oracle_enrichment",
        "df_ogsl_enriched": "ogsl_enrichment",
        "df_ecopart_enriched": "join:ecotaxa+ecopart",
    }
    for variable, source in permanent_enrichments.items():
        _store_frame(store, thread_id, variable, source=source)
    for index in range(25):
        _store_frame(
            store,
            thread_id,
            f"df_derived_{index:02d}",
            source="analysis:explicit-derived",
        )

    for turn in range(1, 26):
        advance_dataframe_cleanup(
            store,
            thread_id,
            marker=f"turn-{turn}",
        )

    hidden = hidden_dataframes(store, thread_id)
    for variable in permanent_enrichments:
        assert variable not in hidden
        assert store.get(f"{thread_id}:dataset:{variable}") is not None


def test_current_reference_revives_capacity_hidden_dataframe(tmp_path):
    store = SessionStore(tmp_path)
    thread_id = "revive-capacity-hidden"
    for index in range(21):
        _store_frame(
            store,
            thread_id,
            f"df_derived_{index:02d}",
            source="analysis:explicit-derived",
        )
    advance_dataframe_cleanup(store, thread_id, marker="turn-1")
    hidden_on_first_turn = hidden_dataframes(store, thread_id)
    assert len(hidden_on_first_turn) == 1
    hidden_name = next(iter(hidden_on_first_turn))

    advance_dataframe_cleanup(
        store,
        thread_id,
        marker="turn-2",
        referenced_text=f"Vérifie `{hidden_name}`.",
    )

    hidden_on_second_turn = hidden_dataframes(store, thread_id)
    assert hidden_name not in hidden_on_second_turn
    assert len(hidden_on_second_turn) == 1


def test_cleanup_metrics_explain_the_twenty_dataframe_policy(tmp_path):
    from tools.dataframe_cleanup import dataframe_cleanup_metrics

    store = SessionStore(tmp_path)
    thread_id = "cleanup-harness-metrics"
    for index in range(25):
        _store_frame(
            store,
            thread_id,
            f"df_derived_{index:02d}",
            source="analysis:explicit-derived",
        )
    advance_dataframe_cleanup(store, thread_id, marker="turn-1")

    assert dataframe_cleanup_metrics(store, thread_id) == {
        "max_live_derived_dataframes": 20,
        "derived_dataframes_total": 25,
        "derived_dataframes_visible": 20,
        "derived_dataframes_hidden": 5,
        "derived_dataframes_capacity_hidden": 5,
        "derived_dataframes_age_hidden": 0,
    }
