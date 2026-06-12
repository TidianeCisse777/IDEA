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

