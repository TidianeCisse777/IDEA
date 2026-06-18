"""Taxon-aware geo+temporal search across cached samples.

Implements G1 coarse granularity: cached samples filtered by bbox /
date / instrument, then keep only the samples that belong to a project
where the taxon is attested at the requested status. Per-sample taxon
counts (G2) are deliberately out of scope for V1.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Literal

from core.ecotaxa_browser.cache.repo import (
    cache_counts,
    open_connection,
    query_samples_filtered,
)
from core.ecotaxa_browser.errors import EcoTaxaBrowserError
from shapely.geometry import Point

from core.ecotaxa_browser.region import (
    _SAMPLE_CAP,
    _bbox_from_polygon,
    _resolve_zone_polygon,
    _row_to_sample,
    _validate_bbox,
    _validate_date_range,
    _validate_polygon_wkt,
)
from core.ecotaxa_browser.taxa_stats import _resolve_taxon
from tools.ecotaxa_client import EcotaxaClient

StatusFilter = Literal["V", "P", "D", "all"]
_VALID_STATUS_FILTERS = {"V", "P", "D", "all"}


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


def find_observations(
    taxon: int | str,
    bbox: dict | None = None,
    date_range: dict | None = None,
    instrument: str | None = None,
    status: StatusFilter = "V",
    polygon_wkt: str | None = None,
    zone_name: str | None = None,
    project_ids: list[int] | None = None,
) -> dict:
    """Return cached samples whose project has the taxon attested.

    Args:
        taxon: integer taxon ID or scientific name (resolved via search_taxa).
        bbox: {south, west, north, east} or None for global.
        date_range: {from, to} or None.
        instrument: filter on the sample's instrument column.
        status: "V" (validated), "P" (predicted), "D" (dubious), or "all".
        polygon_wkt: precise polygon WKT (WGS84) for in-polygon post-filter.
        zone_name: NeoLab zone name (e.g. "Baie de Baffin"); resolved
            internally via core.geo — preferred over polygon_wkt to keep
            large polygons (~480 KB) off the LLM channel. Applied BEFORE
            project attestation lookup, so projects with only out-of-polygon
            samples are correctly excluded. ``zone_name`` wins if both are
            provided.
        project_ids: optional subset of EcoTaxa projects to consider before
            taxon attestation lookup. Use to scope "taxon X in zone Y for
            project Z" in one shot.
    """
    if status not in _VALID_STATUS_FILTERS:
        raise EcoTaxaBrowserError(
            "INVALID_STATUS",
            "status must be one of: V, P, D, all.",
            candidates=sorted(_VALID_STATUS_FILTERS),
        )

    bbox_tuple = _validate_bbox(bbox)
    date_tuple = _validate_date_range(date_range)
    polygon = _resolve_zone_polygon(zone_name) or _validate_polygon_wkt(polygon_wkt)

    if bbox_tuple is None and polygon is not None:
        bbox_tuple = _bbox_from_polygon(polygon)

    client = EcotaxaClient()
    client.login()
    resolved = _resolve_taxon(client, taxon)

    conn = _open_cache()
    try:
        _ensure_cache_ready(conn)
        rows = list(query_samples_filtered(
            conn,
            bbox=bbox_tuple,
            date_range=date_tuple,
            instrument=instrument,
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

    candidate_project_ids = sorted({int(row["project_id"]) for row in rows})
    attested_projects: list[int] = []
    project_counts: dict[int, dict] = {}
    for pid in candidate_project_ids:
        summary = client.taxon_summary(pid, resolved["taxon_id"])
        project_counts[pid] = summary
        if _matches_status(summary, status):
            attested_projects.append(pid)

    matching_rows = [r for r in rows if int(r["project_id"]) in attested_projects]
    total = len(matching_rows)
    truncated = total > _SAMPLE_CAP
    selected = matching_rows[:_SAMPLE_CAP]

    return {
        "taxon": resolved,
        "granularity": "project_filtered",
        "status_filter": status,
        "samples": [_row_to_sample(r) for r in selected],
        "total_matching": total,
        "truncated": truncated,
        "attested_projects": attested_projects,
        "project_counts": {
            str(pid): {
                "validated": int(summary.get("validated_objects") or 0),
                "predicted": int(summary.get("predicted_objects") or 0),
                "dubious": int(summary.get("dubious_objects") or 0),
                "total": int(summary.get("total_objects") or 0),
            }
            for pid, summary in project_counts.items()
        },
    }


def _matches_status(summary: dict, status: StatusFilter) -> bool:
    if status == "all":
        return int(summary.get("total_objects") or 0) > 0
    field = {
        "V": "validated_objects",
        "P": "predicted_objects",
        "D": "dubious_objects",
    }.get(status, "validated_objects")
    return int(summary.get(field) or 0) > 0
