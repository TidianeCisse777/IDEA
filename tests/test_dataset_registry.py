"""TDD — registre commun des DataFrames téléchargés."""

import pandas as pd


def test_dataset_variable_name_normalizes_source_parts():
    from tools.dataset_registry import dataset_variable_name

    assert dataset_variable_name("ecotaxa", 1165) == "df_ecotaxa_1165"
    assert (
        dataset_variable_name("amundsen", "amundsen12713", "BRK-15", "cast", 7)
        == "df_amundsen_amundsen12713_brk_15_cast_7"
    )
    assert (
        dataset_variable_name("bio_oracle", "thetao", "SSP245", "depthsurf", 50.2, -65.8)
        == "df_bio_oracle_thetao_ssp245_depthsurf_50_2_m65_8"
    )
    assert dataset_variable_name("file", "Stations 2024.tsv") == "df_file_stations_2024_tsv"


def test_store_dataset_preserves_stable_entry_and_updates_alias(tmp_path):
    from tools.dataset_registry import store_dataset
    from tools.session_store import SessionStore

    store = SessionStore(storage_dir=tmp_path / "sessions")
    df = pd.DataFrame({"value": [1, 2]})

    store_dataset(
        store,
        "thread-1",
        df,
        variable_name="df_ecotaxa_1165",
        meta={"source": "ecotaxa:1165"},
        latest_alias="ecotaxa",
    )

    assert store.get("thread-1")["df"].equals(df)
    assert store.get("thread-1:ecotaxa")["df"].equals(df)
    stable = store.get("thread-1:dataset:df_ecotaxa_1165")
    assert stable["df"].equals(df)
    assert stable["meta"]["variable_name"] == "df_ecotaxa_1165"


def test_enrichment_source_note_uses_explicit_variable_and_lists_prior_enrichments(tmp_path):
    from tools.dataset_registry import enrichment_source_note
    from tools.session_store import SessionStore

    store = SessionStore(storage_dir=tmp_path / "sessions")
    # A table already enriched with EcoPart, about to be enriched again.
    df = pd.DataFrame({
        "obj_orig_id": ["ips_007_1"],
        "ecopart_Sampled volume [L]": [29.7],
        "ecopart_temperature [degc]": [-1.1],
    })

    note = enrichment_source_note(store, "t", df, "df_ecotaxa_ecopart_105")

    assert "df_ecotaxa_ecopart_105" in note
    assert "2 ecopart_*" in note


def test_enrichment_source_note_falls_back_to_active_df_variable(tmp_path):
    from tools.dataset_registry import enrichment_source_note, store_dataset
    from tools.session_store import SessionStore

    store = SessionStore(storage_dir=tmp_path / "sessions")
    df = pd.DataFrame({"latitude": [48.5], "longitude": [-68.1]})
    store_dataset(store, "t", df, variable_name="df_file_filet_2018",
                  meta={"source": "file:filet"}, latest_alias=None)

    # source_variable=None → name read back from the active session metadata.
    note = enrichment_source_note(store, "t", df, None)

    assert "df_file_filet_2018" in note
    # No enrichment columns yet → no "déjà présent" clause.
    assert "déjà présent" not in note

