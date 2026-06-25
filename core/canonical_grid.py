"""Snap ERDDAP queries to a canonical grid so the cache is file-agnostic.

Two enrichments on slightly different source coordinates must hit the same
cache entry when their points fall in the same canonical tile. We snap:

- `bbox` → 5° lat/lon tile aligned on integer multiples of TILE_DEGREES
- `time_window` → calendar month (start = month start, end = next month start)
- `variables` → sorted alphabetically
- `pres_range` → dropped (None) — local matching applies depth tolerance

The result is one cache entry per (tile × month × variables-pack) covering
the FULL CTD content for that tile and month, reusable across all files.
"""
from __future__ import annotations

import math

import pandas as pd

TILE_DEGREES = 5.0


def snap_bbox(bbox: dict, tile_degrees: float = TILE_DEGREES) -> dict:
    lat_min = math.floor(float(bbox["lat_min"]) / tile_degrees) * tile_degrees
    lat_max = math.ceil(float(bbox["lat_max"]) / tile_degrees) * tile_degrees
    lon_min = math.floor(float(bbox["lon_min"]) / tile_degrees) * tile_degrees
    lon_max = math.ceil(float(bbox["lon_max"]) / tile_degrees) * tile_degrees
    # A point exactly on a tile boundary produces lat_max == lat_min — degenerate
    # tile. Expand one tile up/right so the boundary belongs to the tile above.
    if lat_max <= lat_min:
        lat_max = lat_min + tile_degrees
    if lon_max <= lon_min:
        lon_max = lon_min + tile_degrees
    return {
        "lat_min": lat_min,
        "lat_max": lat_max,
        "lon_min": lon_min,
        "lon_max": lon_max,
    }


def snap_time_window(time_window: dict) -> dict:
    start = pd.Timestamp(time_window["start"])
    end = pd.Timestamp(time_window["end"])
    if start.tz is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    if end.tz is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")
    start_snap = pd.Timestamp(year=start.year, month=start.month, day=1, tz="UTC")
    end_year = end.year + (1 if end.month == 12 else 0)
    end_month = 1 if end.month == 12 else end.month + 1
    end_snap = pd.Timestamp(year=end_year, month=end_month, day=1, tz="UTC")
    return {
        "start": start_snap.isoformat().replace("+00:00", "Z"),
        "end": end_snap.isoformat().replace("+00:00", "Z"),
    }


def canonicalize_amundsen_query(
    *,
    bbox: dict,
    time_window: dict,
    variables: list[str],
    tile_degrees: float = TILE_DEGREES,
) -> tuple[dict, dict, list[str]]:
    return (
        snap_bbox(bbox, tile_degrees),
        snap_time_window(time_window),
        sorted(variables),
    )


def iter_arctic_tiles(
    *,
    lat_min: float = 50.0,
    lat_max: float = 85.0,
    lon_min: float = -170.0,
    lon_max: float = -45.0,
    tile_degrees: float = TILE_DEGREES,
) -> list[dict]:
    """Yield every canonical 5° tile within the arctic NeoLabs zone."""
    tiles: list[dict] = []
    lat = lat_min
    while lat < lat_max:
        lon = lon_min
        while lon < lon_max:
            tiles.append({
                "lat_min": lat,
                "lat_max": lat + tile_degrees,
                "lon_min": lon,
                "lon_max": lon + tile_degrees,
            })
            lon += tile_degrees
        lat += tile_degrees
    return tiles


def iter_months(start_year: int, start_month: int, end_year: int, end_month: int) -> list[dict]:
    """Yield every canonical (month_start, next_month_start) time_window."""
    months: list[dict] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
        end_y = year + (1 if month == 12 else 0)
        end_m = 1 if month == 12 else month + 1
        end = pd.Timestamp(year=end_y, month=end_m, day=1, tz="UTC")
        months.append({
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": end.isoformat().replace("+00:00", "Z"),
        })
        year, month = end_y, end_m
    return months
