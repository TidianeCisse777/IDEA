#!/usr/bin/env python3
"""Assign versioned marine-zone metadata to FILET samples from their coordinates.

The classification intentionally follows the EcoTaxa loader convention: prefer a
single named non-MEOW zone, retain ambiguous overlaps, and explicitly preserve
points outside the registry rather than assigning a nearest zone.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZONES = ROOT / "shared_data/geo/zones_registry.geojson"
ZONE_VERSION = "registry-v1"


def connection(database_url: str | None = None):
    import psycopg
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env.warehouse")
    except ImportError:
        pass
    if database_url:
        return psycopg.connect(database_url)
    password = os.getenv("WAREHOUSE_POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("WAREHOUSE_POSTGRES_PASSWORD absent")
    return psycopg.connect(
        host=os.getenv("WAREHOUSE_POSTGRES_HOST", "localhost"),
        port=os.getenv("WAREHOUSE_POSTGRES_PORT", "55432"),
        dbname=os.getenv("WAREHOUSE_POSTGRES_DB", "neolab_warehouse"),
        user=os.getenv("WAREHOUSE_POSTGRES_USER", "neolab"), password=password,
    )


def point_on_segment(lon: float, lat: float, a: list[float], b: list[float]) -> bool:
    cross = (lon - a[0]) * (b[1] - a[1]) - (lat - a[1]) * (b[0] - a[0])
    if abs(cross) > 1e-10:
        return False
    return min(a[0], b[0]) - 1e-10 <= lon <= max(a[0], b[0]) + 1e-10 and min(a[1], b[1]) - 1e-10 <= lat <= max(a[1], b[1]) + 1e-10


def ring_covers(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Return whether a point is inside or on a GeoJSON linear ring."""
    inside = False
    for index, current in enumerate(ring):
        previous = ring[index - 1]
        if point_on_segment(lon, lat, previous, current):
            return True
        if (current[1] > lat) != (previous[1] > lat):
            cross_lon = (previous[0] - current[0]) * (lat - current[1]) / (previous[1] - current[1]) + current[0]
            if lon < cross_lon:
                inside = not inside
    return inside


def polygon_covers(lon: float, lat: float, polygon: list[list[list[float]]]) -> bool:
    return bool(polygon) and ring_covers(lon, lat, polygon[0]) and not any(ring_covers(lon, lat, hole) for hole in polygon[1:])


def geometry_covers(lon: float, lat: float, geometry: dict) -> bool:
    if geometry["type"] == "Polygon":
        return polygon_covers(lon, lat, geometry["coordinates"])
    if geometry["type"] == "MultiPolygon":
        return any(polygon_covers(lon, lat, polygon) for polygon in geometry["coordinates"])
    raise ValueError(f"Géométrie de zone non prise en charge : {geometry['type']}")


def geometry_bbox(geometry: dict) -> tuple[float, float, float, float]:
    def coordinates(value):
        if isinstance(value[0], (int, float)):
            yield value
        else:
            for nested in value:
                yield from coordinates(nested)
    points = list(coordinates(geometry["coordinates"]))
    longitudes, latitudes = zip(*points)
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def load_features(path: Path) -> list[tuple[str, str, dict, tuple[float, float, float, float]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        (feature["properties"]["canonical"], feature["properties"].get("source", path.name), feature["geometry"], geometry_bbox(feature["geometry"]))
        for feature in payload["features"]
    ]


def zone_for(lon: float | None, lat: float | None, features) -> tuple[str | None, str | None, str | None, str]:
    if lon is None or lat is None:
        return None, None, None, "unresolved"
    lon, lat = float(lon), float(lat)
    hits = []
    for feature in features:
        name, source, geometry = feature[:3]
        bbox = feature[3] if len(feature) > 3 else None
        if bbox and not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
            continue
        if geometry_covers(lon, lat, geometry):
            hits.append((name, source))
    preferred = [hit for hit in hits if not hit[0].startswith("MEOW:")]
    if len(preferred) == 1:
        return preferred[0][0], preferred[0][0], preferred[0][1], "assigned"
    if len(hits) == 1:
        return hits[0][0], hits[0][0], hits[0][1], "assigned"
    if len(hits) > 1:
        return "AMBIGUOUS", "AMBIGUOUS", "zones_registry.geojson", "ambiguous"
    return "HORS_ARCTIQUE_CANADIEN", "HORS_ARCTIQUE_CANADIEN", "zones_registry.geojson", "outside"


def assign(zones_path: Path = DEFAULT_ZONES, database_url: str | None = None) -> dict[str, int]:
    features = load_features(zones_path)
    with connection(database_url) as conn, conn.cursor() as cur:
        samples = cur.execute("SELECT id,latitude,longitude FROM warehouse.filet_sample ORDER BY id").fetchall()
        updates = [(*zone_for(lon, lat, features), ZONE_VERSION, sample_id) for sample_id, lat, lon in samples]
        cur.executemany(
            """UPDATE warehouse.filet_sample
               SET marine_zone_key=%s, marine_zone_name=%s, marine_zone_source=%s,
                   marine_zone_version=%s, marine_zone_assignment_status=%s
               WHERE id=%s""",
            [(key, name, source, version, status, sample_id) for key, name, source, status, version, sample_id in updates],
        )
    counts: dict[str, int] = {}
    for _, _, _, status, _, _ in updates:
        counts[status] = counts.get(status, 0) + 1
    return {"samples": len(updates), **counts}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zones", type=Path, default=DEFAULT_ZONES)
    parser.add_argument("--database-url")
    args = parser.parse_args()
    print(assign(args.zones, args.database_url))


if __name__ == "__main__":
    main()
