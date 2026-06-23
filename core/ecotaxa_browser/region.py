"""Cross-project geo + temporal queries served from the local cache.

Powers UC1: ``samples_in_region`` and ``projects_in_region``. Both are
pure SQLite reads — no live EcoTaxa call. ``find_observations`` is in
the sibling module ``observations`` and combines this with a taxon
filter.
"""

from __future__ import annotations

import os
import sqlite3
from collections import Counter
from typing import Iterable

from shapely import wkt as shapely_wkt
from shapely.errors import GEOSException, ShapelyError
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from core.ecotaxa_browser.cache.repo import (
    cache_counts,
    init_schema,
    is_sync_running,
    latest_sync_status,
    open_connection,
    query_samples_filtered,
)
from core.ecotaxa_browser.errors import EcoTaxaBrowserError

_SAMPLE_CAP = 500
_BBOX_KEYS = {"south", "west", "north", "east"}
_DATE_KEYS = {"from", "to"}
_SAMPLE_PROJECT_FACTOR = 1_000_000
_OUTSIDE_IHO_REGION = "Hors zones IHO"
_MISSING_COORDINATES_REGION = "Sans coordonnées"


def _cache_db_path() -> str:
    return os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")


def _open_cache() -> sqlite3.Connection:
    conn = open_connection(_cache_db_path())
    init_schema(conn)
    return conn


def resolve_sample_projects(sample_ids: list[int]) -> dict[int, int]:
    """Map each ``sample_id`` to its ``project_id``.

    The local cache is authoritative when present. For samples missing from
    the cache, fall back to EcoTaxa's numeric ID convention where the project
    is the sample id prefix (``sample_id // 1_000_000``). This keeps explicit
    user-provided sample exports usable even when the cache is stale.
    """
    from core.ecotaxa_browser.cache.repo import lookup_sample_projects
    if not sample_ids:
        return {}
    conn = _open_cache()
    try:
        resolved = lookup_sample_projects(conn, sample_ids)
    finally:
        conn.close()
    for sample_id in sample_ids:
        if sample_id not in resolved and sample_id >= _SAMPLE_PROJECT_FACTOR:
            resolved[sample_id] = sample_id // _SAMPLE_PROJECT_FACTOR
    return resolved


def _sync_in_progress(conn: sqlite3.Connection) -> bool:
    """Return True if the latest sync run is still running (no ended_at)."""
    return is_sync_running(latest_sync_status(conn))


def _ensure_cache_ready(conn: sqlite3.Connection) -> None:
    counts = cache_counts(conn)
    if counts["samples_indexed"] > 0:
        return
    if _sync_in_progress(conn):
        raise EcoTaxaBrowserError(
            "SYNC_IN_PROGRESS",
            "EcoTaxa cache sync is currently running — retry in a moment. "
            "Call cache_status to monitor progress.",
        )
    raise EcoTaxaBrowserError(
        "CACHE_EMPTY",
        "EcoTaxa local cache is empty — trigger /admin/resync or wait for the nightly sync.",
    )


def _validate_bbox(bbox: dict | None) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    if not isinstance(bbox, dict) or set(bbox.keys()) != _BBOX_KEYS:
        raise EcoTaxaBrowserError(
            "INVALID_BBOX",
            "bbox must be a dict with keys {south, west, north, east}.",
        )
    south = float(bbox["south"])
    north = float(bbox["north"])
    west = float(bbox["west"])
    east = float(bbox["east"])
    if south > north:
        raise EcoTaxaBrowserError(
            "INVALID_BBOX",
            f"south ({south}) must be <= north ({north}).",
        )
    # west > east means antimeridian crossing — allowed but flagged.
    return south, north, west, east


def _resolve_zone_polygon(zone_name: str | None) -> BaseGeometry | None:
    """Résout un nom de zone NeoLab vers son polygone shapely.

    Évite que les polygones (jusqu'à ~480 KB pour Hudson Bay) ne transitent
    par le LLM : seul le `zone_name` court traverse la frontière, la lookup
    se fait côté tool via `core.geo.resolve_zone` sur le registry commité.
    Lève `UNKNOWN_ZONE` si le nom n'est pas reconnu (aliases inclus).
    """
    if zone_name is None:
        return None
    # Import différé pour éviter une dépendance circulaire au chargement
    # (core.geo importe shapely, et region.py est importé tôt par MCP).
    from core.geo import load_registry, resolve_zone

    registry_path = os.getenv(
        "ZONES_REGISTRY", "data/geo/zones_registry.geojson",
    )
    registry = load_registry(registry_path)
    # Match exact canonical d'abord, puis aliases insensible à la casse.
    canonical = None
    needle = zone_name.strip().lower()
    for z in registry.zones:
        if z.canonical.lower() == needle or any(
            a.lower() == needle for a in z.aliases
        ):
            canonical = z.canonical
            break
    if canonical is None:
        raise EcoTaxaBrowserError(
            "UNKNOWN_ZONE",
            f"Zone '{zone_name}' inconnue du registry NeoLab. "
            f"Zones disponibles : {[z.canonical for z in registry.zones]}",
        )
    return resolve_zone(canonical, registry=registry)["polygon"]


def _validate_polygon_wkt(polygon_wkt: str | None) -> BaseGeometry | None:
    """Parse une chaîne WKT en geometry shapely, ou lève INVALID_POLYGON."""
    if polygon_wkt is None:
        return None
    if not isinstance(polygon_wkt, str) or not polygon_wkt.strip():
        raise EcoTaxaBrowserError(
            "INVALID_POLYGON",
            "polygon_wkt must be a non-empty WKT string.",
        )
    try:
        geom = shapely_wkt.loads(polygon_wkt)
    except (GEOSException, ShapelyError, ValueError) as e:
        raise EcoTaxaBrowserError(
            "INVALID_POLYGON",
            f"polygon_wkt could not be parsed as WKT: {e}",
        ) from e
    if geom.is_empty:
        raise EcoTaxaBrowserError(
            "INVALID_POLYGON",
            "polygon_wkt parsed to an empty geometry.",
        )
    return geom


def _bbox_from_polygon(geom: BaseGeometry) -> tuple[float, float, float, float]:
    """(south, north, west, east) — même ordre que _validate_bbox renvoie."""
    minx, miny, maxx, maxy = geom.bounds
    return (miny, maxy, minx, maxx)


def _validate_date_range(date_range: dict | None) -> tuple[str, str] | None:
    if date_range is None:
        return None
    if not isinstance(date_range, dict) or set(date_range.keys()) != _DATE_KEYS:
        raise EcoTaxaBrowserError(
            "INVALID_DATE_RANGE",
            "date_range must be a dict with keys {from, to}.",
        )
    return str(date_range["from"]), str(date_range["to"])


def _validate_month(month: int | None) -> int | None:
    if month is None:
        return None
    value = int(month)
    if value < 1 or value > 12:
        raise EcoTaxaBrowserError(
            "INVALID_MONTH",
            "month must be an integer between 1 and 12.",
        )
    return value


def samples_in_region(
    bbox: dict | None = None,
    date_range: dict | None = None,
    instrument: str | None = None,
    polygon_wkt: str | None = None,
    zone_name: str | None = None,
    project_ids: list[int] | None = None,
    depth_max_lt: float | None = None,
    depth_max_gte: float | None = None,
    month: int | None = None,
) -> dict:
    """Return cached samples matching geo / temporal / instrument filters.

    Three ways to constrain geography:
    - ``bbox`` : rectangle in degrees (loose, fast).
    - ``polygon_wkt`` : WKT polygon for in-polygon precision (heavy).
    - ``zone_name`` : NeoLab zone name (e.g. "Baie de Baffin"). Resolved
      internally via ``core.geo`` — the polygon never traverses the LLM.

    ``zone_name`` wins over ``polygon_wkt`` if both are given. The resolved
    polygon's own bbox is used as the SQL pre-filter when no explicit
    ``bbox`` is provided.

    ``project_ids`` restricts results to a subset of EcoTaxa projects (SQL
    ``IN`` clause on ``samples_cache.project_id``). Combine with zone/date
    to scope « samples du projet X dans la zone Y entre A et B ».

    ``depth_max_lt`` and ``depth_max_gte`` filter the cached sample-level
    maximum object depth. NULL depths are excluded by these SQL comparisons.
    ``month`` filters samples whose cached date envelope overlaps a calendar
    month (1-12), regardless of year.
    """
    bbox_tuple = _validate_bbox(bbox)
    date_tuple = _validate_date_range(date_range)
    month_value = _validate_month(month)
    polygon = _resolve_zone_polygon(zone_name) or _validate_polygon_wkt(polygon_wkt)

    if bbox_tuple is None and polygon is not None:
        bbox_tuple = _bbox_from_polygon(polygon)

    conn = _open_cache()
    try:
        _ensure_cache_ready(conn)
        sync_in_progress = _sync_in_progress(conn)
        bbox_repo = bbox_tuple if bbox_tuple is None else (
            bbox_tuple[0], bbox_tuple[1], bbox_tuple[2], bbox_tuple[3]
        )
        rows = list(query_samples_filtered(
            conn,
            bbox=bbox_repo,
            date_range=date_tuple,
            instrument=instrument,
            project_ids=project_ids,
            depth_max_lt=depth_max_lt,
            depth_max_gte=depth_max_gte,
            month=month_value,
        ))
    finally:
        conn.close()

    if polygon is not None:
        rows = [
            r for r in rows
            if r["lat_avg"] is not None and r["lon_avg"] is not None
            and polygon.contains(Point(r["lon_avg"], r["lat_avg"]))
        ]

    total = len(rows)
    truncated = total > _SAMPLE_CAP
    selected = rows[:_SAMPLE_CAP]
    samples = [_row_to_sample(row) for row in selected]
    summary = _build_summary(rows)

    return {
        "samples": samples,
        "total_matching": total,
        "truncated": truncated,
        "summary": summary,
        "partial": sync_in_progress,
        "sync_in_progress": sync_in_progress,
    }


def projects_in_region(
    bbox: dict | None = None,
    date_range: dict | None = None,
    polygon_wkt: str | None = None,
    zone_name: str | None = None,
    project_ids: list[int] | None = None,
) -> dict:
    """Group matching samples per project.

    Same three geographic filters as ``samples_in_region`` (``bbox``,
    ``polygon_wkt``, or ``zone_name``). When a polygon (resolved or passed)
    is provided, samples outside the polygon are excluded before
    project-level aggregation.

    ``project_ids`` restricts to a subset of EcoTaxa projects.
    """
    bbox_tuple = _validate_bbox(bbox)
    date_tuple = _validate_date_range(date_range)
    polygon = _resolve_zone_polygon(zone_name) or _validate_polygon_wkt(polygon_wkt)

    if bbox_tuple is None and polygon is not None:
        bbox_tuple = _bbox_from_polygon(polygon)

    conn = _open_cache()
    try:
        _ensure_cache_ready(conn)
        sync_in_progress = _sync_in_progress(conn)
        rows = list(query_samples_filtered(
            conn,
            bbox=(bbox_tuple if bbox_tuple is None else
                  (bbox_tuple[0], bbox_tuple[1], bbox_tuple[2], bbox_tuple[3])),
            date_range=date_tuple,
            project_ids=project_ids,
        ))
    finally:
        conn.close()

    if polygon is not None:
        rows = [
            r for r in rows
            if r["lat_avg"] is not None and r["lon_avg"] is not None
            and polygon.contains(Point(r["lon_avg"], r["lat_avg"]))
        ]

    by_project: dict[int, dict] = {}
    for row in rows:
        pid = int(row["project_id"])
        entry = by_project.setdefault(
            pid,
            {
                "project_id": pid,
                "sample_count": 0,
                "object_count": 0,
                "instruments": set(),
                "date_min": row["date_min"],
                "date_max": row["date_max"],
            },
        )
        entry["sample_count"] += 1
        entry["object_count"] += int(row["object_count"] or 0)
        if row["instrument"]:
            entry["instruments"].add(row["instrument"])
        if row["date_min"] and (entry["date_min"] is None or row["date_min"] < entry["date_min"]):
            entry["date_min"] = row["date_min"]
        if row["date_max"] and (entry["date_max"] is None or row["date_max"] > entry["date_max"]):
            entry["date_max"] = row["date_max"]

    projects = []
    for entry in by_project.values():
        entry["instruments"] = sorted(entry["instruments"])
        projects.append(entry)
    projects.sort(key=lambda e: e["sample_count"], reverse=True)

    return {
        "projects": projects,
        "total_projects": len(projects),
        "total_samples": len(rows),
        "partial": sync_in_progress,
        "sync_in_progress": sync_in_progress,
    }


def group_project_samples_by_region(project_id: int) -> dict:
    """Group one EcoTaxa project's cached samples by NeoLab/IHO zone.

    Reads only the local cache. All registry zones are present in ``groups``
    for a stable public shape, followed by two explicit buckets:
    ``Hors zones IHO`` and ``Sans coordonnées``.
    """
    from core.geo import load_registry

    pid = int(project_id)
    registry_path = os.getenv(
        "ZONES_REGISTRY", "data/geo/zones_registry.geojson",
    )
    registry = load_registry(registry_path)
    groups: dict[str, list[int]] = {
        zone.canonical: [] for zone in registry.zones
    }
    groups[_OUTSIDE_IHO_REGION] = []
    groups[_MISSING_COORDINATES_REGION] = []

    conn = _open_cache()
    try:
        _ensure_cache_ready(conn)
        sync_in_progress = _sync_in_progress(conn)
        rows = list(query_samples_filtered(conn, project_ids=[pid]))
    finally:
        conn.close()

    for row in sorted(rows, key=lambda sample: int(sample["sample_id"])):
        sample_id = int(row["sample_id"])
        lat = row["lat_avg"]
        lon = row["lon_avg"]
        if lat is None or lon is None:
            groups[_MISSING_COORDINATES_REGION].append(sample_id)
            continue

        point = Point(lon, lat)
        region_name = _OUTSIDE_IHO_REGION
        for zone in registry.zones:
            if zone.polygon.contains(point):
                region_name = zone.canonical
                break
        groups[region_name].append(sample_id)

    return {
        "project_id": pid,
        "groups": groups,
        "total_samples": len(rows),
        "total_regions": len(registry.zones),
        "partial": sync_in_progress,
        "sync_in_progress": sync_in_progress,
        "markdown_summary": _build_project_region_markdown(
            project_id=pid,
            groups=groups,
            total_samples=len(rows),
            partial=sync_in_progress,
        ),
    }


def _build_project_region_markdown(
    *,
    project_id: int,
    groups: dict[str, list[int]],
    total_samples: int,
    partial: bool,
) -> str:
    title = f"# Projet EcoTaxa {project_id} — samples par région"
    if partial:
        title += " — résultat partiel"
    lines = [
        title,
        f"Total samples : {total_samples}",
        "",
        "| Région | Samples | sample_ids |",
        "|---|---:|---|",
    ]
    visible_groups = [(name, ids) for name, ids in groups.items() if ids]
    if not visible_groups:
        lines.append("| Aucune région | 0 | — |")
        return "\n".join(lines)

    for name, sample_ids in visible_groups:
        shown = ", ".join(str(sample_id) for sample_id in sample_ids[:20])
        if len(sample_ids) > 20:
            shown += f", ... (+{len(sample_ids) - 20})"
        lines.append(f"| {name} | {len(sample_ids)} | {shown} |")
    return "\n".join(lines)


def _row_to_sample(row: sqlite3.Row) -> dict:
    return {
        "sample_id": int(row["sample_id"]),
        "project_id": int(row["project_id"]),
        "lat": row["lat_avg"],
        "lon": row["lon_avg"],
        "date_min": row["date_min"],
        "date_max": row["date_max"],
        "depth_min": row["depth_min"],
        "depth_max": row["depth_max"],
        "object_count": int(row["object_count"] or 0),
        "instrument": row["instrument"],
    }


def _build_summary(rows: Iterable[sqlite3.Row]) -> dict:
    rows = list(rows)
    if not rows:
        return {
            "project_breakdown": {},
            "date_range_seen": {"min": None, "max": None},
            "lat_lon_centroid": None,
        }
    counter = Counter(int(r["project_id"]) for r in rows)
    project_breakdown = {str(pid): count for pid, count in counter.most_common()}

    dates_min = [r["date_min"] for r in rows if r["date_min"]]
    dates_max = [r["date_max"] for r in rows if r["date_max"]]
    lats = [r["lat_avg"] for r in rows if r["lat_avg"] is not None]
    lons = [r["lon_avg"] for r in rows if r["lon_avg"] is not None]

    return {
        "project_breakdown": project_breakdown,
        "date_range_seen": {
            "min": min(dates_min) if dates_min else None,
            "max": max(dates_max) if dates_max else None,
        },
        "lat_lon_centroid": (
            (sum(lats) / len(lats), sum(lons) / len(lons))
            if lats and lons else None
        ),
    }
