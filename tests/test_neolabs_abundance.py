"""Contrat déterministe densité copépode NeoLabs."""

import pandas as pd
import pytest

from core.neolabs_abundance import (
    NEOLABS_COPEPOD_METHOD_VERSION,
    neolabs_copepod_density,
    resolve_neolabs_stage_abundance,
)

_ABUND = "Total abundance (ind./m3 depth vol)"


def test_filters_copepods_and_aggregates_per_station():
    df = pd.DataFrame({
        "SAMPLE_ID": [1, 1, 1, 2, 2],
        "STATION_NAME": ["A", "A", "A", "A", "A"],
        "CLASS": ["Copepoda", "Copepoda", "Bivalvia", "Copepoda", "Hydrozoa"],
        "latitude": [60.0] * 5,
        "longitude": [-65.0] * 5,
        _ABUND: [10.0, 5.0, 999.0, 20.0, 999.0],
    })

    out = neolabs_copepod_density(df)

    row = out[out["STATION_NAME"] == "A"].iloc[0]
    # sample1 = 10+5 = 15 (999 Bivalvia exclu) ; sample2 = 20 ; station = moyenne 17.5
    assert row["copepod_density_ind_m3"] == 17.5
    assert row["n_samples"] == 2
    assert out["method_version"].eq(NEOLABS_COPEPOD_METHOD_VERSION).all()


def test_excludes_non_copepods_entirely():
    df = pd.DataFrame({
        "SAMPLE_ID": [1, 1],
        "STATION_NAME": ["B", "B"],
        "CLASS": ["Bivalvia", "Hydrozoa"],
        _ABUND: [100.0, 200.0],
    })
    with pytest.raises(ValueError, match="copépodes"):
        neolabs_copepod_density(df)


def test_tolerates_residual_nan_abundance():
    df = pd.DataFrame({
        "SAMPLE_ID": [1, 1],
        "STATION_NAME": ["A", "A"],
        "CLASS": ["Copepoda", "Copepoda"],
        _ABUND: [12.0, None],  # NaN ignoré par la somme
    })
    out = neolabs_copepod_density(df)
    assert out.iloc[0]["copepod_density_ind_m3"] == 12.0


def test_rejects_missing_class_column():
    df = pd.DataFrame({
        "SAMPLE_ID": [1],
        "STATION_NAME": ["A"],
        _ABUND: [10.0],
    })
    with pytest.raises(ValueError, match="CLASS"):
        neolabs_copepod_density(df)


def test_resolve_late_stages_excludes_small_stages_from_selected_abundance():
    df = pd.DataFrame({
        "C1_ABUND (ind./m3 depth vol.)": [100.0],
        "C4_ABUND (ind./m3 depth vol.)": [4.0],
        "C5_ABUND (ind./m3 depth vol.)": [5.0],
        "M_ABUND (ind./m3 depth vol.)": [2.0],
        "F_ABUND (ind./m3 depth vol.)": [3.0],
        "ALL_STAGES_ABUND (ind./m3 depth vol.)": [114.0],
    })

    selected, stages = resolve_neolabs_stage_abundance(
        df, stages="late_stages"
    )

    assert stages == ["C4", "C5", "M", "F"]
    assert selected["_selected_net_abundance_ind_m3"].tolist() == [14.0]


def test_resolve_stage_selection_accepts_natural_custom_separators_and_case():
    df = pd.DataFrame({
        "C4_ABUND (ind./m3 depth vol.)": [4.0],
        "C5_ABUND (ind./m3 depth vol.)": [5.0],
        "M_ABUND (ind./m3 depth vol.)": [2.0],
        "F_ABUND (ind./m3 depth vol.)": [3.0],
    })

    selected, stages = resolve_neolabs_stage_abundance(
        df, stages="c4 + c5; m, f"
    )

    assert stages == ["C4", "C5", "M", "F"]
    assert selected["_selected_net_abundance_ind_m3"].tolist() == [14.0]


def test_density_accepts_natural_stage_selection_syntax():
    df = pd.DataFrame({
        "CLASS": ["Copepoda"],
        "SAMPLE_ID": ["sample-1"],
        "STATION_NAME": ["station-1"],
        "C4_ABUND (ind./m3 depth vol.)": [4.0],
        "C5_ABUND (ind./m3 depth vol.)": [5.0],
        "M_ABUND (ind./m3 depth vol.)": [2.0],
        "F_ABUND (ind./m3 depth vol.)": [3.0],
    })

    result = neolabs_copepod_density(df, stages="c4 + c5; m, f")

    assert result.iloc[0]["stages_used"] == "C4+C5+M+F"
    assert result.iloc[0]["copepod_density_ind_m3"] == 14.0
