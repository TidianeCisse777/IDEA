"""Contrat déterministe correspondance + comparaison filet ↔ UVP."""

import numpy as np
import pandas as pd
import pytest

from core.net_uvp_comparison import (
    NET_UVP_COMPARE_METHOD_VERSION,
    NET_UVP_MATCH_METHOD_VERSION,
    compare_paired_density,
    haversine_km,
    join_certified_net_uvp_enriched,
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
            "station_id": ["S1", "S2"],
            "profile_id": ["cruise_s1_1", "cruise_s2_1"],
            "lat_avg": [67.5, 60.0],
            "lon_avg": [-63.8, -60.0],
            "date_min": ["2015-06-03", "2015-06-03"],
        }
    )


def test_haversine_zero_and_known_distance():
    assert haversine_km(0.0, 0.0, 0.0, 0.0) == pytest.approx(0.0)
    # 1° de latitude ≈ 111 km
    assert float(haversine_km(0.0, 0.0, 1.0, 0.0)) == pytest.approx(111.19, abs=0.5)


def test_matches_by_spatiotemporal_proximity():
    out = match_net_to_uvp(_net(), _uvp(), max_days=None)
    assert list(out["net_sample_id"]) == [101, 102]
    assert list(out["match_method"]) == ["deployment_spatiotemporal", "deployment_spatiotemporal"]
    assert out.iloc[0]["uvp_sample_id"] == 1
    assert out.iloc[0]["uvp_profile_str"] == "cruise_s1_1"
    assert out.iloc[0]["match_status"] == "matched"
    assert out["join_eligible"].all()
    assert out.iloc[0]["method_version"] == NET_UVP_MATCH_METHOD_VERSION


def test_picks_best_temporal_match_among_candidates():
    """Station visitée deux fois : on doit choisir le sample temporellement le plus proche."""
    net = pd.DataFrame({
        "SAMPLE_ID": [1],
        "STATION_NAME": ["S1"],
        "latitude": [67.5],
        "longitude": [-63.8],
        "deployment_datetime_start": ["2015-06-01"],
    })
    uvp = pd.DataFrame({
        "sample_id": [10, 20],        # deux passages à S1
        "project_id": [42, 42],
        "instrument": ["UVP5SD", "UVP5SD"],
        "station_id": ["S1", "S1"],   # même station
        "profile_id": ["p_old", "p_close"],
        "lat_avg": [67.5, 67.5],
        "lon_avg": [-63.8, -63.8],
        "date_min": ["2010-01-01", "2015-06-03"],  # p_close est à 2 jours
    })
    out = match_net_to_uvp(net, uvp, max_days=None)
    assert len(out) == 1
    assert out.iloc[0]["uvp_sample_id"] == 20      # p_close sélectionné
    assert out.iloc[0]["uvp_profile_str"] == "p_close"
    assert out.iloc[0]["time_gap_days"] == pytest.approx(2.0, abs=0.5)


def test_temporal_gap_flags_spatial_only():
    net = _net().assign(deployment_datetime_start=["2014-06-01", "2014-06-01"])
    uvp = _uvp().assign(date_min=["2024-06-01", "2024-06-01"])
    out = match_net_to_uvp(net, uvp, max_days=60)
    assert list(out["match_status"]) == ["spatial_only", "spatial_only"]
    assert not out["join_eligible"].any()
    assert out.iloc[0]["time_gap_days"] > 3000


def test_matches_once_per_deployment_then_expands_to_net_samples():
    net = pd.DataFrame(
        {
            "SAMPLE_ID": [101, 102],
            "DEPLOYMENT_ID": [7, 7],
            "STATION_NAME": ["Filet-7", "Filet-7"],
            "latitude": [67.5, 67.5],
            "longitude": [-63.8, -63.8],
            "deployment_datetime_start": ["2015-06-01", "2015-06-01"],
        }
    )
    uvp = pd.DataFrame(
        {
            "sample_id": [10, 20],
            "project_id": [42, 42],
            "instrument": ["UVP5SD", "UVP5SD"],
            # Names deliberately differ: station text is evidence, not a filter.
            "station_id": ["Different-name", "Filet-7"],
            "profile_id": ["p_close_date", "p_old_date"],
            "lat_avg": [67.51, 67.5001],
            "lon_avg": [-63.8, -63.8],
            "date_min": ["2015-06-02", "2010-01-01"],
        }
    )
    out = match_net_to_uvp(
        net, uvp, max_km=50, max_days=2, net_deployment_col="DEPLOYMENT_ID"
    )
    assert list(out["net_sample_id"]) == [101, 102]
    assert out["net_deployment_id"].eq("7").all()
    assert out["uvp_sample_id"].eq(10).all()
    assert not out["station_name_match"].any()
    assert out["join_eligible"].all()


def test_missing_uvp_dates_stays_spatial_only_and_is_not_join_eligible():
    uvp = _uvp().assign(date_min=[None, None])
    out = match_net_to_uvp(_net(), uvp, max_days=2)
    assert len(out) == 2
    assert out["match_status"].eq("spatial_only").all()
    assert not out["join_eligible"].any()


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


def test_certified_join_uses_project_and_profile_keys():
    net = pd.DataFrame(
        {
            "SAMPLE_ID": ["101", "102"],
            "net_measurement": [1.0, 2.0],
        }
    )
    audit = pd.DataFrame(
        {
            "net_sample_id": [101, 102],
            "uvp_sample_id": [10, 20],
            "uvp_project_id": [42, 42],
            "uvp_profile_str": ["profile-a", "profile-b"],
            "join_eligible": [True, True],
            "ctd_filename_join_eligible": [True, True],
        }
    )
    enriched = pd.DataFrame(
        {
            "export_project_id": [42, 99, 42],
            "sample_profileid": ["profile-a", "profile-b", "other-profile"],
            "density_ind_m3": [15.0, 99.0, 3.0],
        }
    )

    out = join_certified_net_uvp_enriched(net, audit, enriched)

    assert set(out["uvp_sample_id"]) == {10}
    assert out["ctd_filename_join_eligible"].all()


def test_certified_join_excludes_uncertified_audit_rows():
    net = pd.DataFrame({"SAMPLE_ID": ["101"]})
    audit = pd.DataFrame(
        {
            "net_sample_id": [101],
            "uvp_sample_id": [10],
            "uvp_project_id": [42],
            "uvp_profile_str": ["profile-a"],
            "join_eligible": [True],
            "ctd_filename_join_eligible": [True],
        }
    )
    enriched = pd.DataFrame(
        {
            "export_project_id": [42],
            "sample_profileid": ["profile-a"],
        }
    )

    assert join_certified_net_uvp_enriched(
        net, audit.assign(join_eligible=False), enriched
    ).empty


def test_certified_join_prioritizes_explicit_export_profile_id():
    net = pd.DataFrame({"SAMPLE_ID": [101]})
    audit = pd.DataFrame(
        {
            "net_sample_id": [101],
            "uvp_sample_id": [10],
            "uvp_project_id": [42],
            "uvp_profile_str": ["profile-a"],
            "join_eligible": [True],
        }
    )
    enriched = pd.DataFrame(
        {
            "export_project_id": [42],
            "sample_profileid": ["profile-a"],
            "sample_id": ["unrelated-object-id"],
        }
    )

    out = join_certified_net_uvp_enriched(net, audit, enriched)

    assert set(out["uvp_sample_id"]) == {10}
