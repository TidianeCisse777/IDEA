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


def test_certified_chain_keeps_same_profile_separate_across_projects():
    net = pd.DataFrame(
        {
            "SAMPLE_ID": [501, 502],
            "station": ["S1", "S2"],
            "net_ind_m3": [10.0, 20.0],
        }
    )
    audit = pd.DataFrame(
        {
            "net_sample_id": [501, 502],
            "uvp_project_id": [10, 20],
            "uvp_profile_str": ["shared-profile", "shared-profile"],
            "join_eligible": [True, True],
            "ctd_verification": ["verified", "verified"],
        }
    )
    enriched = pd.DataFrame(
        {
            "export_project_id": [10, 20],
            "sample_profileid": ["shared-profile", "shared-profile"],
            "sample_id": ["shared-cast_1", "shared-cast_1"],
            "object_id": ["project-10-object", "project-20-object"],
            "depth_bin": [2.5, 2.5],
            "object_annotation_hierarchy": [
                "living>Crustacea>Copepoda",
                "living>Crustacea>Copepoda",
            ],
            "ecopart_Sampled volume [L]": [100.0, 100.0],
        }
    )

    final_objects = join_certified_net_uvp_enriched(net, audit, enriched)
    canonical = build_canonical_sample_depth(
        final_objects,
        stable_columns=("uvp_profile_str",),
    )
    project_to_net = final_objects[
        [
            "export_project_id",
            "uvp_profile_str",
            "SAMPLE_ID",
            "station",
            "net_ind_m3",
        ]
    ].drop_duplicates()
    paired = canonical.merge(
        project_to_net,
        on=["export_project_id", "uvp_profile_str"],
        how="inner",
    )

    assert set(
        final_objects[["export_project_id", "uvp_profile_str"]].itertuples(
            index=False,
            name=None,
        )
    ) == {(10, "shared-profile"), (20, "shared-profile")}
    assert set(
        canonical[["export_project_id", "uvp_profile_str"]].itertuples(
            index=False,
            name=None,
        )
    ) == {(10, "shared-profile"), (20, "shared-profile")}
    assert canonical["target_count"].tolist() == [1, 1]
    assert set(paired["station"]) == {"S1", "S2"}


def test_certified_core_rejects_join_eligible_false_even_with_verified_ctd():
    net = pd.DataFrame({"SAMPLE_ID": [501]})
    audit = pd.DataFrame(
        {
            "net_sample_id": [501],
            "uvp_project_id": [10],
            "uvp_profile_str": ["uvp-101"],
            "join_eligible": [False],
            "ctd_verification": ["verified"],
        }
    )
    enriched = pd.DataFrame(
        {
            "export_project_id": [10],
            "sample_profileid": ["uvp-101"],
        }
    )

    assert join_certified_net_uvp_enriched(net, audit, enriched).empty


@pytest.mark.parametrize("ctd_verification", ["no_match", "unavailable"])
def test_certified_core_rejects_ctd_without_match_or_opt_in(ctd_verification):
    net = pd.DataFrame({"SAMPLE_ID": [501]})
    audit = pd.DataFrame(
        {
            "net_sample_id": [501],
            "uvp_project_id": [10],
            "uvp_profile_str": ["uvp-101"],
            "join_eligible": [True],
            "ctd_verification": [ctd_verification],
            "exploratory": [False],
        }
    )
    enriched = pd.DataFrame(
        {
            "export_project_id": [10],
            "sample_profileid": ["uvp-101"],
        }
    )

    assert join_certified_net_uvp_enriched(net, audit, enriched).empty


def test_partial_abundance_coverage_limits_density_comparison_to_calculable_pairs(
    tmp_path, monkeypatch
):
    """Five certified metadata pairs do not make five abundance comparisons."""
    import tools.copepod_sources as source_module
    from tools.dataset_registry import store_dataset
    from tools.session_store import SessionStore

    thread_id = "net-uvp-five-certified-two-abundance"
    store = SessionStore(tmp_path / "sessions")
    net = pd.DataFrame(
        {
            "SAMPLE_ID": [501, 502],
            "ANALYSIS_ID": [9001, 9002],
            "TAXON_ID": ["Calanus", "Oithona"],
            "CLASS": ["Copepoda", "Copepoda"],
            "MIN_SAMPLE_DEPTH": [0.0, 0.0],
            "MAX_SAMPLE_DEPTH": [10.0, 10.0],
            "ALL_STAGES_ABUND (ind./m3 depth vol.)": [12.0, 15.0],
        }
    )
    store_dataset(
        store,
        thread_id,
        net,
        variable_name="df_file_net_abundance",
        meta={"source": "file:abundance"},
        is_loaded_file=True,
    )
    audit = pd.DataFrame(
        {
            "net_sample_id": [501, 502, 503, 504, 505],
            "uvp_project_id": [10, 20, 30, 40, 50],
            "uvp_profile_str": ["uvp-101", "uvp-203", "uvp-304", "uvp-405", "uvp-506"],
            "join_eligible": [True] * 5,
            "ctd_verification": ["verified"] * 5,
        }
    )
    store_dataset(
        store,
        thread_id,
        audit,
        variable_name="df_net_uvp_matches",
        meta={
            "source": "net_uvp_match",
            "net_variable_name": "df_file_original_metadata",
            "net_dataframe_fingerprint": source_module._net_dataframe_fingerprint(net),
            "ctd_filename_verified": 5,
            "ctd_verification": "verified",
            "exploratory": False,
            "allow_unverified_ctd": False,
        },
        set_active=False,
    )
    store_dataset(
        store,
        thread_id,
        pd.DataFrame(
            {
                "export_project_id": [10, 20],
                "sample_profileid": ["uvp-101", "uvp-203"],
                "object_id": ["obj-1", "obj-2"],
                "depth_bin": [2.5, 2.5],
                "object_annotation_hierarchy": ["living>Crustacea>Copepoda"] * 2,
                "ecopart_Sampled volume [L]": [100.0, 100.0],
            }
        ),
        variable_name="df_ecotaxa_ecopart_campaign",
        meta={"source": "join:ecotaxa_campaign+ecopart"},
        set_active=False,
    )
    monkeypatch.setattr(source_module, "_store", store)
    join_tool = next(
        tool
        for tool in source_module.make_source_tools(thread_id)
        if tool.name == "join_net_uvp_enriched"
    )

    _, artifact = join_tool.func(
        net_variable_name="df_file_net_abundance",
        uvp_enriched_variable="df_ecotaxa_ecopart_campaign",
    )
    calculable = store.get(f"{thread_id}:dataset:df_net_uvp_calculable")["df"]
    density_comparison = compare_paired_density(
        calculable,
        net_col="net_abundance_ind_m3",
        uvp_col="uvp_abundance_ind_m3",
    )

    assert artifact["metrics"]["certified_pair_count"] == 5
    assert artifact["metrics"]["net_abundance_available_count"] == 2
    assert artifact["metrics"]["ecopart_volume_available_count"] == 2
    assert artifact["metrics"]["calculable_strata_count"] == 2
    assert artifact["metrics"]["comparison_readiness"] == "partial"
    assert density_comparison["net_sample_id"].tolist() == [501, 502]
