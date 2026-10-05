"""Read-only coverage navigator for the NeoLab warehouse."""

from __future__ import annotations

import os
import json
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from psycopg.rows import dict_row


app = FastAPI(title="Navigateur warehouse NeoLab", docs_url=None, redoc_url=None)
STATIC = Path(__file__).parent / "static"
ZONES = Path(os.getenv("WAREHOUSE_ZONES_PATH", "/data/zones_registry.geojson"))

# Scope of this navigator: Canadian Arctic and immediately connected northern waters.
CANADIAN_ARCTIC_ZONES = {
    "Arctique", "Baie d'Hudson", "Baie d'Ungava", "Détroit d'Hudson",
    "Baie de Baffin", "Détroit de Davis", "Mer du Labrador", "Mer de Beaufort",
    "Mer de Lincoln", "Hawke Channel", "Nunavik",
    "MEOW: High Arctic Archipelago", "MEOW: Lancaster Sound",
    "MEOW: Hudson Complex", "MEOW: Baffin Bay - Davis Strait",
    "MEOW: Northern Labrador", "MEOW: Northern Grand Banks - Southern Labrador",
    "MEOW: North Greenland", "MEOW: Beaufort Sea - continental coast and shelf",
    "MEOW: Beaufort-Amundsen-Viscount Melville-Queen Maud",
}


@contextmanager
def db():
    password = os.environ.get("WAREHOUSE_POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("WAREHOUSE_POSTGRES_PASSWORD absent")
    conn = psycopg.connect(
        host=os.getenv("WAREHOUSE_POSTGRES_HOST", "neolab-warehouse-db"),
        port=os.getenv("WAREHOUSE_POSTGRES_PORT", "5432"),
        dbname=os.getenv("WAREHOUSE_POSTGRES_DB", "neolab_warehouse"),
        user=os.getenv("WAREHOUSE_POSTGRES_USER", "neolab"),
        password=password,
        row_factory=dict_row,
    )
    try:
        yield conn
    finally:
        conn.close()


def profile_filter(zones: list[str], year_from: int | None, year_to: int | None, ecotaxa_projects: list[int], ecopart_project: int | None, search: str | None):
    """Build a shared UVP predicate for cumulative map filters."""
    clauses, values = ["1=1"], []
    if zones:
        clauses.append("p.id = ANY(%s::bigint[])")
        values.append(profile_ids_in_zones(zones))
    if ecotaxa_projects:
        clauses.append("p.ecotaxa_project_id = ANY(%s)")
        values.append(ecotaxa_projects)
    if ecopart_project is not None:
        clauses.append("p.ecopart_project_id = %s")
        values.append(ecopart_project)
    if year_from:
        clauses.append("EXTRACT(YEAR FROM p.sampled_at) >= %s")
        values.append(year_from)
    if year_to:
        clauses.append("EXTRACT(YEAR FROM p.sampled_at) <= %s")
        values.append(year_to)
    if search:
        clauses.append("(p.sample_name ILIKE %s OR p.station_key ILIKE %s OR p.cruise_key ILIKE %s)")
        values.extend([f"%{search}%"] * 3)
    return " AND ".join(clauses), values


def geometry_bbox(geometry: dict) -> tuple[float, float, float, float]:
    """Return a geometry bounding box before the more expensive point test."""
    def coordinates(value):
        if isinstance(value[0], (int, float)):
            yield value
        else:
            for nested in value:
                yield from coordinates(nested)

    points = list(coordinates(geometry["coordinates"]))
    longitudes, latitudes = zip(*points)
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def point_on_segment(lon: float, lat: float, a: list[float], b: list[float]) -> bool:
    cross = (lon - a[0]) * (b[1] - a[1]) - (lat - a[1]) * (b[0] - a[0])
    if abs(cross) > 1e-10:
        return False
    return min(a[0], b[0]) - 1e-10 <= lon <= max(a[0], b[0]) + 1e-10 and min(a[1], b[1]) - 1e-10 <= lat <= max(a[1], b[1]) + 1e-10


def ring_covers(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    for index, current in enumerate(ring):
        previous = ring[index - 1]
        if point_on_segment(lon, lat, previous, current):
            return True
        if (current[1] > lat) != (previous[1] > lat):
            crossing_lon = (previous[0] - current[0]) * (lat - current[1]) / (previous[1] - current[1]) + current[0]
            if lon < crossing_lon:
                inside = not inside
    return inside


def geometry_covers(lon: float, lat: float, geometry: dict) -> bool:
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    if geometry["type"] not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"Géométrie de zone non prise en charge : {geometry['type']}")
    return any(
        ring_covers(lon, lat, polygon[0]) and not any(ring_covers(lon, lat, hole) for hole in polygon[1:])
        for polygon in polygons
    )


@lru_cache(maxsize=1)
def zone_geometries() -> dict[str, list[tuple[dict, tuple[float, float, float, float]]]]:
    """Index the local canonical registry; the GeoJSON is mounted read-only."""
    registry = json.loads(ZONES.read_text(encoding="utf-8"))
    geometries: dict[str, list[tuple[dict, tuple[float, float, float, float]]]] = {}
    for feature in registry["features"]:
        name = feature.get("properties", {}).get("canonical")
        if name in CANADIAN_ARCTIC_ZONES:
            geometry = feature["geometry"]
            geometries.setdefault(name, []).append((geometry, geometry_bbox(geometry)))
    return geometries


@lru_cache(maxsize=50000)
def point_matches_zone(lon: float, lat: float, zones: tuple[str, ...]) -> bool:
    for zone in zones:
        for geometry, bbox in zone_geometries().get(zone, []):
            if bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3] and geometry_covers(lon, lat, geometry):
                return True
    return False


def filet_ids_in_zones(zones: list[str]) -> list[int] | None:
    """Return FILET samples in selected polygons, including overlapping assignments.

    ``marine_zone_name`` is intentionally a single-value provenance field.  It
    marks geometric overlaps as ``AMBIGUOUS`` instead of silently choosing one
    zone.  Navigation must nevertheless include an ambiguous point when its
    coordinates fall within a zone selected by the user.
    """
    if not zones:
        return None
    with db() as conn:
        rows = conn.execute("""SELECT id, latitude, longitude
                               FROM warehouse.filet_sample
                               WHERE latitude IS NOT NULL AND longitude IS NOT NULL""").fetchall()
    return [
        row["id"] for row in rows
        if point_matches_zone(float(row["longitude"]), float(row["latitude"]), tuple(sorted(set(zones))))
    ]


def profile_ids_in_zones(zones: list[str]) -> list[int]:
    """Return only profiles whose coordinates are covered by the selected zones."""
    with db() as conn:
        rows = conn.execute("""SELECT id,latitude,longitude
                               FROM warehouse.uvp_profile
                               WHERE latitude IS NOT NULL AND longitude IS NOT NULL""").fetchall()
    selected = tuple(sorted(set(zones)))
    return [r["id"] for r in rows if point_matches_zone(float(r["longitude"]), float(r["latitude"]), selected)]


def filet_filter(zone_sample_ids: list[int] | None, year_from: int | None, year_to: int | None, ecotaxa_projects: list[int], ecopart_project: int | None, search: str | None):
    """Build the FILET predicate; project facets use only proven FILET–UVP candidates."""
    clauses, values = ["1=1"], []
    if year_from:
        clauses.append("s.sampling_year >= %s")
        values.append(year_from)
    if year_to:
        clauses.append("s.sampling_year <= %s")
        values.append(year_to)
    if search:
        clauses.append("(s.sample_id ILIKE %s OR s.station_name ILIKE %s OR s.deployment_id ILIKE %s)")
        values.extend([f"%{search}%"] * 3)
    if zone_sample_ids is not None:
        if zone_sample_ids:
            clauses.append("s.id = ANY(%s)")
            values.append(zone_sample_ids)
        else:
            clauses.append("FALSE")

    uvp_clauses, uvp_values = [], []
    if ecotaxa_projects:
        uvp_clauses.append("p.ecotaxa_project_id = ANY(%s)")
        uvp_values.append(ecotaxa_projects)
    if ecopart_project is not None:
        uvp_clauses.append("p.ecopart_project_id = %s")
        uvp_values.append(ecopart_project)
    if uvp_clauses:
        clauses.append("""EXISTS (
            SELECT 1 FROM warehouse.filet_uvp_match m
            JOIN warehouse.uvp_profile p ON p.id = m.uvp_profile_id
            WHERE m.filet_sample_id = s.id AND """ + " AND ".join(uvp_clauses) + ")")
        values.extend(uvp_values)
    return " AND ".join(clauses), values



def accepted_pair_ids(zones, year_from, year_to, projects, ecopart_project, search, hours):
    """Both endpoints must satisfy the filters and be mappable."""
    pw, pv = profile_filter(zones, year_from, year_to, projects, ecopart_project, search)
    fw, fv = filet_filter(filet_ids_in_zones(zones), year_from, year_to, [], None, search)
    with db() as conn:
        rows = conn.execute(f"""
            SELECT DISTINCT p.id AS profile_id, s.id AS sample_id
            FROM warehouse.filet_uvp_match m
            JOIN warehouse.uvp_profile p ON p.id=m.uvp_profile_id
            JOIN warehouse.filet_sample s ON s.id=m.filet_sample_id
            WHERE m.match_status='accepted' AND m.time_gap_hours <= %s
              AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL
              AND s.latitude IS NOT NULL AND s.longitude IS NOT NULL
              AND {pw} AND {fw}""", [hours] + pv + fv).fetchall()
    return sorted({r["profile_id"] for r in rows}), sorted({r["sample_id"] for r in rows})

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/zone")
def zone_shape(name: list[str] = Query(default=[])):
    """Official local zone boundaries selected by the cumulative geographic filter."""
    collection = json.loads(ZONES.read_text(encoding="utf-8"))
    features = [f for f in collection["features"] if not name or f.get("properties", {}).get("canonical") in name]
    return {"type": "FeatureCollection", "features": features}


@app.get("/health")
def health():
    with db() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


@app.get("/api/options")
def options():
    # The selector exposes every named maritime zone in the local canonical registry.
    # ``AMBIGUOUS`` is an assignment outcome, not a geographic zone.
    registry = json.loads(ZONES.read_text(encoding="utf-8"))
    zones = sorted({feature.get("properties", {}).get("canonical") for feature in registry["features"] if feature.get("properties", {}).get("canonical") in CANADIAN_ARCTIC_ZONES})
    with db() as conn:
        return {
            "zones": zones,
            "years": [int(row["value"]) for row in conn.execute("SELECT DISTINCT EXTRACT(YEAR FROM sampled_at)::int AS value FROM warehouse.uvp_profile WHERE sampled_at IS NOT NULL UNION SELECT DISTINCT sampling_year FROM warehouse.filet_sample WHERE sampling_year IS NOT NULL ORDER BY 1 DESC")],
            "ecotaxa_projects": conn.execute("""SELECT DISTINCT p.ecotaxa_project_id AS value,
                ep.title AS label FROM warehouse.uvp_profile p
                JOIN warehouse.ecotaxa_project ep ON ep.project_id=p.ecotaxa_project_id
                WHERE p.ecotaxa_project_id IS NOT NULL ORDER BY ep.title""").fetchall(),
            "ecopart_projects": [row["value"] for row in conn.execute("SELECT DISTINCT ecopart_project_id AS value FROM warehouse.uvp_profile WHERE ecopart_project_id IS NOT NULL ORDER BY 1")],
        }


@app.get("/api/coverage")
def coverage(
    zone: list[str] = Query(default=[]),
    year: int | None = Query(None, ge=1900, le=2100),
    year_from: int | None = Query(None, ge=1900, le=2100),
    year_to: int | None = Query(None, ge=1900, le=2100),
    ecotaxa_project: list[int] = Query(default=[]),
    ecopart_project: int | None = None,
    search: str | None = Query(None, max_length=100),
    matched_only: bool = False,
    max_gap_hours: float = Query(10, gt=0, le=72),
):
    year_from = year if year_from is None else year_from
    year_to = year if year_to is None else year_to
    if year_from and year_to and year_from > year_to:
        year_from, year_to = year_to, year_from
    where, values = profile_filter(zone, year_from, year_to, ecotaxa_project, ecopart_project, search)
    filet_where, filet_values = filet_filter(filet_ids_in_zones(zone), year_from, year_to, ecotaxa_project, ecopart_project, search)
    if matched_only:
        profile_ids, sample_ids = accepted_pair_ids(zone, year_from, year_to, ecotaxa_project, ecopart_project, search, max_gap_hours)
        where += " AND p.id = ANY(%s::bigint[])"
        values.append(profile_ids)
        filet_where += " AND s.id = ANY(%s::bigint[])"
        filet_values.append(sample_ids)
    with db() as conn:
        uvp = conn.execute(f"""
          SELECT count(*) AS profiles,
                 count(*) FILTER (WHERE latitude IS NOT NULL AND longitude IS NOT NULL) AS geolocated_profiles,
                 count(DISTINCT ecotaxa_project_id) AS ecotaxa_projects,
                 count(DISTINCT ecopart_project_id) AS ecopart_projects,
                 min(sampled_at)::date AS first_date, max(sampled_at)::date AS last_date
          FROM warehouse.uvp_profile p WHERE {where}""", values).fetchone()
        bins = conn.execute(f"""SELECT count(*) AS bins, coalesce(sum(b.sampled_volume_l),0) AS volume_l
          FROM warehouse.uvp_bin b JOIN warehouse.uvp_profile p ON p.id=b.profile_id WHERE {where}""", values).fetchone()
        objects = conn.execute(f"""SELECT count(*) AS objects_mapped
          FROM warehouse.uvp_object_bin o JOIN warehouse.uvp_bin b ON b.id=o.uvp_bin_id
          JOIN warehouse.uvp_profile p ON p.id=b.profile_id
          WHERE {where} AND o.mapping_status='accepted'""", values).fetchone()
        taxa = conn.execute(f"""SELECT count(DISTINCT a.taxon_key) AS taxon_series
          FROM warehouse.uvp_taxon_abundance a JOIN warehouse.uvp_profile p ON p.id=a.profile_id WHERE {where}""", values).fetchone()
        ctd = conn.execute(f"""SELECT count(DISTINCT l.ctd_profile_id) AS profiles
          FROM warehouse.uvp_ctd l JOIN warehouse.uvp_profile p ON p.id=l.uvp_profile_id WHERE {where}""", values).fetchone()
        filet = conn.execute(f"""SELECT count(DISTINCT s.id) AS samples, count(DISTINCT a.id) AS analyses,
                 min(s.deployment_datetime_start)::date AS first_date,
                 max(s.deployment_datetime_start)::date AS last_date,
                 count(DISTINCT f.source_row_number) AS abundance_source_rows
          FROM warehouse.filet_sample s LEFT JOIN warehouse.filet_analysis a ON a.sample_ref=s.id
          LEFT JOIN warehouse.filet_abundance f ON f.metadata_dataset_version_id=a.dataset_version_id AND f.sample_id=a.sample_id AND f.analysis_id=a.analysis_id
          WHERE {filet_where}""", filet_values).fetchone()
        links = conn.execute(f"""SELECT
          (SELECT count(*) FROM warehouse.uvp_ecotaxa l JOIN warehouse.uvp_profile p ON p.id=l.uvp_profile_id WHERE {where}) AS uvp_ecotaxa,
          (SELECT count(*) FROM warehouse.uvp_ctd l JOIN warehouse.uvp_profile p ON p.id=l.uvp_profile_id WHERE {where}) AS uvp_ctd,
          (SELECT count(*) FROM warehouse.filet_ecotaxa) AS filet_ecotaxa,
          (SELECT count(*) FROM warehouse.filet_ctd) AS filet_ctd,
          (SELECT count(*) FROM warehouse.filet_uvp_match) AS filet_uvp""", values + values).fetchone()
        spatial = conn.execute(f"""SELECT latitude,longitude,count(*) AS profiles
          FROM warehouse.uvp_profile p WHERE {where} AND latitude IS NOT NULL AND longitude IS NOT NULL
          GROUP BY latitude,longitude ORDER BY profiles DESC LIMIT 250""", values).fetchall()
        timeline = conn.execute(f"""SELECT EXTRACT(YEAR FROM sampled_at)::int AS year,count(*) AS profiles
          FROM warehouse.uvp_profile p WHERE {where} AND sampled_at IS NOT NULL GROUP BY 1 ORDER BY 1""", values).fetchall()
        projects = conn.execute(f"""SELECT ecotaxa_project_id,ecopart_project_id,count(*) AS profiles,count(DISTINCT station_key) AS stations
          FROM warehouse.uvp_profile p WHERE {where} GROUP BY 1,2 ORDER BY profiles DESC LIMIT 20""", values).fetchall()
        results = conn.execute(f"""SELECT 'EcoPart' AS source,p.sample_name AS identifier,p.sampled_at::date AS date,p.station_key,p.marine_zone_name,
                 p.latitude,p.longitude FROM warehouse.uvp_profile p WHERE {where} ORDER BY p.sampled_at DESC NULLS LAST LIMIT 30""", values).fetchall()
        if search:
            results += conn.execute(f"""SELECT 'FILET' AS source,s.sample_id AS identifier,s.deployment_datetime_start::date AS date,s.station_name AS station_key,
                 s.marine_zone_name,s.latitude,s.longitude FROM warehouse.filet_sample s WHERE {filet_where}
                 ORDER BY s.deployment_datetime_start DESC NULLS LAST LIMIT 30""", filet_values).fetchall()
    return {"filters": {"zones": zone, "year_from": year_from, "year_to": year_to, "ecotaxa_projects": ecotaxa_project, "ecopart_project": ecopart_project, "search": search}, "uvp": {**uvp, **bins, **objects, **taxa}, "ctd": ctd, "filet": filet, "links": links, "spatial": spatial, "timeline": timeline, "projects": projects, "results": results[:30]}


@app.get("/api/map")
def map_points(
    zone: list[str] = Query(default=[]), year: int | None = Query(None, ge=1900, le=2100),
    year_from: int | None = Query(None, ge=1900, le=2100), year_to: int | None = Query(None, ge=1900, le=2100),
    ecotaxa_project: list[int] = Query(default=[]), ecopart_project: int | None = None,
    matched_only: bool = False, max_gap_hours: float = Query(10, gt=0, le=72),
):
    """One aggregated point per source coordinate: map coverage, never objects."""
    year_from = year if year_from is None else year_from
    year_to = year if year_to is None else year_to
    if year_from and year_to and year_from > year_to:
        year_from, year_to = year_to, year_from
    where, values = profile_filter(zone, year_from, year_to, ecotaxa_project, ecopart_project, None)
    filet_filter_sql, filet_values = filet_filter(filet_ids_in_zones(zone), year_from, year_to, ecotaxa_project, ecopart_project, None)
    filet_where = ["s.latitude IS NOT NULL", "s.longitude IS NOT NULL", filet_filter_sql]
    if matched_only:
        profile_ids, sample_ids = accepted_pair_ids(zone, year_from, year_to, ecotaxa_project, ecopart_project, None, max_gap_hours)
        where += " AND p.id = ANY(%s::bigint[])"
        values.append(profile_ids)
        filet_where.append("s.id = ANY(%s::bigint[])")
        filet_values.append(sample_ids)
    with db() as conn:
        uvp = conn.execute(f"""SELECT p.latitude,p.longitude,count(DISTINCT p.id) AS count,
          string_agg(DISTINCT p.sample_name, ', ') AS samples,
          string_agg(DISTINCT p.station_key, ', ') AS stations,
          string_agg(DISTINCT ep.title, ', ') AS ecotaxa_projects,
          string_agg(DISTINCT p.ecopart_project_id::text, ', ') AS ecopart_projects,
          min(p.sampled_at) AS sampled_at,max(p.sampled_at) AS last_sampled_at,
          count(DISTINCT l.ctd_profile_id) AS ctd_profiles
          FROM warehouse.uvp_profile p LEFT JOIN warehouse.uvp_ctd l ON l.uvp_profile_id=p.id
          LEFT JOIN warehouse.ecotaxa_project ep ON ep.project_id=p.ecotaxa_project_id
          WHERE {where} AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL GROUP BY 1,2""", values).fetchall()
        ctd = conn.execute(f"""SELECT c.latitude,c.longitude,count(DISTINCT c.id) AS count,
          string_agg(DISTINCT p.sample_name, ', ') AS samples,
          string_agg(DISTINCT p.station_key, ', ') AS stations,
          min(c.sampled_at) AS sampled_at
          FROM warehouse.uvp_ctd l JOIN warehouse.uvp_profile p ON p.id=l.uvp_profile_id
          JOIN warehouse.ctd_profile c ON c.id=l.ctd_profile_id
          WHERE {where} AND c.latitude IS NOT NULL AND c.longitude IS NOT NULL GROUP BY 1,2""", values).fetchall()
        filet = conn.execute(f"""SELECT s.latitude,s.longitude,count(*) AS count,
          string_agg(s.sample_id, ', ') AS samples,string_agg(DISTINCT s.station_name, ', ') AS stations,
          min(s.deployment_datetime_start) AS sampled_at,
          max(s.deployment_datetime_start) AS last_sampled_at,
          string_agg(DISTINCT NULLIF(s.sampling_platform, ''), ', ') AS sampling_platform,
          string_agg(DISTINCT NULLIF(s.gear, ''), ', ') AS gear,
          string_agg(DISTINCT NULLIF(s.tow_type, ''), ', ') AS tow_type,
          string_agg(DISTINCT s.net_mesh_size::text, ', ') AS net_mesh_size,
          string_agg(DISTINCT s.number_of_nets::text, ', ') AS number_of_nets,
          min(s.min_sample_depth) AS min_sample_depth,
          max(s.max_sample_depth) AS max_sample_depth
          FROM warehouse.filet_sample s WHERE {' AND '.join(filet_where)} GROUP BY 1,2""", filet_values).fetchall()
    return {"uvp": uvp, "ctd": ctd, "filet": filet}


@app.get("/api/filet-uvp")
def filet_uvp(
    max_gap_hours: float = Query(10, gt=0, le=72),
    zone: list[str] = Query(default=[]), year: int | None = Query(None, ge=1900, le=2100),
    year_from: int | None = Query(None, ge=1900, le=2100), year_to: int | None = Query(None, ge=1900, le=2100),
    ecotaxa_project: list[int] = Query(default=[]), ecopart_project: int | None = None,
):
    """Read-only, mappable FILET–UVP candidates for the cumulative filter."""
    year_from = year if year_from is None else year_from
    year_to = year if year_to is None else year_to
    if year_from and year_to and year_from > year_to:
        year_from, year_to = year_to, year_from
    pw, pv = profile_filter(zone, year_from, year_to, ecotaxa_project, ecopart_project, None)
    fw, fv = filet_filter(filet_ids_in_zones(zone), year_from, year_to, [], None, None)
    with db() as conn:
        rows = conn.execute(f"""SELECT m.match_status,m.time_gap_hours,s.sample_id,s.station_name,
          s.deployment_datetime_start AS filet_time,s.sampling_platform,s.gear,s.tow_type,s.net_mesh_size,s.number_of_nets,
          (SELECT count(*) FROM warehouse.uvp_ctd c WHERE c.uvp_profile_id=p.id) AS ctd_profiles,
          s.min_sample_depth,s.max_sample_depth,p.sample_name,p.station_key,p.sampled_at AS uvp_time,ep.title AS uvp_project,
          s.latitude AS filet_latitude,s.longitude AS filet_longitude,p.latitude AS uvp_latitude,p.longitude AS uvp_longitude
          FROM warehouse.filet_uvp_match m JOIN warehouse.filet_sample s ON s.id=m.filet_sample_id
          JOIN warehouse.uvp_profile p ON p.id=m.uvp_profile_id
          LEFT JOIN warehouse.ecotaxa_project ep ON ep.project_id=p.ecotaxa_project_id
          WHERE m.time_gap_hours <= %s
            AND s.latitude IS NOT NULL AND s.longitude IS NOT NULL
            AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL
            AND {pw} AND {fw}
          ORDER BY m.time_gap_hours, s.id, p.id""", [max_gap_hours] + pv + fv).fetchall()
    return {"max_gap_hours": max_gap_hours, "accepted": sum(r["match_status"] == "accepted" for r in rows),
            "ambiguous": sum(r["match_status"] == "ambiguous" for r in rows), "matches": rows}
