"""Chaîne filet↔UVP certifiée, de l'audit CTD à l'analyse canonique."""

import pandas as pd
import pytest

from core.copepod_sample_depth import build_canonical_sample_depth
from core.net_uvp_comparison import (
    compare_paired_density,
    join_certified_net_uvp_enriched,
)


def test_certified_net_uvp_chain_excludes_every_spatial_only_candidate():
    """Une ligne d'audit non certifiée ne doit atteindre aucun calcul final."""
    net = pd.DataFrame(
        {
            "SAMPLE_ID": [501, 502, 503],
            "station": ["S1", "S2", "S3"],
            "net_ind_m3": [15.0, 40.0, 90.0],
        }
    )
    audit = pd.DataFrame(
        {
            "net_sample_id": [501, 502, 503],
            "uvp_sample_id": [101, 203, 404],
            "uvp_project_id": [10, 20, 30],
            "uvp_profile_str": ["uvp-101", "uvp-203", "uvp-404"],
            "distance_km": [0.2, 0.4, 0.1],
            "time_gap_days": [0.5, 0.75, 8.0],
            "ctd_filename_match_status": ["matched", "matched", "filename_candidate"],
            "match_status": ["matched", "matched", "spatial_only"],
            "join_eligible": [True, True, False],
        }
    )
    enriched = pd.DataFrame(
        {
            "export_project_id": [10, 10, 20, 20, 30],
            "sample_profileid": [
                "uvp-101",
                "uvp-101",
                "uvp-203",
                "uvp-203",
                "uvp-404",
            ],
            "sample_id": ["cast-101", "cast-101", "cast-203", "cast-203", "cast-404"],
            "object_id": ["o-1", "o-2", "o-3", "o-4", "o-5"],
            "depth_bin": [2.5, 2.5, 2.5, 2.5, 2.5],
            "object_annotation_hierarchy": [
                "living>Crustacea>Copepoda",
                "living>Crustacea>Copepoda",
                "living>Crustacea>Copepoda",
                "living>Crustacea>Copepoda",
                "living>Crustacea>Copepoda",
            ],
            "ecopart_Sampled volume [L]": [100.0, 100.0, 50.0, 50.0, 20.0],
        }
    )

    final_objects = join_certified_net_uvp_enriched(net, audit, enriched)

    assert set(final_objects["SAMPLE_ID"]) == {501, 502}
    assert final_objects["join_eligible"].all()
    assert final_objects["ctd_filename_match_status"].eq("matched").all()
    assert not final_objects["match_status"].eq("spatial_only").any()
    assert 30 not in set(final_objects["export_project_id"])

    canonical = build_canonical_sample_depth(final_objects)
    assert {"abundance_ind_m3", "target_count", "sampled_volume_L"} <= set(
        canonical.columns
    )
    profile_to_net = final_objects[
        ["sample_id", "SAMPLE_ID", "station", "net_ind_m3"]
    ].drop_duplicates()
    paired = (
        canonical.merge(profile_to_net, on="sample_id", how="inner")
        .rename(columns={"abundance_ind_m3": "uvp_ind_m3"})
    )

    result = compare_paired_density(
        paired,
        net_col="net_ind_m3",
        uvp_col="uvp_ind_m3",
    )

    assert set(result["station"]) == {"S1", "S2"}
    assert result["uvp_ind_m3"].tolist() == pytest.approx([20.0, 40.0])
    assert result["abundance_ratio"].tolist() == pytest.approx([4 / 3, 1.0])


def test_certified_net_uvp_chain_stops_when_audit_has_no_ctd_match():
    net = pd.DataFrame({"SAMPLE_ID": [501], "net_ind_m3": [15.0]})
    audit = pd.DataFrame(
        {
            "net_sample_id": [501],
            "uvp_project_id": [10],
            "uvp_profile_str": ["uvp-101"],
            "ctd_filename_match_status": ["filename_candidate"],
            "match_status": ["spatial_only"],
            "join_eligible": [False],
        }
    )
    enriched = pd.DataFrame(
        {
            "export_project_id": [10],
            "sample_profileid": ["uvp-101"],
            "object_id": ["o-1"],
        }
    )

    final_objects = join_certified_net_uvp_enriched(net, audit, enriched)

    assert final_objects.empty
