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


# ---------------------------------------------------------------------------
# Slice 2 : polygon_wkt — post-filtre précis sur le polygone IHO/NeoLab
# ---------------------------------------------------------------------------

def test_samples_in_region_polygon_wkt_excludes_points_outside_polygon(cache_db):
    """Le polygone fin doit exclure des samples qui passent le bbox grossier.

    Setup : 4 samples dans la même bbox 55-65°N × -95 à -75°W, mais seulement
    le sample 1 tombe DANS le polygone diagonal (sud-est).
    """
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 56.0, "lon": -78.0},  # IN
        {"sample_id": 2, "project_id": 42, "lat": 64.0, "lon": -94.0},  # OUT (NW corner)
        {"sample_id": 3, "project_id": 99, "lat": 64.0, "lon": -78.0},  # OUT (NE corner)
        {"sample_id": 4, "project_id": 99, "lat": 56.0, "lon": -94.0},  # OUT (SW corner)
    ])
    # Polygone triangle qui ne contient que le sud-est du bbox
    polygon_wkt = "POLYGON((-75 55, -80 55, -75 60, -75 55))"

    with _with_cache(cache_db):
        result = samples_in_region(polygon_wkt=polygon_wkt)

    sample_ids = sorted(s["sample_id"] for s in result["samples"])
    assert sample_ids == [1]
    assert result["total_matching"] == 1


def test_samples_in_region_combines_bbox_and_polygon_wkt(cache_db):
    """bbox + polygon_wkt : bbox sert de pré-filtre rapide, polygone raffine.
    Cas réaliste : la bbox d'Ungava capte des points en Détroit d'Hudson,
    le polygone les exclut."""
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {"sample_id": 10, "project_id": 1, "lat": 59.0, "lon": -68.0},  # Ungava réel
        {"sample_id": 11, "project_id": 1, "lat": 62.5, "lon": -72.0},  # Détroit (bbox-only)
    ])
    bbox = {"south": 55.0, "west": -75.0, "north": 65.0, "east": -64.0}
    # Polygone qui ne couvre que la moitié sud (lat ≤ 61)
    polygon_wkt = "POLYGON((-75 55, -64 55, -64 61, -75 61, -75 55))"

    with _with_cache(cache_db):
        result = samples_in_region(bbox=bbox, polygon_wkt=polygon_wkt)

    sample_ids = sorted(s["sample_id"] for s in result["samples"])
    assert sample_ids == [10]


def test_samples_in_region_raises_INVALID_POLYGON_on_bad_wkt(cache_db):
    from core.ecotaxa_browser.region import samples_in_region
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError

    _seed(cache_db, [{"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0}])
    with _with_cache(cache_db):
        with pytest.raises(EcoTaxaBrowserError) as exc_info:
            samples_in_region(polygon_wkt="NOT A WKT")
    assert exc_info.value.code == "INVALID_POLYGON"


def test_projects_in_region_polygon_wkt_filters_per_project_counts(cache_db):
    """projects_in_region doit grouper par project APRÈS post-filter polygone.
    Les samples hors polygone ne doivent pas gonfler les counts d'un projet."""
    from core.ecotaxa_browser.region import projects_in_region

    _seed(cache_db, [
        {"sample_id": 100, "project_id": 1, "lat": 56.0, "lon": -78.0},  # IN
        {"sample_id": 101, "project_id": 1, "lat": 64.0, "lon": -78.0},  # OUT
        {"sample_id": 102, "project_id": 2, "lat": 56.0, "lon": -78.0},  # IN
    ])
    polygon_wkt = "POLYGON((-75 55, -80 55, -75 60, -75 55))"

    with _with_cache(cache_db):
        result = projects_in_region(polygon_wkt=polygon_wkt)

    counts = {p["project_id"]: p["sample_count"] for p in result["projects"]}
    assert counts == {1: 1, 2: 1}
    assert result["total_samples"] == 2


# ---------------------------------------------------------------------------
# Slice 2-bis : zone_name — résolution interne via core.geo, pas de WKT
# côté LLM (les polygones IHO font 100+ KB, ils ne doivent pas transiter)
# ---------------------------------------------------------------------------

def test_samples_in_region_zone_name_resolves_polygon_internally(cache_db):
    """zone_name doit déclencher la résolution interne du polygone : pour
    une zone connue du registry NeoLab, les samples sont post-filtrés sans
    que le LLM ait à passer le WKT volumineux."""
    from core.ecotaxa_browser.region import samples_in_region

    # Coords cibles : 73.74°N, -78.63°W tombent dans la bbox Baffin mais HORS
    # du polygone IHO Baffin (Lancaster Sound) — c'est notre vérité terrain.
    _seed(cache_db, [
        {"sample_id": 7301, "project_id": 1, "lat": 73.5,  "lon": -65.0},  # IN Baffin
        {"sample_id": 7302, "project_id": 1, "lat": 73.74, "lon": -78.63}, # OUT (Lancaster)
    ])

    with _with_cache(cache_db):
        result = samples_in_region(zone_name="Baie de Baffin")

    sample_ids = sorted(s["sample_id"] for s in result["samples"])
    assert sample_ids == [7301]


def test_samples_in_region_zone_name_raises_on_unknown_zone(cache_db):
    from core.ecotaxa_browser.region import samples_in_region
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError

    _seed(cache_db, [{"sample_id": 1, "project_id": 1, "lat": 60.0, "lon": -80.0}])
    with _with_cache(cache_db):
        with pytest.raises(EcoTaxaBrowserError) as exc_info:
            samples_in_region(zone_name="Mer de Nulle Part")
    assert exc_info.value.code == "UNKNOWN_ZONE"


def test_samples_in_region_zone_name_accepts_english_alias(cache_db):
    """L'alias 'Hudson Bay' doit résoudre vers Baie d'Hudson sans erreur."""
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {"sample_id": 9001, "project_id": 1, "lat": 60.0, "lon": -85.0},  # Hudson Bay
    ])
    with _with_cache(cache_db):
        result = samples_in_region(zone_name="Hudson Bay")

    assert result["total_matching"] == 1


def test_projects_in_region_zone_name(cache_db):
    from core.ecotaxa_browser.region import projects_in_region

    _seed(cache_db, [
        {"sample_id": 8001, "project_id": 1, "lat": 73.5,  "lon": -65.0},  # IN Baffin
        {"sample_id": 8002, "project_id": 2, "lat": 73.74, "lon": -78.63}, # OUT Lancaster
    ])
    with _with_cache(cache_db):
        result = projects_in_region(zone_name="Baie de Baffin")

    pids = sorted(p["project_id"] for p in result["projects"])
    assert pids == [1]
    assert result["total_samples"] == 1
