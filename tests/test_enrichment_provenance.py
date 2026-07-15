from datetime import datetime, timezone

import pandas as pd
import pytest


def _schema():
    from core.environment_resolver import resolve_environment_schema

    return resolve_environment_schema(
        pd.DataFrame(
            {
                "object_lat": [74.0],
                "object_lon": [-80.0],
                "object_date": ["2018-08-01"],
            }
        )
    )


def _build(**overrides):
    from core.environment_resolver import build_enrichment_provenance

    values = {
        "source": "Amundsen Science CTD",
        "dataset_id": "amundsen12713",
        "dataset_url": "https://erddap.amundsenscience.com/erddap/tabledap/amundsen12713.html",
        "completed_at": datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc),
        "parameters": {"spatial_tolerance_km": 25.0},
        "resolved_schema": _schema(),
        "variables": ["TE90", "PSAL"],
        "coverage": {
            "total_rows": 10,
            "matched_rows": 8,
            "match_rate": 0.8,
            "status_counts": {"matched": 8, "no_match": 2},
        },
    }
    values.update(overrides)
    return build_enrichment_provenance(**values)


def test_builds_json_serializable_enrichment_provenance():
    result = _build()

    assert result["source"] == "Amundsen Science CTD"
    assert result["dataset_id"] == "amundsen12713"
    assert result["completed_at_utc"] == "2026-07-14T20:00:00+00:00"
    assert result["resolved_columns"]["columns"]["time"] == "object_date"
    assert result["coverage"]["match_rate"] == 0.8


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"dataset_id": ""}, "dataset_id"),
        ({"dataset_url": "amundsen12713"}, "dataset_url"),
        ({"completed_at": datetime(2026, 7, 14, 20, 0)}, "UTC"),
        (
            {
                "coverage": {
                    "total_rows": 10,
                    "matched_rows": 8,
                    "match_rate": 0.7,
                    "status_counts": {"matched": 8, "no_match": 2},
                }
            },
            "match_rate",
        ),
    ],
)
def test_refuses_invalid_provenance(override, match):
    with pytest.raises(ValueError, match=match):
        _build(**override)


def test_accepts_structured_join_schema():
    result = _build(
        source="EcoTaxa + EcoPart",
        dataset_id="ecopart:105",
        dataset_url="https://ecopart.obs-vlfr.fr/prj/105",
        resolved_schema={
            "columns": {
                "sample": "obj_orig_id (profil)",
                "depth": "object_depth_min",
                "ecopart_sample": "Profile",
                "ecopart_depth": "Depth [m]",
            },
            "resolution": {"sample": "overlap", "depth": "detected"},
        },
    )

    assert result["resolved_columns"]["columns"]["sample"] == "obj_orig_id (profil)"
