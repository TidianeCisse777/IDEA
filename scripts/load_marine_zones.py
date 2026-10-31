#!/usr/bin/env python3
"""Load shared_data/geo/zones_registry.geojson into warehouse.marine_zone (PostGIS),
simplified, so an agent connected only through SQL can get a real zone shape instead
of just a zone name. Idempotent: upserts by zone_key, safe to rerun after the
registry changes. Independent of the other loaders (no dataset_version, no RLS:
warehouse.marine_zone is a reference table like taxon_mapping).
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

import psycopg
from shapely.geometry import shape
from shapely.geometry.multipolygon import MultiPolygon
from shapely.geometry.polygon import Polygon

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / 'shared_data/geo/zones_registry.geojson'
DEFAULT_TOLERANCE_DEG = 0.02
# Some zones (notably Arctic archipelago composites) encode thousands of small
# islands as interior rings; Douglas-Peucker alone barely shrinks them because
# each ring still needs its own points to stay valid. Dropping rings below
# this area first (~0.001 deg^2, a few km^2 at these latitudes) is what
# actually brings a zone's GeoJSON down to a size an agent can fetch and parse
# without it dominating its context (one zone measured at 1.2 MB before, ~30-60 KB after).
DEFAULT_MIN_HOLE_AREA_DEG2 = 0.001


def default_database_url():
    if os.getenv('WAREHOUSE_DATABASE_URL'):
        return os.environ['WAREHOUSE_DATABASE_URL']
    return 'host=%s port=%s dbname=%s user=%s password=%s' % (
        os.getenv('WAREHOUSE_POSTGRES_HOST', '127.0.0.1'), os.getenv('WAREHOUSE_POSTGRES_PORT', '55432'),
        os.getenv('WAREHOUSE_POSTGRES_DB', 'neolab_warehouse'), os.getenv('WAREHOUSE_POSTGRES_USER', 'neolab'),
        os.environ['WAREHOUSE_POSTGRES_PASSWORD'])


def as_multipolygon(geometry):
    """shapely.simplify can turn a MultiPolygon into a Polygon when only one
    ring survives; the table column is always MultiPolygon, so normalize back."""
    if isinstance(geometry, Polygon):
        return MultiPolygon([geometry])
    return geometry


def drop_tiny_holes(geometry, min_area_deg2: float):
    """Remove interior rings (islands) smaller than min_area_deg2 before
    simplifying; this is what actually shrinks archipelago-heavy zones."""
    def fix(polygon: Polygon) -> Polygon:
        kept = [ring for ring in polygon.interiors if Polygon(ring).area >= min_area_deg2]
        return Polygon(polygon.exterior, kept)
    if isinstance(geometry, MultiPolygon):
        return MultiPolygon([fix(p) for p in geometry.geoms])
    return fix(geometry)


def load(conn, registry_path: Path, tolerance_deg: float, min_hole_area_deg2: float) -> int:
    registry = json.loads(registry_path.read_text(encoding='utf-8'))
    n = 0
    with conn.cursor() as cur:
        for feature in registry['features']:
            zone_key = feature.get('properties', {}).get('canonical')
            source = feature.get('properties', {}).get('source')
            if not zone_key:
                continue
            geometry = shape(feature['geometry'])
            if not geometry.is_valid:
                geometry = geometry.buffer(0)
            geometry = drop_tiny_holes(geometry, min_hole_area_deg2)
            simplified = as_multipolygon(geometry.simplify(tolerance_deg, preserve_topology=True))
            cur.execute(
                """INSERT INTO warehouse.marine_zone(zone_key, zone_source, geom, simplify_tolerance_deg, loaded_at)
                VALUES (%s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, now())
                ON CONFLICT (zone_key) DO UPDATE SET
                    zone_source = EXCLUDED.zone_source, geom = EXCLUDED.geom,
                    simplify_tolerance_deg = EXCLUDED.simplify_tolerance_deg, loaded_at = EXCLUDED.loaded_at""",
                (zone_key, source, json.dumps(simplified.__geo_interface__), tolerance_deg))
            n += 1
    conn.commit()
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--registry', type=Path, default=DEFAULT_REGISTRY)
    ap.add_argument('--tolerance-deg', type=float, default=DEFAULT_TOLERANCE_DEG,
                     help='Douglas-Peucker simplification tolerance in degrees (default %(default)s)')
    ap.add_argument('--min-hole-area-deg2', type=float, default=DEFAULT_MIN_HOLE_AREA_DEG2,
                     help='Drop islands (interior rings) smaller than this area in deg^2 before simplifying (default %(default)s)')
    ap.add_argument('--database-url')
    args = ap.parse_args()
    with psycopg.connect(args.database_url or default_database_url()) as conn:
        n = load(conn, args.registry, args.tolerance_deg, args.min_hole_area_deg2)
    print(f'[marine_zone] {n} zones chargées depuis {args.registry} '
          f'(tolérance {args.tolerance_deg}°, îles < {args.min_hole_area_deg2}°² retirées)')


if __name__ == '__main__':
    main()
