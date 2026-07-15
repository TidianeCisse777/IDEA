import re

import pandas as pd
import pytest


def _joined_uvp_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sample_id": ["RA18", "RA18", "RA18"],
            "depth_bin": [212.5, 212.5, 217.5],
            "object_annotation_hierarchy": [
                "Animalia > Arthropoda > Copepoda > Calanoida",
                "Animalia > Cnidaria",
                "Animalia > Cnidaria",
            ],
            "ecopart_Sampled volume [L]": [100.0, 100.00000001, 80.0],
            "sample_stationid": ["RA18", "RA18", "RA18"],
            "amundsen_temperature": [-1.2, -1.2, -1.1],
        }
    )


def test_builds_one_row_per_sample_depth_with_zero_bins_and_abundance():
    from core.copepod_sample_depth import (
        CANONICAL_METHOD_VERSION,
        build_canonical_sample_depth,
    )

    result = build_canonical_sample_depth(
        _joined_uvp_rows(),
        stable_columns=("sample_stationid", "amundsen_temperature"),
    )

    assert list(result[["sample_id", "depth_bin"]].itertuples(index=False, name=None)) == [
        ("RA18", 212.5),
        ("RA18", 217.5),
    ]
    assert result["copepod_count"].tolist() == [1, 0]
    assert result["sampled_volume_L"].tolist() == pytest.approx([100.000000005, 80.0])
    assert result["abundance_ind_L"].tolist() == pytest.approx([0.0099999999995, 0.0])
    assert result["abundance_ind_m3"].tolist() == pytest.approx([9.9999999995, 0.0])
    assert result["sample_stationid"].tolist() == ["RA18", "RA18"]
    assert result["canonical_method_version"].eq(CANONICAL_METHOD_VERSION).all()


def test_ra18_count_is_stable_across_views_derived_from_canonical_table():
    from core.copepod_sample_depth import build_canonical_sample_depth

    canonical = build_canonical_sample_depth(_joined_uvp_rows())
    tabular_count = int(canonical.loc[canonical["sample_id"] == "RA18", "copepod_count"].sum())
    graph_count = int(
        canonical.groupby("sample_id", as_index=False)["copepod_count"].sum()
        .set_index("sample_id")
        .loc["RA18", "copepod_count"]
    )

    assert tabular_count == graph_count == 1


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("sample_id", "sample_id"),
        ("depth_bin", "depth_bin"),
        ("object_annotation_hierarchy", "object_annotation_hierarchy"),
        ("ecopart_Sampled volume [L]", "ecopart_Sampled volume [L]"),
    ],
)
def test_refuses_missing_required_column(column: str, expected: str):
    from core.copepod_sample_depth import build_canonical_sample_depth

    with pytest.raises(ValueError, match=re.escape(expected)):
        build_canonical_sample_depth(_joined_uvp_rows().drop(columns=column))


@pytest.mark.parametrize("invalid_volume", [0.0, -1.0, None])
def test_refuses_non_positive_or_missing_volume(invalid_volume):
    from core.copepod_sample_depth import build_canonical_sample_depth

    rows = _joined_uvp_rows()
    rows.loc[2, "ecopart_Sampled volume [L]"] = invalid_volume

    with pytest.raises(ValueError, match=r"volume.*RA18.*217\.5"):
        build_canonical_sample_depth(rows)


def test_refuses_incompatible_volumes_in_same_sample_depth_key():
    from core.copepod_sample_depth import build_canonical_sample_depth

    rows = _joined_uvp_rows()
    rows.loc[1, "ecopart_Sampled volume [L]"] = 120.0

    with pytest.raises(ValueError, match=r"Volumes incompatibles.*RA18.*212\.5"):
        build_canonical_sample_depth(rows)


def test_refuses_contradictory_stable_metadata_in_same_key():
    from core.copepod_sample_depth import build_canonical_sample_depth

    rows = _joined_uvp_rows()
    rows.loc[1, "sample_stationid"] = "OTHER"

    with pytest.raises(ValueError, match=r"sample_stationid.*RA18.*212\.5"):
        build_canonical_sample_depth(rows, stable_columns=("sample_stationid",))


@pytest.mark.parametrize(("column", "invalid"), [("sample_id", None), ("depth_bin", "bad")])
def test_refuses_rows_with_invalid_sample_depth_key(column: str, invalid):
    from core.copepod_sample_depth import build_canonical_sample_depth

    rows = _joined_uvp_rows()
    rows[column] = rows[column].astype("object")
    rows.loc[0, column] = invalid

    with pytest.raises(ValueError, match=column):
        build_canonical_sample_depth(rows)
