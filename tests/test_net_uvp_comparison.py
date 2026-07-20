"""Contrat déterministe correspondance + comparaison filet ↔ UVP."""

import numpy as np
import pandas as pd
import pytest

from core.net_uvp_comparison import (
    NET_UVP_COMPARE_METHOD_VERSION,
    NET_UVP_MATCH_METHOD_VERSION,
    compare_paired_density,
    haversine_km,
    match_net_to_uvp,
    to_ind_per_m3,
)


def _net():
    return pd.DataFrame(
        {
            "SAMPLE_ID": [101, 102],
            "STATION_NAME": ["S1", "S2"],
            "latitude": [67.5, 60.0],
            "longitude": [-63.8, -60.0],
            "deployment_datetime_start": ["2015-06-01", "2015-06-01"],
        }
    )


def _uvp():
    return pd.DataFrame(
        {
            "sample_id": [1, 2],
            "project_id": [42, 42],
            "instrument": ["UVP5SD", "UVP5SD"],
            "lat_avg": [67.5, 10.0],  # sample 2 loin de tout
            "lon_avg": [-63.8, 10.0],
            "date_min": ["2015-06-03", "2015-06-03"],
        }
    )


def test_haversine_zero_and_known_distance():
    assert haversine_km(0.0, 0.0, 0.0, 0.0) == pytest.approx(0.0)
    # 1° de latitude ≈ 111 km
    assert float(haversine_km(0.0, 0.0, 1.0, 0.0)) == pytest.approx(111.19, abs=0.5)


def test_matches_by_station_name():
    net = _net().copy()
    uvp = _uvp().assign(station_id=["S1", "S2"])
    out = match_net_to_uvp(net, uvp, max_days=None)
    assert list(out["net_sample_id"]) == [101, 102]
    assert list(out["match_method"]) == ["station_name", "station_name"]
    assert out.iloc[0]["uvp_sample_id"] == 1
    assert out.iloc[0]["match_status"] == "matched"
    assert out.iloc[0]["method_version"] == NET_UVP_MATCH_METHOD_VERSION


def test_temporal_gap_flags_spatial_only():
    net = _net().assign(deployment_datetime_start=["2014-06-01", "2014-06-01"])
    uvp = _uvp().assign(
        station_id=["S1", "S2"],
        date_min=["2024-06-01", "2024-06-01"],
    )
    out = match_net_to_uvp(net, uvp, max_days=60)
    assert list(out["match_status"]) == ["spatial_only", "spatial_only"]
    assert out.iloc[0]["time_gap_days"] > 3000


def test_rejects_missing_net_columns():
    with pytest.raises(ValueError, match="filet"):
        match_net_to_uvp(pd.DataFrame({"x": [1]}), _uvp(), max_km=50.0)


def test_to_ind_per_m3_converts_litres():
    s = pd.Series([1.0, 2.5])
    assert list(to_ind_per_m3(s, from_unit="ind_per_L")) == [1000.0, 2500.0]
    assert list(to_ind_per_m3(s, from_unit="ind_per_m3")) == [1.0, 2.5]
    with pytest.raises(ValueError, match="Unité"):
        to_ind_per_m3(s, from_unit="ind_per_image")


def test_compare_paired_density_delta_and_ratio():
    paired = pd.DataFrame(
        {
            "station": ["S1", "S2"],
            "net_ind_m3": [10.0, 4.0],
            "uvp_ind_m3": [20.0, 2.0],
        }
    )
    out = compare_paired_density(paired, net_col="net_ind_m3", uvp_col="uvp_ind_m3")
    assert list(out["abundance_delta_ind_m3"]) == [10.0, -2.0]
    assert list(out["abundance_ratio"]) == [2.0, 0.5]
    assert out["abundance_log2_ratio"].iloc[0] == pytest.approx(1.0)
    assert out["abundance_log2_ratio"].iloc[1] == pytest.approx(-1.0)
    assert out["method_version"].eq(NET_UVP_COMPARE_METHOD_VERSION).all()


def test_compare_paired_density_handles_zero_net():
    paired = pd.DataFrame({"net": [0.0], "uvp": [5.0]})
    out = compare_paired_density(paired, net_col="net", uvp_col="uvp")
    assert np.isnan(out["abundance_ratio"].iloc[0])
    assert out["abundance_delta_ind_m3"].iloc[0] == 5.0


def test_compare_rejects_missing_column():
    with pytest.raises(ValueError, match="absente"):
        compare_paired_density(pd.DataFrame({"a": [1]}), net_col="a", uvp_col="b")
