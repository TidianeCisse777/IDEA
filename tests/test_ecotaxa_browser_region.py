"""TDD — core/ecotaxa_browser/region.py (samples_in_region / projects_in_region)."""

import sqlite3
from unittest.mock import patch

import pytest

from core.ecotaxa_browser.cache.repo import init_schema, upsert_sample


@pytest.fixture
def cache_db(tmp_path):
    path = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(str(path))
    init_schema(conn)
    conn.close()
    return str(path)


def _seed(cache_db, samples):
    conn = sqlite3.connect(cache_db)
    for sample in samples:
        upsert_sample(
            conn,
            sample_id=sample["sample_id"],
            project_id=sample["project_id"],
            lat_avg=sample["lat"],
            lon_avg=sample["lon"],
            date_min=sample.get("date_min", sample.get("date", "2018-01-01")),
            date_max=sample.get("date_max", sample.get("date", "2018-01-01")),
            object_count=sample.get("object_count", 10),
            instrument=sample.get("instrument", "UVP5"),
            last_synced="ts",
        )
    conn.close()


def _with_cache(cache_db):
    return patch(
        "core.ecotaxa_browser.region._cache_db_path",
        return_value=cache_db,
    )


def test_samples_in_region_returns_samples_inside_bbox(cache_db):
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0},   # Hudson Bay
        {"sample_id": 2, "project_id": 42, "lat": 65.0, "lon": -85.0},
        {"sample_id": 3, "project_id": 99, "lat": 70.0, "lon": -64.0},   # Outside
        {"sample_id": 4, "project_id": 99, "lat": 45.0, "lon": -60.0},
    ])

    bbox = {"south": 55.0, "west": -95.0, "north": 65.0, "east": -75.0}
    with _with_cache(cache_db):
        result = samples_in_region(bbox=bbox)

    sample_ids = sorted(s["sample_id"] for s in result["samples"])
    assert sample_ids == [1, 2]


def test_samples_in_region_bbox_borders_are_inclusive(cache_db):
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 55.0, "lon": -95.0},  # south-west corner
        {"sample_id": 2, "project_id": 42, "lat": 65.0, "lon": -75.0},  # north-east corner
    ])

    bbox = {"south": 55.0, "west": -95.0, "north": 65.0, "east": -75.0}
    with _with_cache(cache_db):
        result = samples_in_region(bbox=bbox)

    sample_ids = sorted(s["sample_id"] for s in result["samples"])
    assert sample_ids == [1, 2]


def test_samples_in_region_filters_by_date_range(cache_db):
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0,
         "date_min": "2018-06-01", "date_max": "2018-06-30"},
        {"sample_id": 2, "project_id": 42, "lat": 60.0, "lon": -80.0,
         "date_min": "2020-06-01", "date_max": "2020-06-30"},
        {"sample_id": 3, "project_id": 42, "lat": 60.0, "lon": -80.0,
         "date_min": "2025-06-01", "date_max": "2025-06-30"},
    ])

    with _with_cache(cache_db):
        result = samples_in_region(
            date_range={"from": "2018-01-01", "to": "2022-12-31"},
        )
    sample_ids = sorted(s["sample_id"] for s in result["samples"])
    assert sample_ids == [1, 2]


def test_samples_in_region_filters_by_instrument(cache_db):
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0, "instrument": "UVP5SD"},
        {"sample_id": 2, "project_id": 42, "lat": 60.0, "lon": -80.0, "instrument": "UVP6"},
        {"sample_id": 3, "project_id": 42, "lat": 60.0, "lon": -80.0, "instrument": "Loki"},
    ])

    with _with_cache(cache_db):
        result = samples_in_region(instrument="UVP6")
    sample_ids = sorted(s["sample_id"] for s in result["samples"])
    assert sample_ids == [2]


def test_samples_in_region_caps_at_500_and_flags_truncated(cache_db):
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {"sample_id": idx, "project_id": 42, "lat": 60.0, "lon": -80.0}
        for idx in range(1, 600)  # 599 samples
    ])
    with _with_cache(cache_db):
        result = samples_in_region()

    assert len(result["samples"]) == 500
    assert result["truncated"] is True
    assert result["total_matching"] == 599


def test_samples_in_region_summary_aggregates_project_breakdown(cache_db):
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0},
        {"sample_id": 2, "project_id": 42, "lat": 61.0, "lon": -81.0},
        {"sample_id": 3, "project_id": 99, "lat": 62.0, "lon": -82.0},
    ])
    with _with_cache(cache_db):
        result = samples_in_region()

    breakdown = result["summary"]["project_breakdown"]
    assert breakdown["42"] == 2
    assert breakdown["99"] == 1
    assert result["summary"]["date_range_seen"]["min"] == "2018-01-01"
    assert result["summary"]["date_range_seen"]["max"] == "2018-01-01"


def test_samples_in_region_raises_CACHE_EMPTY_when_empty(cache_db):
    from core.ecotaxa_browser.region import samples_in_region
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError

    with _with_cache(cache_db):
        with pytest.raises(EcoTaxaBrowserError) as exc_info:
            samples_in_region()
    assert exc_info.value.code == "CACHE_EMPTY"


def test_projects_in_region_groups_count_per_project(cache_db):
    from core.ecotaxa_browser.region import projects_in_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0},
        {"sample_id": 2, "project_id": 42, "lat": 61.0, "lon": -81.0},
        {"sample_id": 3, "project_id": 99, "lat": 62.0, "lon": -82.0},
        {"sample_id": 4, "project_id": 99, "lat": 30.0, "lon": -50.0},  # outside
    ])
    bbox = {"south": 55.0, "west": -95.0, "north": 65.0, "east": -75.0}
    with _with_cache(cache_db):
        result = projects_in_region(bbox=bbox)
    by_project = {row["project_id"]: row for row in result["projects"]}
    assert by_project[42]["sample_count"] == 2
    assert by_project[99]["sample_count"] == 1


def test_projects_in_region_raises_CACHE_EMPTY(cache_db):
    from core.ecotaxa_browser.region import projects_in_region
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError

    with _with_cache(cache_db):
        with pytest.raises(EcoTaxaBrowserError) as exc_info:
            projects_in_region()
    assert exc_info.value.code == "CACHE_EMPTY"


def test_samples_in_region_validates_bbox_dict_shape(cache_db):
    from core.ecotaxa_browser.region import samples_in_region
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError

    _seed(cache_db, [{"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0}])
    bad_bbox = {"south": 65.0, "west": -95.0, "north": 55.0, "east": -75.0}
    with _with_cache(cache_db):
        with pytest.raises(EcoTaxaBrowserError) as exc_info:
            samples_in_region(bbox=bad_bbox)
    assert exc_info.value.code == "INVALID_BBOX"
