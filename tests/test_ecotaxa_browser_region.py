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
            depth_min=sample.get("depth_min"),
            depth_max=sample.get("depth_max"),
            original_id=sample.get("original_id"),
            station_id=sample.get("station_id"),
            profile_id=sample.get("profile_id"),
            free_fields_json=sample.get("free_fields_json"),
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


def test_samples_in_region_returns_light_sample_metadata(cache_db):
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {
            "sample_id": 1,
            "project_id": 42,
            "lat": 60.0,
            "lon": -80.0,
            "original_id": "gn2015_l2_001",
            "station_id": "ice-camp",
            "profile_id": "001",
            "free_fields_json": '{"stationid": "ice-camp", "profileid": "001"}',
        },
    ])

    bbox = {"south": 55.0, "west": -95.0, "north": 65.0, "east": -75.0}
    with _with_cache(cache_db):
        result = samples_in_region(bbox=bbox)

    sample = result["samples"][0]
    assert sample["original_id"] == "gn2015_l2_001"
    assert sample["station_id"] == "ice-camp"
    assert sample["profile_id"] == "001"
    assert sample["free_fields_json"] == '{"stationid": "ice-camp", "profileid": "001"}'


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


def test_samples_in_region_filters_by_depth_max_lt(cache_db):
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {
            "sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0,
            "date_min": "2018-07-01", "date_max": "2018-07-01",
            "depth_min": 0.0, "depth_max": 82.0,
        },
        {
            "sample_id": 2, "project_id": 42, "lat": 60.0, "lon": -80.0,
            "date_min": "2018-07-02", "date_max": "2018-07-02",
            "depth_min": 0.0, "depth_max": 100.0,
        },
        {
            "sample_id": 3, "project_id": 42, "lat": 60.0, "lon": -80.0,
            "date_min": "2018-07-03", "date_max": "2018-07-03",
            "depth_min": None, "depth_max": None,
        },
    ])

    with _with_cache(cache_db):
        result = samples_in_region(
            date_range={"from": "2018-07-01", "to": "2018-07-31"},
            depth_max_lt=100,
        )

    assert [s["sample_id"] for s in result["samples"]] == [1]
    assert result["samples"][0]["depth_max"] == pytest.approx(82.0)


def test_samples_in_region_filters_by_calendar_month(cache_db):
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {
            "sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0,
            "date_min": "2018-07-01", "date_max": "2018-07-01",
        },
        {
            "sample_id": 2, "project_id": 42, "lat": 60.0, "lon": -80.0,
            "date_min": "2019-07-15", "date_max": "2019-07-15",
        },
        {
            "sample_id": 3, "project_id": 42, "lat": 60.0, "lon": -80.0,
            "date_min": "2019-06-30", "date_max": "2019-06-30",
        },
    ])

    with _with_cache(cache_db):
        result = samples_in_region(month=7)

    assert [s["sample_id"] for s in result["samples"]] == [1, 2]


def test_samples_in_region_migrates_legacy_cache_before_depth_filter(tmp_path):
    from core.ecotaxa_browser.region import samples_in_region

    path = tmp_path / "legacy-cache.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE samples_cache (
            sample_id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            lat_avg REAL,
            lon_avg REAL,
            date_min TEXT,
            date_max TEXT,
            object_count INTEGER,
            instrument TEXT,
            last_synced TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO samples_cache (
            sample_id, project_id, lat_avg, lon_avg,
            date_min, date_max, object_count, instrument, last_synced
        )
        VALUES (1, 42, 60.0, -80.0, '2018-07-01', '2018-07-01', 10, 'UVP5', 'ts')
        """
    )
    conn.commit()
    conn.close()

    with patch(
        "core.ecotaxa_browser.region._cache_db_path",
        return_value=str(path),
    ):
        result = samples_in_region(month=7)

    assert result["samples"][0]["sample_id"] == 1
    assert result["samples"][0]["depth_max"] is None


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


# ── Bootstrap progressif : SYNC_IN_PROGRESS vs CACHE_EMPTY ────────────────


def _start_running_sync(cache_db: str) -> int:
    """Insert a sync_run with no ended_at to simulate a sync in progress."""
    conn = sqlite3.connect(cache_db)
    try:
        cursor = conn.execute(
            "INSERT INTO sync_runs (started_at, status) VALUES (?, 'running')",
            ("2026-06-19T03:00:00Z",),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def test_samples_in_region_raises_SYNC_IN_PROGRESS_when_cache_empty_but_sync_running(
    cache_db,
):
    """Cache vide + sync en cours → SYNC_IN_PROGRESS (distinct de CACHE_EMPTY).

    Le LLM doit dire « patiente, sync en cours » au lieu de « lance /admin/resync ».
    """
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError
    from core.ecotaxa_browser.region import samples_in_region

    _start_running_sync(cache_db)

    with _with_cache(cache_db):
        with pytest.raises(EcoTaxaBrowserError) as exc_info:
            samples_in_region()
    assert exc_info.value.code == "SYNC_IN_PROGRESS"


def test_samples_in_region_returns_partial_flag_when_sync_running_with_cache(
    cache_db,
):
    """Cache déjà partiellement rempli + sync en cours → résultats partiels avec flag."""
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0},
    ])
    _start_running_sync(cache_db)
    bbox = {"south": 55.0, "west": -95.0, "north": 65.0, "east": -75.0}

    with _with_cache(cache_db):
        result = samples_in_region(bbox=bbox)

    assert result["partial"] is True
    assert result["sync_in_progress"] is True
    assert len(result["samples"]) == 1


def test_samples_in_region_no_partial_flag_when_sync_done(cache_db):
    """Sync terminé → résultat normal, pas de flag partial."""
    from core.ecotaxa_browser.region import samples_in_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0},
    ])
    # No running sync — leave sync_runs empty (mimics first non-cached call
    # after a successful sync but before any new run started).
    bbox = {"south": 55.0, "west": -95.0, "north": 65.0, "east": -75.0}

    with _with_cache(cache_db):
        result = samples_in_region(bbox=bbox)

    assert result.get("partial", False) is False
    assert result.get("sync_in_progress", False) is False


def test_projects_in_region_raises_SYNC_IN_PROGRESS_when_cache_empty_but_sync_running(
    cache_db,
):
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError
    from core.ecotaxa_browser.region import projects_in_region

    _start_running_sync(cache_db)

    with _with_cache(cache_db):
        with pytest.raises(EcoTaxaBrowserError) as exc_info:
            projects_in_region()
    assert exc_info.value.code == "SYNC_IN_PROGRESS"


# ── samples_by_year : regroupement interannuel station/zone ─────────────────

def test_samples_by_year_buckets_by_year_with_counts(cache_db):
    """Regroupe les samples d'une zone par année, comptes par année, tri croissant."""
    from core.ecotaxa_browser.region import samples_by_year

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0,
         "date_min": "2018-07-02", "date_max": "2018-07-02", "station_id": "st-27"},
        {"sample_id": 2, "project_id": 42, "lat": 60.1, "lon": -80.1,
         "date_min": "2018-08-14", "date_max": "2018-08-14", "station_id": "st-bb3"},
        {"sample_id": 3, "project_id": 388, "lat": 60.0, "lon": -80.0,
         "date_min": "2019-07-05", "date_max": "2019-07-05", "station_id": "st-27"},
    ])
    bbox = {"south": 55.0, "west": -95.0, "north": 65.0, "east": -75.0}
    with _with_cache(cache_db):
        result = samples_by_year(bbox=bbox)

    years = {y["year"]: y for y in result["years"]}
    assert [y["year"] for y in result["years"]] == [2018, 2019]  # tri croissant
    assert years[2018]["n_samples"] == 2
    assert years[2019]["n_samples"] == 1
    assert result["total_matching"] == 3
    assert result["n_years"] == 2


def test_samples_by_year_counts_distinct_stations_per_year(cache_db):
    """Une zone peut contenir plusieurs stations la même année."""
    from core.ecotaxa_browser.region import samples_by_year

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0,
         "date_min": "2021-07-01", "station_id": "st-27"},
        {"sample_id": 2, "project_id": 42, "lat": 60.0, "lon": -80.0,
         "date_min": "2021-07-10", "station_id": "st-27"},   # même station
        {"sample_id": 3, "project_id": 42, "lat": 60.5, "lon": -80.5,
         "date_min": "2021-08-01", "station_id": "st-bb3"},  # station distincte
    ])
    bbox = {"south": 55.0, "west": -95.0, "north": 65.0, "east": -75.0}
    with _with_cache(cache_db):
        result = samples_by_year(bbox=bbox)

    y2021 = next(y for y in result["years"] if y["year"] == 2021)
    assert y2021["n_samples"] == 3
    assert y2021["n_stations"] == 2  # st-27 et st-bb3


def test_samples_by_year_station_filter_spans_years(cache_db):
    """Filtrer une station précise ne garde que ses samples, sur toutes les années."""
    from core.ecotaxa_browser.region import samples_by_year

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0,
         "date_min": "2018-07-02", "station_id": "st-27"},
        {"sample_id": 2, "project_id": 42, "lat": 60.5, "lon": -80.5,
         "date_min": "2018-07-03", "station_id": "st-bb3"},   # autre station, exclue
        {"sample_id": 3, "project_id": 388, "lat": 60.0, "lon": -80.0,
         "date_min": "2019-07-05", "station_id": "st-27"},
    ])
    bbox = {"south": 55.0, "west": -95.0, "north": 65.0, "east": -75.0}
    with _with_cache(cache_db):
        result = samples_by_year(bbox=bbox, station="st-27")

    all_ids = sorted(sid for y in result["years"] for sid in y["sample_ids"])
    assert all_ids == [1, 3]
    assert [y["year"] for y in result["years"]] == [2018, 2019]
    assert result["station"] == "st-27"


def test_samples_by_year_reports_dates_instruments_projects(cache_db):
    """Par année : envelope de dates, instruments et projets distincts."""
    from core.ecotaxa_browser.region import samples_by_year

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0,
         "date_min": "2018-07-02", "date_max": "2018-07-02", "instrument": "UVP5",
         "station_id": "st-27"},
        {"sample_id": 2, "project_id": 240, "lat": 60.1, "lon": -80.1,
         "date_min": "2018-08-14", "date_max": "2018-08-14", "instrument": "UVP6",
         "station_id": "st-bb3"},
    ])
    bbox = {"south": 55.0, "west": -95.0, "north": 65.0, "east": -75.0}
    with _with_cache(cache_db):
        result = samples_by_year(bbox=bbox)

    y2018 = next(y for y in result["years"] if y["year"] == 2018)
    assert y2018["date_min"] == "2018-07-02"
    assert y2018["date_max"] == "2018-08-14"
    assert sorted(y2018["instruments"]) == ["UVP5", "UVP6"]
    assert sorted(y2018["project_ids"]) == [42, 240]
