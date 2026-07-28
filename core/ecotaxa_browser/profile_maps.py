"""Deterministic, cache-only aggregation for EcoTaxa profile maps.

The generic SQL explorer remains available for analyst-led questions. A map
where each point represents a profile, however, has a stable semantic
contract: the point is one non-empty ``profile_id`` and its size is the number
of distinct cached samples. Keeping that contract here avoids asking an LLM
to recreate a fragile aggregation for every map request.
"""

from __future__ import annotations

import os

from shapely.geometry import Point

from core.ecotaxa_browser.cache.repo import (
    cache_counts,
    open_readonly_connection,
    query_samples_filtered,
)
from core.ecotaxa_browser.errors import EcoTaxaBrowserError


def _cache_db_path() -> str:
    return os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")


def _resolve_named_zone(zone_name: str) -> dict:
    """Resolve a user zone once, keeping its geometry outside the LLM channel."""
    from core.geo import load_registry, resolve_zone

    registry_path = os.getenv("ZONES_REGISTRY", "data/geo/zones_registry.geojson")
    registry = load_registry(registry_path)
    try:
        return resolve_zone(zone_name, registry=registry)
    except KeyError as exc:
        raise EcoTaxaBrowserError(
            "UNKNOWN_ZONE",
            f"Zone '{zone_name}' inconnue du registry NeoLab. "
            f"Zones disponibles : {[zone.canonical for zone in registry.zones]}",
        ) from exc


def _bbox_from_polygon(polygon) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = polygon.bounds
    return miny, maxy, minx, maxx


def _non_empty_profile(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def profiles_for_map(zone_name: str) -> dict:
    """Return one exact-zone map row per profile and truthful coverage metrics.

    The cache is opened read-only. A bounding box narrows the SQLite query,
    then the canonical registry polygon performs the definitive inclusion
    check. This matters for bays whose polygon is much narrower than its
    rectangle.
    """
    if not isinstance(zone_name, str) or not zone_name.strip():
        raise EcoTaxaBrowserError("INVALID_ZONE", "zone_name must be a non-empty string.")

    resolved = _resolve_named_zone(zone_name)
    polygon = resolved["polygon"]
    conn = open_readonly_connection(_cache_db_path())
    try:
        if cache_counts(conn)["samples_indexed"] == 0:
            raise EcoTaxaBrowserError(
                "CACHE_EMPTY",
                "EcoTaxa local cache is empty — wait for the shared cache bootstrap.",
            )

        candidate_rows = query_samples_filtered(
            conn,
            bbox=_bbox_from_polygon(polygon),
        )
        rows_in_zone = [
            row for row in candidate_rows
            if row["lat_avg"] is not None
            and row["lon_avg"] is not None
            and polygon.contains(Point(row["lon_avg"], row["lat_avg"]))
        ]
        profile_rows = [
            row for row in rows_in_zone if _non_empty_profile(row["profile_id"])
        ]
        missing_profile = len(rows_in_zone) - len(profile_rows)
        profiles_missing_coordinates = conn.execute(
            """
            SELECT COUNT(DISTINCT TRIM(profile_id))
            FROM samples_cache
            WHERE profile_id IS NOT NULL
              AND TRIM(profile_id) <> ''
              AND (lat_avg IS NULL OR lon_avg IS NULL)
            """
        ).fetchone()[0]
    finally:
        conn.close()

    grouped: dict[str, dict] = {}
    for row in profile_rows:
        profile_id = _non_empty_profile(row["profile_id"])
        assert profile_id is not None  # narrowed directly above
        group = grouped.setdefault(
            profile_id,
            {"sample_ids": set(), "latitudes": [], "longitudes": []},
        )
        group["sample_ids"].add(int(row["sample_id"]))
        group["latitudes"].append(float(row["lat_avg"]))
        group["longitudes"].append(float(row["lon_avg"]))

    profiles = [
        {
            "profile_id": profile_id,
            "n_samples": len(group["sample_ids"]),
            "lat_avg": sum(group["latitudes"]) / len(group["latitudes"]),
            "lon_avg": sum(group["longitudes"]) / len(group["longitudes"]),
        }
        for profile_id, group in sorted(grouped.items())
    ]

    return {
        "zone": {
            "requested": zone_name,
            "canonical": resolved["canonical"],
            "source": resolved["source"],
        },
        "profiles": profiles,
        "coverage": {
            "samples_in_zone": len(rows_in_zone),
            "samples_with_profile_id": len(profile_rows),
            "profiles_with_coordinates": len(profiles),
            "samples_missing_profile_id": missing_profile,
            # These rows cannot be assigned to an exact named zone; report
            # them separately instead of pretending they are absent.
            "profiles_missing_coordinates": int(profiles_missing_coordinates or 0),
        },
    }
