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

from core.ecotaxa_browser.cache.repo import (
    cache_counts,
    open_connection,
    query_samples_filtered,
)
from core.ecotaxa_browser.errors import EcoTaxaBrowserError

_SAMPLE_CAP = 500
_BBOX_KEYS = {"south", "west", "north", "east"}
_DATE_KEYS = {"from", "to"}


def _cache_db_path() -> str:
    return os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")


def _open_cache() -> sqlite3.Connection:
    return open_connection(_cache_db_path())


def _ensure_cache_ready(conn: sqlite3.Connection) -> None:
    counts = cache_counts(conn)
    if counts["samples_indexed"] == 0:
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


def _validate_date_range(date_range: dict | None) -> tuple[str, str] | None:
    if date_range is None:
        return None
    if not isinstance(date_range, dict) or set(date_range.keys()) != _DATE_KEYS:
        raise EcoTaxaBrowserError(
            "INVALID_DATE_RANGE",
            "date_range must be a dict with keys {from, to}.",
        )
    return str(date_range["from"]), str(date_range["to"])


def samples_in_region(
    bbox: dict | None = None,
    date_range: dict | None = None,
    instrument: str | None = None,
) -> dict:
    """Return cached samples matching geo / temporal / instrument filters."""
    bbox_tuple = _validate_bbox(bbox)
    date_tuple = _validate_date_range(date_range)

    conn = _open_cache()
    try:
        _ensure_cache_ready(conn)
        bbox_repo = None
        if bbox_tuple is not None:
            south, north, west, east = bbox_tuple
            bbox_repo = (south, north, west, east)
        rows = list(query_samples_filtered(
            conn,
            bbox=bbox_repo,
            date_range=date_tuple,
            instrument=instrument,
        ))
    finally:
        conn.close()

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
    }


def projects_in_region(
    bbox: dict | None = None,
    date_range: dict | None = None,
) -> dict:
    """Group matching samples per project."""
    bbox_tuple = _validate_bbox(bbox)
    date_tuple = _validate_date_range(date_range)

    conn = _open_cache()
    try:
        _ensure_cache_ready(conn)
        rows = list(query_samples_filtered(
            conn,
            bbox=(bbox_tuple if bbox_tuple is None else
                  (bbox_tuple[0], bbox_tuple[1], bbox_tuple[2], bbox_tuple[3])),
            date_range=date_tuple,
        ))
    finally:
        conn.close()

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
    }


def _row_to_sample(row: sqlite3.Row) -> dict:
    return {
        "sample_id": int(row["sample_id"]),
        "project_id": int(row["project_id"]),
        "lat": row["lat_avg"],
        "lon": row["lon_avg"],
        "date_min": row["date_min"],
        "date_max": row["date_max"],
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
