"""EcoTaxa cache synchronization engine (M4).

Strategy: full sync (F1), per-project transaction (E3), 5 req/s throttle,
object cap 50k per project (P2). Pulls (lat, lon, objdate, sample_id) via
``POST /object_set/{id}/query`` paginated, aggregates to sample-level
averages, and replaces the project's slice of ``samples_cache`` atomically.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections import defaultdict
from typing import Any

from core.ecotaxa_browser.cache.repo import (
    finish_sync_run,
    replace_project_samples,
    start_sync_run,
    upsert_project_schema,
)
from core.ecotaxa_browser.schema import get_project_schema

_LOGGER = logging.getLogger(__name__)

_QUERY_FIELDS = "obj.latitude,obj.longitude,obj.objdate,obj.sample_id"
_DEFAULT_WINDOW_SIZE = 5000
_DEFAULT_OBJECT_CAP = 50_000
_DEFAULT_RATE_LIMIT_RPS = 5.0


def sync_project(
    conn: sqlite3.Connection,
    client: Any,
    *,
    project_id: int,
    last_synced: str,
    window_size: int = _DEFAULT_WINDOW_SIZE,
    object_cap: int = _DEFAULT_OBJECT_CAP,
    rate_limit_rps: float = _DEFAULT_RATE_LIMIT_RPS,
) -> int:
    """Synchronize one project's samples into the cache.

    Returns the number of samples cached. Raises on EcoTaxa failure —
    the caller is responsible for catching and tagging the project as
    failed in the sync_runs row. Existing rows for this project are not
    touched until the in-memory aggregation succeeds.
    """
    project_meta = client.get_project(project_id)
    instrument = project_meta.get("instrument")

    aggregates: dict[int, dict] = {}
    window_start = 0
    objects_seen = 0
    min_interval = 1.0 / rate_limit_rps if rate_limit_rps > 0 else 0.0

    while objects_seen < object_cap:
        remaining_cap = object_cap - objects_seen
        size = min(window_size, remaining_cap)
        before = time.monotonic()
        payload = client.query_objects(
            project_id=project_id,
            filters={},
            fields=_QUERY_FIELDS,
            window_start=window_start,
            window_size=size,
        )
        rows = payload.get("details") or []
        if not rows:
            break

        for row in rows:
            if len(row) < 4:
                continue
            lat, lon, objdate, sample_id = row[0], row[1], row[2], row[3]
            if lat is None or lon is None or sample_id is None:
                continue
            try:
                sid = int(sample_id)
                latf = float(lat)
                lonf = float(lon)
            except (TypeError, ValueError):
                continue
            agg = aggregates.setdefault(
                sid,
                {
                    "lat_sum": 0.0,
                    "lon_sum": 0.0,
                    "count": 0,
                    "date_min": objdate,
                    "date_max": objdate,
                },
            )
            agg["lat_sum"] += latf
            agg["lon_sum"] += lonf
            agg["count"] += 1
            if objdate is not None:
                if agg["date_min"] is None or objdate < agg["date_min"]:
                    agg["date_min"] = objdate
                if agg["date_max"] is None or objdate > agg["date_max"]:
                    agg["date_max"] = objdate

        objects_seen += len(rows)
        window_start += len(rows)
        if len(rows) < size:
            break

        # Throttle between API calls.
        elapsed = time.monotonic() - before
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    samples = [
        {
            "sample_id": sid,
            "lat_avg": agg["lat_sum"] / agg["count"],
            "lon_avg": agg["lon_sum"] / agg["count"],
            "date_min": agg["date_min"],
            "date_max": agg["date_max"],
            "object_count": agg["count"],
            "instrument": instrument,
        }
        for sid, agg in aggregates.items()
    ]

    replace_project_samples(
        conn,
        project_id=project_id,
        samples=samples,
        last_synced=last_synced,
    )
    return len(samples)


def _snapshot_project_schema(
    conn: sqlite3.Connection,
    client: Any,
    *,
    project_id: int,
    last_synced: str,
) -> None:
    """Cache the get_project_schema output for one project."""
    import core.ecotaxa_browser.schema as schema_module

    original_factory = schema_module.EcotaxaClient
    schema_module.EcotaxaClient = lambda: client  # type: ignore[assignment]
    try:
        schema = get_project_schema(project_id)
    finally:
        schema_module.EcotaxaClient = original_factory  # type: ignore[assignment]

    upsert_project_schema(
        conn,
        project_id=project_id,
        schema_json=json.dumps(schema),
        last_synced=last_synced,
    )


def run_full_sync(
    conn: sqlite3.Connection,
    client: Any,
    *,
    now_iso: str,
    window_size: int = _DEFAULT_WINDOW_SIZE,
    object_cap: int = _DEFAULT_OBJECT_CAP,
    rate_limit_rps: float = _DEFAULT_RATE_LIMIT_RPS,
) -> dict:
    """Full sync (F1) across every project the service account sees.

    Per-project transactional (E3) — a failure on one project rolls back
    that project's rows but leaves the others committed. Returns a summary
    dict mirroring the ``sync_runs`` row.
    """
    run_id = start_sync_run(conn, started_at=now_iso)

    client.login()
    projects = client.list_projects()

    projects_synced = 0
    samples_synced = 0
    failures: list[str] = []

    for project_meta in projects:
        project_id = int(project_meta["projid"])
        try:
            samples_synced += sync_project(
                conn,
                client,
                project_id=project_id,
                last_synced=now_iso,
                window_size=window_size,
                object_cap=object_cap,
                rate_limit_rps=rate_limit_rps,
            )
            _snapshot_project_schema(
                conn, client, project_id=project_id, last_synced=now_iso,
            )
            projects_synced += 1
        except Exception as exc:  # noqa: BLE001 — record per-project failure
            failure_msg = f"{project_id}: {type(exc).__name__}: {exc}"
            _LOGGER.warning("sync project %s failed: %s", project_id, exc)
            failures.append(failure_msg)

    status = "ok" if not failures else ("partial" if projects_synced > 0 else "failed")
    error_message = "; ".join(failures) if failures else None

    finish_sync_run(
        conn,
        run_id=run_id,
        ended_at=now_iso,
        status=status,
        projects_synced=projects_synced,
        samples_synced=samples_synced,
        error_message=error_message,
    )
    return {
        "run_id": run_id,
        "status": status,
        "projects_synced": projects_synced,
        "samples_synced": samples_synced,
        "error_message": error_message,
    }
