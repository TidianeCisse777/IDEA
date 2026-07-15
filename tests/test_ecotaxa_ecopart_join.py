"""TDD — shared EcoTaxa–EcoPart binning and persisted-join audit."""

import pandas as pd


def test_depth_bin_5m_reproduces_documented_centres():
    from core.ecotaxa_ecopart_join import depth_bin_5m

    depth = pd.Series([0.0, 2.5, 4.99, 5.0, 12.5])

    assert depth_bin_5m(depth).tolist() == [2.5, 2.5, 2.5, 7.5, 12.5]


def test_audit_join_reports_official_depth_and_integrity():
    from core.ecotaxa_ecopart_join import audit_ecotaxa_ecopart_dataframe

    joined = pd.DataFrame({
        "sample_id": ["hc_02", "hc_02", "hc_02"],
        "object_id": ["o1", "o2", "o3"],
        "object_depth_min": [12.5, 12.5, 17.5],
        "depth_bin": [12.5, 12.5, 17.5],
        "ecopart_Sampled volume [L]": [29.7, 29.7, 37.8],
    })
    meta = {
        "variable_name": "df_ecotaxa_ecopart",
        "depth_col_used": "object_depth_min",
        "n_rows": 3,
        "n_matched": 3,
    }

    audit = audit_ecotaxa_ecopart_dataframe(joined, meta)

    assert audit["verdict"] == "validated"
    assert audit["depth_column"] == "object_depth_min"
    assert audit["duplicate_object_ids"] == 0
    assert audit["n_sample_depth_bins"] == 2
    assert audit["missing_volume_rows"] == 0
    assert audit["non_positive_volume_rows"] == 0
    assert audit["objects_outside_5m_bin"] == 0


def test_audit_join_refuses_non_official_depth_provenance():
    from core.ecotaxa_ecopart_join import audit_ecotaxa_ecopart_dataframe

    joined = pd.DataFrame({
        "sample_id": ["hc_02"],
        "object_id": ["o1"],
        "object_depth_min": [12.5],
        "object_depth_max": [14.0],
        "depth_bin": [12.5],
        "ecopart_Sampled volume [L]": [29.7],
    })

    audit = audit_ecotaxa_ecopart_dataframe(
        joined,
        {"depth_col_used": "object_depth_max", "n_matched": 1},
    )

    assert audit["verdict"] == "refused"
    assert "object_depth_min" in audit["anomalies"]


def test_audit_join_refuses_conflicting_volume_within_sample_bin():
    from core.ecotaxa_ecopart_join import audit_ecotaxa_ecopart_dataframe

    joined = pd.DataFrame({
        "sample_id": ["hc_02", "hc_02"],
        "object_id": ["o1", "o2"],
        "object_depth_min": [12.5, 12.5],
        "depth_bin": [12.5, 12.5],
        "ecopart_Sampled volume [L]": [29.7, 37.8],
    })

    audit = audit_ecotaxa_ecopart_dataframe(
        joined,
        {"depth_col_used": "object_depth_min", "n_matched": 2},
    )

    assert audit["verdict"] == "refused"
    assert audit["conflicting_volume_bins"] == 1
    assert "conflicting_volume" in audit["anomalies"]


def test_audit_join_accepts_declared_sampled_zero_object_rows():
    from core.ecotaxa_ecopart_join import audit_ecotaxa_ecopart_dataframe

    joined = pd.DataFrame({
        "sample_id": ["hc_02", "hc_02", "hc_03"],
        "object_id": ["o1", pd.NA, pd.NA],
        "object_depth_min": [12.5, pd.NA, pd.NA],
        "depth_bin": [12.5, 17.5, 7.5],
        "ecopart_Sampled volume [L]": [29.7, 37.8, 20.0],
    })

    audit = audit_ecotaxa_ecopart_dataframe(
        joined,
        {
            "depth_col_used": "object_depth_min",
            "n_matched": 1,
            "n_zero_object_bins": 2,
        },
    )

    assert audit["verdict"] == "validated"
    assert audit["duplicate_object_ids"] == 0
    assert audit["sampled_zero_object_bins"] == 2
    assert audit["objects_outside_5m_bin"] == 0
