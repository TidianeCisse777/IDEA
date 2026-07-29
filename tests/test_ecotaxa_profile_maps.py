"""TDD — deterministic EcoTaxa aggregation for profile maps."""

from __future__ import annotations

import sqlite3

import pytest

from core.ecotaxa_browser.cache.repo import init_schema, upsert_sample
from core.geo import load_registry, resolve_zone


@pytest.fixture
def cache_db(tmp_path):
    path = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(path)
    init_schema(conn)
    conn.close()
    return path


def _zone_points(zone_name: str):
    registry = load_registry("data/geo/zones_registry.geojson")
    polygon = resolve_zone(zone_name, registry=registry)["polygon"]
    inside = polygon.representative_point()
    minx, miny, maxx, maxy = polygon.bounds
    candidates = [
        (minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy),
    ]
    outside = next(
        (candidate for candidate in candidates if not polygon.contains(
            type(inside)(candidate)
        )),
        None,
    )
    assert outside is not None, "The fixture needs a bbox corner outside the zone"
    return (inside.x, inside.y), outside


def _seed(conn, *, sample_id, profile_id, longitude, latitude, iho_zone=None):
    upsert_sample(
        conn,
        sample_id=sample_id,
        project_id=1,
        lat_avg=latitude,
        lon_avg=longitude,
        date_min="2024-01-01",
        date_max="2024-01-01",
        object_count=1,
        instrument="UVP5",
        profile_id=profile_id,
        iho_zone=iho_zone,
        last_synced="now",
    )


def test_profiles_for_map_uses_one_point_per_profile_and_exact_zone(
    cache_db, monkeypatch
):
    from core.ecotaxa_browser.profile_maps import profiles_for_map

    inside, outside = _zone_points("Baie de Baffin")
    conn = sqlite3.connect(cache_db)
    _seed(conn, sample_id=1, profile_id="P-1", longitude=inside[0], latitude=inside[1])
    _seed(conn, sample_id=2, profile_id="P-1", longitude=inside[0], latitude=inside[1])
    _seed(conn, sample_id=3, profile_id="P-2", longitude=inside[0], latitude=inside[1])
    _seed(conn, sample_id=4, profile_id=None, longitude=inside[0], latitude=inside[1])
    _seed(conn, sample_id=5, profile_id="P-out", longitude=outside[0], latitude=outside[1])
    _seed(conn, sample_id=6, profile_id="P-missing", longitude=None, latitude=None)
    conn.commit()
    conn.close()
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))

    result = profiles_for_map("Baie de Baffin")

    assert result["zone"]["canonical"] == "Baie de Baffin"
    assert result["zone"]["source"]
    assert result["profiles"] == [
        {
            "profile_id": "P-1",
            "n_samples": 2,
            "lat_avg": pytest.approx(inside[1]),
            "lon_avg": pytest.approx(inside[0]),
        },
        {
            "profile_id": "P-2",
            "n_samples": 1,
            "lat_avg": pytest.approx(inside[1]),
            "lon_avg": pytest.approx(inside[0]),
        },
    ]
    assert result["coverage"] == {
        "samples_in_zone": 4,
        "samples_with_profile_id": 3,
        "profiles_with_coordinates": 2,
        "samples_missing_profile_id": 1,
        "profiles_missing_coordinates": 1,
    }


def test_profiles_for_map_rejects_unknown_zone(cache_db, monkeypatch):
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError
    from core.ecotaxa_browser.profile_maps import profiles_for_map

    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))

    with pytest.raises(EcoTaxaBrowserError) as exc_info:
        profiles_for_map("Zone imaginaire")
    assert exc_info.value.code == "UNKNOWN_ZONE"


def test_profiles_for_map_global_keeps_one_cast_per_profile_and_its_iho_zone(
    cache_db, monkeypatch
):
    from core.ecotaxa_browser.profile_maps import profiles_for_map

    conn = sqlite3.connect(cache_db)
    _seed(conn, sample_id=1, profile_id="P-baffin", longitude=-65, latitude=70, iho_zone="Baie de Baffin")
    _seed(conn, sample_id=2, profile_id="P-baffin", longitude=-65, latitude=70, iho_zone="Baie de Baffin")
    _seed(conn, sample_id=3, profile_id="P-davis", longitude=-58, latitude=66, iho_zone="Détroit de Davis")
    _seed(conn, sample_id=4, profile_id="P-no-coords", longitude=None, latitude=None, iho_zone="Baie de Baffin")
    conn.commit()
    conn.close()
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))

    result = profiles_for_map()

    assert result["zone"] == {
        "requested": None,
        "canonical": "Toutes les zones IHO",
        "source": "cache partagé EcoTaxa",
        "reference": "IHO",
    }
    assert result["profiles"] == [
        {"profile_id": "P-baffin", "n_samples": 2, "lat_avg": 70.0, "lon_avg": -65.0, "zone": "Baie de Baffin"},
        {"profile_id": "P-davis", "n_samples": 1, "lat_avg": 66.0, "lon_avg": -58.0, "zone": "Détroit de Davis"},
    ]
    assert result["coverage"]["zone_reference"] == "IHO"
    assert result["coverage"]["profiles_missing_coordinates"] == 1
