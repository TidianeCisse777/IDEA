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
    depth_min_lt: float | None = None,
    depth_min_gte: float | None = None,
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

    ``depth_max_lt`` / ``depth_max_gte`` filter the cached sample-level
    maximum object depth (the deepest object the sample reached).
    ``depth_min_lt`` / ``depth_min_gte`` filter the sample-level minimum
    object depth (the shallowest object — where the cast started). Combine
    ``depth_min_gte=A`` with ``depth_max_lt=B`` to keep only samples whose
    cast is entirely contained in the [A, B[ band. NULL depths are excluded
    by these SQL comparisons.
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
            depth_min_lt=depth_min_lt,
            depth_min_gte=depth_min_gte,
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


def _sample_station_label(row) -> str | None:
    """Identifiant de station lisible d'un sample (station_id > original_id > profile_id)."""
    for key in ("station_id", "original_id", "profile_id"):
        value = row[key] if key in row.keys() else None
        if value:
            return str(value)
    return None


def _row_matches_station(row, station: str) -> bool:
    """Vrai si `station` (insensible à la casse) apparaît dans un identifiant du sample."""
    needle = station.strip().lower()
    for key in ("station_id", "original_id", "profile_id"):
        value = row[key] if key in row.keys() else None
        if value and needle in str(value).lower():
            return True
    return False


def samples_by_year(
    bbox: dict | None = None,
    date_range: dict | None = None,
    instrument: str | None = None,
    polygon_wkt: str | None = None,
    zone_name: str | None = None,
    station: str | None = None,
    project_ids: list[int] | None = None,
    depth_max_lt: float | None = None,
    depth_max_gte: float | None = None,
    depth_min_lt: float | None = None,
    depth_min_gte: float | None = None,
    month: int | None = None,
) -> dict:
    """Regroupe par **année** les samples cache d'un lieu (station ou zone).

    Vue de couverture interannuelle : pour un même endroit suivi dans la
    durée (une zone peut couvrir plusieurs stations), renvoie pour chaque
    année le nombre de samples, le nombre de stations distinctes, l'envelope
    de dates, les instruments et les projets. Sert à repérer les années
    exploitables avant un export étalé sur plusieurs années.

    Mêmes filtres géo/temporels/instrument/profondeur/projets que
    ``samples_in_region``, plus ``station`` : ne garde que les samples dont un
    identifiant (station_id / original_id / profile_id) contient la chaîne
    donnée (insensible à la casse). L'agrégation porte sur **tous** les samples
    correspondants (pas de plafond), pour des comptes annuels exacts.

    Retour : ``{"years": [...], "total_matching", "n_years", "station",
    "sample_ids", "partial", "sync_in_progress"}``. Chaque entrée d'année :
    ``{"year", "n_samples", "n_stations", "date_min", "date_max",
    "instruments", "project_ids", "sample_ids"}``, triée par année croissante
    (les samples sans date parseable sont regroupés sous ``year=None`` en fin
    de liste). Lecture du cache local — pas de download.
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
            depth_min_lt=depth_min_lt,
            depth_min_gte=depth_min_gte,
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

    if station:
        rows = [r for r in rows if _row_matches_station(r, station)]

    def _year_of(row) -> int | None:
        raw = row["date_min"] or row["date_max"]
        if not raw or len(str(raw)) < 4 or not str(raw)[:4].isdigit():
            return None
        return int(str(raw)[:4])

    buckets: dict = {}
    all_ids: list[int] = []
    for row in rows:
        year = _year_of(row)
        sid = int(row["sample_id"])
        all_ids.append(sid)
        bucket = buckets.setdefault(year, {
            "year": year,
            "sample_ids": [],
            "stations": set(),
            "instruments": set(),
            "project_ids": set(),
            "date_min": None,
            "date_max": None,
        })
        bucket["sample_ids"].append(sid)
        station_label = _sample_station_label(row)
        if station_label:
            bucket["stations"].add(station_label)
        if row["instrument"]:
            bucket["instruments"].add(row["instrument"])
        bucket["project_ids"].add(int(row["project_id"]))
        for field in ("date_min", "date_max"):
            value = row["date_min"] if field == "date_min" else row["date_max"]
            if not value:
                continue
            current = bucket[field]
            if current is None:
                bucket[field] = value
            elif field == "date_min":
                bucket[field] = min(current, value)
            else:
                bucket[field] = max(current, value)

    def _sort_key(year):
        return (year is None, year if year is not None else 0)

    years = []
    for year in sorted(buckets, key=_sort_key):
        b = buckets[year]
        years.append({
            "year": year,
            "n_samples": len(b["sample_ids"]),
            "n_stations": len(b["stations"]),
            "date_min": b["date_min"],
            "date_max": b["date_max"],
            "instruments": sorted(b["instruments"]),
            "project_ids": sorted(b["project_ids"]),
            "sample_ids": b["sample_ids"],
        })

    return {
        "years": years,
        "total_matching": len(rows),
        "n_years": len([y for y in years if y["year"] is not None]),
        "station": station,
        "sample_ids": all_ids,
        "partial": sync_in_progress,
        "sync_in_progress": sync_in_progress,
    }


def projects_in_region(
    bbox: dict | None = None,
    date_range: dict | None = None,
    polygon_wkt: str | None = None,
    zone_name: str | None = None,
    project_ids: list[int] | None = None,
    depth_max_lt: float | None = None,
    depth_max_gte: float | None = None,
    depth_min_lt: float | None = None,
    depth_min_gte: float | None = None,
) -> dict:
    """Group matching samples per project.

    Same three geographic filters as ``samples_in_region`` (``bbox``,
    ``polygon_wkt``, or ``zone_name``). When a polygon (resolved or passed)
    is provided, samples outside the polygon are excluded before
    project-level aggregation.

    ``project_ids`` restricts to a subset of EcoTaxa projects.

    ``depth_max_lt`` / ``depth_max_gte`` / ``depth_min_lt`` /
    ``depth_min_gte`` filter the sample-level depth envelope **before**
    project-level aggregation. A project is excluded from the result if
    none of its samples match. Same semantics as ``samples_in_region``.
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
            depth_max_lt=depth_max_lt,
            depth_max_gte=depth_max_gte,
            depth_min_lt=depth_min_lt,
            depth_min_gte=depth_min_gte,
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


def rank_samples_by_region(
    include_empty: bool = False,
    sort_by: str = "sample_count",
    sort_order: str = "asc",
) -> dict:
    """Rank all cached EcoTaxa samples by NeoLab/IHO/MEOW region.

    Reads only the local cache. By default, only regions that contain at
    least one cached sample are returned, plus explicit outside/missing
    buckets when they contain samples. Set ``include_empty=True`` to include
    empty registry zones for gap analysis.
    """
    from core.geo import load_registry

    order = sort_order.strip().lower()
    if order not in {"asc", "desc"}:
        raise EcoTaxaBrowserError(
            "INVALID_SORT_ORDER",
            "sort_order must be 'asc' or 'desc'.",
        )
    metric = sort_by.strip().lower()
    if metric not in {"sample_count", "date_min", "date_max"}:
        raise EcoTaxaBrowserError(
            "INVALID_SORT_BY",
            "sort_by must be 'sample_count', 'date_min', or 'date_max'.",
        )

    registry_path = os.getenv(
        "ZONES_REGISTRY", "data/geo/zones_registry.geojson",
    )
    registry = load_registry(registry_path)
    groups: dict[str, list[sqlite3.Row]] = {
        zone.canonical: [] for zone in registry.zones
    }
    groups[_OUTSIDE_IHO_REGION] = []
    groups[_MISSING_COORDINATES_REGION] = []

    conn = _open_cache()
    try:
        _ensure_cache_ready(conn)
        sync_in_progress = _sync_in_progress(conn)
        rows = list(query_samples_filtered(conn))
    finally:
        conn.close()

    for row in rows:
        lat = row["lat_avg"]
        lon = row["lon_avg"]
        if lat is None or lon is None:
            groups[_MISSING_COORDINATES_REGION].append(row)
            continue

        point = Point(lon, lat)
        region_name = _OUTSIDE_IHO_REGION
        for zone in registry.zones:
            if zone.polygon.contains(point):
                region_name = zone.canonical
                break
        groups[region_name].append(row)

    region_rows = []
    for region_name, sample_rows in groups.items():
        if not include_empty and not sample_rows:
            continue
        sample_ids = sorted(int(row["sample_id"]) for row in sample_rows)
        project_ids = sorted({int(row["project_id"]) for row in sample_rows})
        date_min_values = [
            str(row["date_min"]) for row in sample_rows
            if row["date_min"] is not None
        ]
        date_max_values = [
            str(row["date_max"]) for row in sample_rows
            if row["date_max"] is not None
        ]
        region_rows.append({
            "region": region_name,
            "sample_count": len(sample_rows),
            "project_count": len(project_ids),
            "date_min": min(date_min_values) if date_min_values else None,
            "date_max": max(date_max_values) if date_max_values else None,
            "sample_ids": sample_ids,
            "project_ids": project_ids,
        })

    def _sort_value(row: dict) -> tuple[int, int | str, str]:
        if metric == "sample_count":
            value = int(row["sample_count"])
            return (0, -value if order == "desc" else value, row["region"])
        value = row[metric]
        if value is None:
            return (1, "", row["region"])
        sortable = str(value)
        return (0, _reverse_string(sortable) if order == "desc" else sortable, row["region"])

    region_rows.sort(
        key=_sort_value
    )
    regions_with_samples = sum(1 for row in region_rows if row["sample_count"] > 0)

    return {
        "regions": region_rows,
        "total_samples": len(rows),
        "regions_with_samples": regions_with_samples,
        "total_regions": len(registry.zones),
        "include_empty": include_empty,
        "sort_by": metric,
        "sort_order": order,
        "partial": sync_in_progress,
        "sync_in_progress": sync_in_progress,
        "markdown_summary": _build_region_rank_markdown(
            regions=region_rows,
            total_samples=len(rows),
            include_empty=include_empty,
            sort_by=metric,
            sort_order=order,
            partial=sync_in_progress,
        ),
    }


def _reverse_string(value: str) -> str:
    """Return a lexicographic inverse for ISO date descending sorts."""
    return "".join(chr(0x10FFFF - ord(char)) for char in value)


def _build_region_rank_markdown(
    *,
    regions: list[dict],
    total_samples: int,
    include_empty: bool,
    sort_by: str,
    sort_order: str,
    partial: bool,
) -> str:
    title = "# EcoTaxa — samples par région"
    if partial:
        title += " — résultat partiel"
    lines = [
        title,
        f"Total samples cache : {total_samples}",
        f"Zones vides incluses : {'oui' if include_empty else 'non'}",
        f"Tri : {sort_by} "
        f"({'décroissant' if sort_order == 'desc' else 'croissant'})",
        "",
        "| Région | Samples | Projets | Date min | Date max | sample_ids |",
        "|---|---:|---:|---|---|---|",
    ]
    if not regions:
        lines.append("| Aucune région | 0 | 0 | — |")
        return "\n".join(lines)

    for row in regions:
        sample_ids = row["sample_ids"]
        shown = ", ".join(str(sample_id) for sample_id in sample_ids[:20])
        if len(sample_ids) > 20:
            shown += f", ... (+{len(sample_ids) - 20})"
        lines.append(
            f"| {row['region']} | {row['sample_count']} | "
            f"{row['project_count']} | {row['date_min'] or '—'} | "
            f"{row['date_max'] or '—'} | {shown or '—'} |"
        )
    return "\n".join(lines)


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
        "original_id": row["original_id"],
        "station_id": row["station_id"],
        "profile_id": row["profile_id"],
        "free_fields_json": row["free_fields_json"],
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
