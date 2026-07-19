"""Chaîne complète filet↔UVP bout-à-bout, sur densités réelles des deux côtés.

Aucune paire synchrone n'existe dans les données démo (filet 2014-2018 vs UVP
2024), donc ce test ne prétend PAS à une comparaison scientifique cast-à-cast :
il prouve que la chaîne de calcul du skill `net_uvp_abundance_comparison`
(Step 2→4) produit un tableau apparié cohérent à partir de vraies densités —
densité copépode filet réelle (contrat NeoLabs) et densité copépode UVP réelle
(m5_cop_dens du pipeline UVP_metrics_for_MCA).
"""

from pathlib import Path

import pandas as pd
import pytest

from core.neolabs_abundance import neolabs_copepod_density
from core.net_uvp_comparison import compare_paired_density, to_ind_per_m3

_NET_FILE = Path("data/demo/neolabs_taxonomy_2014_2020.tsv")
_UVP_METRICS = Path("UVP_metrics_for_MCA/final_datasets/uvp_metrics_Hawke_Channel_2024.csv")


@pytest.mark.skipif(
    not (_NET_FILE.exists() and _UVP_METRICS.exists()),
    reason="demo net file or UVP metrics file absent",
)
def test_full_net_uvp_comparison_produces_real_paired_table():
    # --- Step 1 : densité copépode filet réelle (ind./m³), contrat imposé ---
    net = pd.read_csv(_NET_FILE, sep="\t", low_memory=False)
    net_density = neolabs_copepod_density(net)
    assert (net_density["copepod_density_ind_m3"] >= 0).all()

    # --- Step 2 : densité copépode UVP réelle (m5_cop_dens, ind./L) ---
    uvp = pd.read_csv(_UVP_METRICS)
    assert "m5_cop_dens" in uvp.columns

    # --- Step 3 : alignement d'unités (ind./L → ind./m³) ---
    uvp = uvp.assign(
        uvp_ind_m3=to_ind_per_m3(uvp["m5_cop_dens"], from_unit="ind_per_L")
    )
    # conversion vérifiable : ×1000
    assert uvp["uvp_ind_m3"].iloc[0] == pytest.approx(uvp["m5_cop_dens"].iloc[0] * 1000)

    # correspondance (produite en prod par find_uvp_matches_for_net_table) :
    # on relie quelques stations filet réelles à des samples UVP réels.
    net_stations = net_density["STATION_NAME"].astype(str).tolist()[:5]
    uvp_samples = uvp["sample_id"].tolist()[:5]
    matches = pd.DataFrame(
        {
            "station": net_stations,
            "uvp_sample_id": uvp_samples,
            "distance_km": [0.1, 0.2, 0.3, 0.4, 0.5],
            "time_gap_days": [2900.0] * 5,
            "match_status": ["spatial_only"] * 5,
        }
    )

    # --- bridge net (station) ↔ UVP (sample) via la correspondance ---
    paired = (
        matches.merge(
            net_density.assign(STATION_NAME=net_density["STATION_NAME"].astype(str))[
                ["STATION_NAME", "copepod_density_ind_m3"]
            ],
            left_on="station",
            right_on="STATION_NAME",
            how="inner",
        )
        .merge(uvp[["sample_id", "uvp_ind_m3"]], left_on="uvp_sample_id", right_on="sample_id", how="inner")
        .rename(columns={"copepod_density_ind_m3": "net_ind_m3"})
    )
    assert len(paired) == 5

    # --- Step 4 : comparaison appariée, contrat déterministe ---
    result = compare_paired_density(paired, net_col="net_ind_m3", uvp_col="uvp_ind_m3")

    for col in (
        "station",
        "net_ind_m3",
        "uvp_ind_m3",
        "abundance_delta_ind_m3",
        "abundance_ratio",
        "abundance_log2_ratio",
        "time_gap_days",
        "match_status",
    ):
        assert col in result.columns

    # la maths tient sur les vraies valeurs
    row = result.iloc[0]
    assert row["abundance_delta_ind_m3"] == pytest.approx(
        row["uvp_ind_m3"] - row["net_ind_m3"]
    )
    assert row["abundance_ratio"] == pytest.approx(row["uvp_ind_m3"] / row["net_ind_m3"])
    # les deux côtés portent des nombres réels non nuls
    assert result["net_ind_m3"].gt(0).all()
    assert result["uvp_ind_m3"].gt(0).all()
