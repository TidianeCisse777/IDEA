"""Parcours déterministes utilisés par la démonstration NeoLabs."""

from __future__ import annotations

import pandas as pd

from tools.data_tools import make_tools
from tools.session_store import SessionStore


def test_prepare_neolabs_analysis_preserves_every_source_row_and_builds_graph_tables(
    tmp_path,
):
    abundance_path = tmp_path / "neolabs_abundance.csv"
    sample_path = tmp_path / "neolabs_sample.csv"
    pd.DataFrame(
        {
            "SAMPLE_ID": [1, 1, 2],
            "ANALYSIS_ID": [10, 10, 20],
            "TAXON_ID": ["Calanus", "Oithona", "Calanus"],
            "CLASS": ["Copepoda", "Copepoda", "Copepoda"],
            "ALL_STAGES_ABUND (ind./m3 depth vol.)": [10.0, 20.0, 5.0],
        }
    ).to_csv(abundance_path, index=False)
    pd.DataFrame(
        {
            "sample_id": [1, 3],
            "analysis_id": [10, pd.NA],
            "sampling_year": [2023, 2024],
            "deployment_datetime_start": [
                "2023-08-14 10:15:00",
                "2024-07-03 09:30:00",
            ],
            "deployment_datetime_end": [
                "2023-08-14 10:45:00",
                "2024-07-03 10:00:00",
            ],
            "cast_number": [87, 42],
            "sampling_platform": ["CCGS Amundsen", "Louis S. St-Laurent"],
            "deployment_comments": ["profil complet", "filet oblique"],
            "station_name": ["A", "B"],
            "min_sample_depth": [0.0, 10.0],
            "max_sample_depth": [10.0, 20.0],
            "latitude": [60.0, 61.0],
            "longitude": [-65.0, -64.0],
        }
    ).to_csv(sample_path, index=False)

    store = SessionStore(tmp_path / "sessions")
    prepare = next(
        tool
        for tool in make_tools("demo-neolabs", store=store)
        if tool.name == "prepare_neolabs_analysis"
    )

    text = prepare.invoke(
        {
            "abundance_path": str(abundance_path),
            "sample_path": str(sample_path),
        }
    )

    working = store.get("demo-neolabs:dataset:df_neolabs_working")["df"]
    samples = store.get("demo-neolabs:dataset:df_neolabs_samples")["df"]
    graph = store.get("demo-neolabs:dataset:df_neolabs_graph")["df"]
    coverage = store.get("demo-neolabs:dataset:df_neolabs_coverage")["df"]

    for variable in (
        "df_neolabs_working",
        "df_neolabs_samples",
        "df_neolabs_coverage",
        "df_neolabs_graph",
    ):
        entry = store.get(f"demo-neolabs:dataset:{variable}")
        meta = entry["meta"]
        assert len(meta["columns"]) == len(entry["df"].columns)
        assert meta["description"]
        assert meta["important_columns"]
        assert meta["column_descriptions"]

    assert len(working) == 4
    assert working["join_status"].value_counts().to_dict() == {
        "matched": 2,
        "abundance_without_sample": 1,
        "sample_without_abundance": 1,
    }
    assert len(samples) == 3
    matched = samples.loc[samples["join_status"].eq("matched")].iloc[0]
    assert matched["copepod_density_ind_m3"] == 30.0
    assert matched["density_status"] == "calculated"
    assert matched["deployment_datetime_start"] == "2023-08-14 10:15:00"
    assert matched["deployment_datetime_end"] == "2023-08-14 10:45:00"
    assert matched["cast_number"] == 87
    assert matched["sampling_platform"] == "CCGS Amundsen"
    assert matched["deployment_comments"] == "profil complet"
    sample_meta = store.get(
        "demo-neolabs:dataset:df_neolabs_samples"
    )["meta"]
    assert "density_status" in sample_meta["important_columns"]
    assert "hors dénominateur" in sample_meta["column_descriptions"]["density_status"]
    assert samples.loc[
        samples["join_status"].ne("matched"), "density_status"
    ].eq("not_applicable").all()
    assert graph[["sample_id", "copepod_density_ind_m3"]].to_dict("records") == [
        {"sample_id": 1, "copepod_density_ind_m3": 30.0}
    ]
    assert int(coverage["n_sample_analysis_rows"].sum()) == 3
    assert "3 lignes abondance" in text
    assert "2 lignes sample" in text
    assert "Densité sur les couples appariés : 1/1 calculable" in text
    assert "non appariés (hors dénominateur) : 2" in text
    assert "aucune ligne source écartée" in text.casefold()
    assert "join_status == 'matched'" in text
    assert "identifiants non nuls" in text
