"""SQLite repository for the EcoTaxa cache.

Schema: sample-level aggregate (lat/lon/date), project schema snapshot,
sync run history. Designed for SQLite (file or in-memory) — no spatial
extension required, bbox math is plain numeric SQL.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterable, Iterator, Sequence

import pandas as pd

from core.geo import assign_zones, load_registry

_GEO_REGISTRY_PATH = "data/geo/zones_registry.geojson"
_geo_registry_cache: object = None
_geo_registry_loaded = False

# Bump this integer every time the schema gains columns that require a full
# resync to populate (i.e. _ensure_column adds a column whose data must come
# from EcoTaxa, not a backfill). Stored in the SQLite user_version pragma so
# the startup code can detect an old-format cache and trigger a resync.
SCHEMA_VERSION = 3


def _load_geo_registry():
    global _geo_registry_cache, _geo_registry_loaded
    if _geo_registry_loaded:
        return _geo_registry_cache
    try:
        _geo_registry_cache = load_registry(_GEO_REGISTRY_PATH)
    except Exception:
        _geo_registry_cache = None
    _geo_registry_loaded = True
    return _geo_registry_cache

# Single source of truth for the samples_cache secondary indexes: name -> the
# indexed column expression. init_schema builds them, and the deferred-index
# bulk-load path drops and rebuilds exactly this set — keep them here so the two
# can never drift.
_SECONDARY_INDEXES = {
    "idx_samples_project": "samples_cache(project_id)",
    "idx_samples_bbox": "samples_cache(lat_avg, lon_avg)",
    "idx_samples_date": "samples_cache(date_min, date_max)",
    "idx_samples_datetime": "samples_cache(datetime_min, datetime_max)",
    "idx_samples_depth_max": "samples_cache(depth_max)",
    "idx_samples_zone": "samples_cache(iho_zone)",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS samples_cache (
    sample_id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    lat_avg REAL,
    lon_avg REAL,
    date_min TEXT,
    date_max TEXT,
    depth_min REAL,
    depth_max REAL,
    original_id TEXT,
    station_id TEXT,
    profile_id TEXT,
    free_fields_json TEXT,
    object_count INTEGER,
    nb_validated INTEGER,
    nb_predicted INTEGER,
    nb_dubious INTEGER,
    nb_unclassified INTEGER,
    used_taxa TEXT,
    instrument TEXT,
    last_synced TEXT NOT NULL,
    iho_zone TEXT,
    datetime_min TEXT,
    datetime_max TEXT,
    time_min TEXT,
    time_max TEXT,
    temporal_precision TEXT,
    missing_date_count INTEGER,
    missing_time_count INTEGER,
    missing_depth_min_count INTEGER,
    missing_depth_max_count INTEGER,
    depth_complete INTEGER,
    metadata_objects_scanned INTEGER,
    metadata_complete INTEGER,
    metadata_coverage_pct REAL
);

CREATE TABLE IF NOT EXISTS project_schemas_cache (
    project_id INTEGER PRIMARY KEY,
    schema_json TEXT NOT NULL,
    last_synced TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_signatures_cache (
    project_id INTEGER PRIMARY KEY,
    objcount INTEGER NOT NULL,
    pctvalidated REAL NOT NULL,
    pctclassified REAL NOT NULL,
    last_synced TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT,
    projects_synced INTEGER,
    samples_synced INTEGER,
    error_message TEXT
);
"""


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the stored schema version (SQLite user_version pragma)."""
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    """Persist the schema version. Called after a successful migration."""
    conn.execute(f"PRAGMA user_version = {int(version)}")
    conn.commit()


def cache_needs_resync(conn: sqlite3.Connection) -> bool:
    """True when the on-disk schema version is older than the current code.

    A stale version means columns were added by _ensure_column but existing
    rows still carry NULL for those fields — a full EcoTaxa resync is needed
    to populate them.
    """
    return get_schema_version(conn) < SCHEMA_VERSION


def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they do not exist (idempotent).

    Does NOT stamp SCHEMA_VERSION — the version is only updated after a
    successful full sync (see ecotaxa_server._run_full_sync_with_real_client).
    This lets the boot logic detect an old-format cache via cache_needs_resync
    even after init_schema has run the column migrations.
    """
    conn.executescript(_SCHEMA)
    _ensure_column(conn, "samples_cache", "lat_avg", "REAL")
    _ensure_column(conn, "samples_cache", "lon_avg", "REAL")
    _ensure_column(conn, "samples_cache", "date_min", "TEXT")
    _ensure_column(conn, "samples_cache", "date_max", "TEXT")
    _ensure_column(conn, "samples_cache", "object_count", "INTEGER")
    _ensure_column(conn, "samples_cache", "instrument", "TEXT")
    _ensure_column(conn, "samples_cache", "depth_min", "REAL")
    _ensure_column(conn, "samples_cache", "depth_max", "REAL")
    _ensure_column(conn, "samples_cache", "original_id", "TEXT")
    _ensure_column(conn, "samples_cache", "station_id", "TEXT")
    _ensure_column(conn, "samples_cache", "profile_id", "TEXT")
    _ensure_column(conn, "samples_cache", "free_fields_json", "TEXT")
    _ensure_column(conn, "samples_cache", "iho_zone", "TEXT")
    # Sample-level classification stats (from sample_taxo_stats, no object
    # download): counts per status + list of taxa present in the sample.
    _ensure_column(conn, "samples_cache", "nb_validated", "INTEGER")
    _ensure_column(conn, "samples_cache", "nb_predicted", "INTEGER")
    _ensure_column(conn, "samples_cache", "nb_dubious", "INTEGER")
    _ensure_column(conn, "samples_cache", "nb_unclassified", "INTEGER")
    _ensure_column(conn, "samples_cache", "used_taxa", "TEXT")
    deployment_columns = {
        "datetime_min": "TEXT",
        "datetime_max": "TEXT",
        "time_min": "TEXT",
        "time_max": "TEXT",
        "temporal_precision": "TEXT",
        "missing_date_count": "INTEGER",
        "missing_time_count": "INTEGER",
        "missing_depth_min_count": "INTEGER",
        "missing_depth_max_count": "INTEGER",
        "depth_complete": "INTEGER",
        "metadata_objects_scanned": "INTEGER",
        "metadata_complete": "INTEGER",
        "metadata_coverage_pct": "REAL",
    }
    for column_name, column_type in deployment_columns.items():
        _ensure_column(conn, "samples_cache", column_name, column_type)
    create_secondary_indexes(conn)
    conn.commit()


def create_secondary_indexes(conn: sqlite3.Connection) -> None:
    """Create the samples_cache secondary indexes (idempotent)."""
    for name, target in _SECONDARY_INDEXES.items():
        conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")
    conn.commit()


def drop_secondary_indexes(conn: sqlite3.Connection) -> None:
    """Drop the samples_cache secondary indexes (idempotent)."""
    for name in _SECONDARY_INDEXES:
        conn.execute(f"DROP INDEX IF EXISTS {name}")
    conn.commit()


def is_samples_cache_empty(conn: sqlite3.Connection) -> bool:
    """True when no sample rows are cached — i.e. a first-fill sync."""
    return conn.execute("SELECT 1 FROM samples_cache LIMIT 1").fetchone() is None


def backfill_iho_zones(conn: sqlite3.Connection, *, chunk_size: int = 5000) -> int:
    """Assign iho_zone to existing samples that have coordinates but no zone.

    Runs at startup after init_schema so that a real cache populated before
    the iho_zone column was added gets filled without waiting for a full re-sync.
    Processes rows in chunks to stay memory-friendly on large accounts.
    Returns the total number of rows updated.
    """
    registry = _load_geo_registry()
    if registry is None:
        return 0

    total_updated = 0
    while True:
        rows = conn.execute(
            """
            SELECT sample_id, lat_avg, lon_avg FROM samples_cache
            WHERE iho_zone IS NULL AND lat_avg IS NOT NULL AND lon_avg IS NOT NULL
            LIMIT ?
            """,
            (chunk_size,),
        ).fetchall()
        if not rows:
            break

        df = pd.DataFrame(rows, columns=["sample_id", "lat", "lon"])
        zones = assign_zones(df, registry, lat_col="lat", lon_col="lon", family="auto")
        updates = list(zip(zones.tolist(), df["sample_id"].tolist()))
        conn.executemany(
            "UPDATE samples_cache SET iho_zone = ? WHERE sample_id = ?", updates
        )
        conn.commit()
        total_updated += len(rows)

    return total_updated


@contextmanager
def deferred_secondary_indexes(conn: sqlite3.Connection) -> Iterator[None]:
    """Drop the secondary indexes for a bulk first-fill, rebuild on exit.

    Building each index once at the end (a single sorted pass) is far cheaper
    than maintaining it incrementally across a large load — ~5x faster to fill
    a multi-million-row cache from scratch. Only safe when no reader depends on
    the indexes meanwhile, so this is for an *empty-cache* first fill, not an
    incremental refresh of a populated cache. The indexes are rebuilt even if
    the body raises, so a crash mid-sync never leaves the cache index-less.
    """
    drop_secondary_indexes(conn)
    try:
        yield
    finally:
        create_secondary_indexes(conn)


def _ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    columns = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table_name})")
    }
    if column_name not in columns:
        conn.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )


def _compute_iho_zone(lat: float | None, lon: float | None) -> str | None:
    """Return the IHO/MEOW zone label for a single point, or None if no coords."""
    if lat is None or lon is None:
        return None
    registry = _load_geo_registry()
    if registry is None:
        return None
    df = pd.DataFrame({"lat": [lat], "lon": [lon]})
    zones = assign_zones(df, registry, lat_col="lat", lon_col="lon", family="auto")
    return zones.iloc[0]


def upsert_sample(
    conn: sqlite3.Connection,
    *,
    sample_id: int,
    project_id: int,
    lat_avg: float | None,
    lon_avg: float | None,
    date_min: str | None,
    date_max: str | None,
    object_count: int | None,
    instrument: str | None,
    last_synced: str,
    depth_min: float | None = None,
    depth_max: float | None = None,
    original_id: str | None = None,
    station_id: str | None = None,
    profile_id: str | None = None,
    free_fields_json: str | None = None,
    iho_zone: str | None = None,
    datetime_min: str | None = None,
    datetime_max: str | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
    temporal_precision: str | None = None,
    missing_date_count: int | None = None,
    missing_time_count: int | None = None,
    missing_depth_min_count: int | None = None,
    missing_depth_max_count: int | None = None,
    depth_complete: bool | None = None,
    metadata_objects_scanned: int | None = None,
    metadata_complete: bool | None = None,
    metadata_coverage_pct: float | None = None,
) -> None:
    """Insert or update a single sample row."""
    if iho_zone is None:
        iho_zone = _compute_iho_zone(lat_avg, lon_avg)
    conn.execute(
        """
        INSERT INTO samples_cache (
            sample_id, project_id, lat_avg, lon_avg,
            date_min, date_max, depth_min, depth_max,
            original_id, station_id, profile_id, free_fields_json,
            object_count, instrument, last_synced, iho_zone,
            datetime_min, datetime_max, time_min, time_max, temporal_precision,
            missing_date_count, missing_time_count, missing_depth_min_count,
            missing_depth_max_count, depth_complete, metadata_objects_scanned,
            metadata_complete, metadata_coverage_pct
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sample_id) DO UPDATE SET
            project_id = excluded.project_id,
            lat_avg = excluded.lat_avg,
            lon_avg = excluded.lon_avg,
            date_min = excluded.date_min,
            date_max = excluded.date_max,
            depth_min = excluded.depth_min,
            depth_max = excluded.depth_max,
            original_id = excluded.original_id,
            station_id = excluded.station_id,
            profile_id = excluded.profile_id,
            free_fields_json = excluded.free_fields_json,
            object_count = excluded.object_count,
            instrument = excluded.instrument,
            last_synced = excluded.last_synced,
            iho_zone = excluded.iho_zone,
            datetime_min = excluded.datetime_min,
            datetime_max = excluded.datetime_max,
            time_min = excluded.time_min,
            time_max = excluded.time_max,
            temporal_precision = excluded.temporal_precision,
            missing_date_count = excluded.missing_date_count,
            missing_time_count = excluded.missing_time_count,
            missing_depth_min_count = excluded.missing_depth_min_count,
            missing_depth_max_count = excluded.missing_depth_max_count,
            depth_complete = excluded.depth_complete,
            metadata_objects_scanned = excluded.metadata_objects_scanned,
            metadata_complete = excluded.metadata_complete,
            metadata_coverage_pct = excluded.metadata_coverage_pct
        """,
        (
            sample_id, project_id, lat_avg, lon_avg,
            date_min, date_max, depth_min, depth_max,
            original_id, station_id, profile_id, free_fields_json,
            object_count, instrument, last_synced, iho_zone,
            datetime_min, datetime_max, time_min, time_max, temporal_precision,
            missing_date_count, missing_time_count, missing_depth_min_count,
            missing_depth_max_count,
            int(depth_complete) if depth_complete is not None else None,
            metadata_objects_scanned,
            int(metadata_complete) if metadata_complete is not None else None,
            metadata_coverage_pct,
        ),
    )
    conn.commit()


def replace_project_samples(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    samples: Sequence[dict],
    last_synced: str,
) -> None:
    """Atomically replace the cached samples for one project.

    Drops any sample previously cached for ``project_id`` that is not in
    the new payload, then upserts the supplied rows. Wrapped in a single
    transaction — a failure mid-loop leaves the cache untouched.
    """
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM samples_cache WHERE project_id = ?", (project_id,))

        # Compute iho_zone in batch for all samples that have coordinates.
        registry = _load_geo_registry()
        lats = [s.get("lat_avg") for s in samples]
        lons = [s.get("lon_avg") for s in samples]
        if registry is not None and any(v is not None for v in lats):
            geo_df = pd.DataFrame({"lat": lats, "lon": lons})
            zone_series = assign_zones(
                geo_df, registry, lat_col="lat", lon_col="lon", family="auto"
            )
            zone_values = zone_series.tolist()
        else:
            zone_values = [None] * len(samples)

        rows = [
            (
                int(sample["sample_id"]),
                project_id,
                sample.get("lat_avg"),
                sample.get("lon_avg"),
                sample.get("date_min"),
                sample.get("date_max"),
                sample.get("depth_min"),
                sample.get("depth_max"),
                sample.get("original_id"),
                sample.get("station_id"),
                sample.get("profile_id"),
                sample.get("free_fields_json"),
                (
                    int(sample["object_count"])
                    if sample.get("object_count") is not None
                    else None
                ),
                sample.get("nb_validated"),
                sample.get("nb_predicted"),
                sample.get("nb_dubious"),
                sample.get("nb_unclassified"),
                sample.get("used_taxa"),
                sample.get("instrument"),
                last_synced,
                zone_values[i],
                sample.get("datetime_min"),
                sample.get("datetime_max"),
                sample.get("time_min"),
                sample.get("time_max"),
                sample.get("temporal_precision"),
                sample.get("missing_date_count"),
                sample.get("missing_time_count"),
                sample.get("missing_depth_min_count"),
                sample.get("missing_depth_max_count"),
                (
                    int(sample["depth_complete"])
                    if sample.get("depth_complete") is not None
                    else None
                ),
                sample.get("metadata_objects_scanned"),
                (
                    int(sample["metadata_complete"])
                    if sample.get("metadata_complete") is not None
                    else None
                ),
                sample.get("metadata_coverage_pct"),
            )
            for i, sample in enumerate(samples)
        ]
        conn.executemany(
            """
            INSERT INTO samples_cache (
                sample_id, project_id, lat_avg, lon_avg,
                date_min, date_max, depth_min, depth_max,
                original_id, station_id, profile_id, free_fields_json,
                object_count, nb_validated, nb_predicted, nb_dubious,
                nb_unclassified, used_taxa, instrument, last_synced, iho_zone,
                datetime_min, datetime_max, time_min, time_max, temporal_precision,
                missing_date_count, missing_time_count, missing_depth_min_count,
                missing_depth_max_count, depth_complete, metadata_objects_scanned,
                metadata_complete, metadata_coverage_pct
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def upsert_project_schema(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    schema_json: str,
    last_synced: str,
) -> None:
    conn.execute(
        """
        INSERT INTO project_schemas_cache (project_id, schema_json, last_synced)
        VALUES (?, ?, ?)
        ON CONFLICT(project_id) DO UPDATE SET
            schema_json = excluded.schema_json,
            last_synced = excluded.last_synced
        """,
        (project_id, schema_json, last_synced),
    )
    conn.commit()


def get_project_signature(
    conn: sqlite3.Connection, project_id: int
) -> tuple | None:
    """Return the cached (objcount, pctvalidated, pctclassified) tuple or None."""
    row = conn.execute(
        "SELECT objcount, pctvalidated, pctclassified FROM project_signatures_cache "
        "WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if not row:
        return None
    return (int(row[0]), round(float(row[1]), 4), round(float(row[2]), 4))


def project_is_fully_unenriched(
    conn: sqlite3.Connection, project_id: int
) -> bool:
    """True when the project has cached samples but not one carries taxo stats.

    Distinguishes a whole-project enrichment drop (e.g. the taxo-stats batch
    failing for a large project) from the normal case where a few samples have
    no classifiable object. Used by the incremental sync to re-sync a
    signature-unchanged project whose local rows never got enriched, instead of
    skipping it forever. Requires *some* samples so an empty project is not
    endlessly re-synced.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS total, COUNT(nb_validated) AS enriched "
        "FROM samples_cache WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if not row:
        return False
    total, enriched = int(row[0]), int(row[1])
    return total > 0 and enriched == 0


def upsert_project_signature(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    objcount: int,
    pctvalidated: float,
    pctclassified: float,
    last_synced: str,
) -> None:
    conn.execute(
        """
        INSERT INTO project_signatures_cache
            (project_id, objcount, pctvalidated, pctclassified, last_synced)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(project_id) DO UPDATE SET
            objcount = excluded.objcount,
            pctvalidated = excluded.pctvalidated,
            pctclassified = excluded.pctclassified,
            last_synced = excluded.last_synced
        """,
        (project_id, objcount, pctvalidated, pctclassified, last_synced),
    )
    conn.commit()


def query_samples_in_bbox(
    conn: sqlite3.Connection,
    *,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
) -> Iterable[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM samples_cache
        WHERE lat_avg BETWEEN ? AND ?
          AND lon_avg BETWEEN ? AND ?
        """,
        (lat_min, lat_max, lon_min, lon_max),
    )


def query_samples_in_date_range(
    conn: sqlite3.Connection,
    *,
    date_from: str,
    date_to: str,
) -> Iterable[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM samples_cache
        WHERE date_max >= ? AND date_min <= ?
        """,
        (date_from, date_to),
    )


def _build_sample_filter(
    *,
    bbox: tuple[float, float, float, float] | None = None,
    date_range: tuple[str, str] | None = None,
    instrument: str | None = None,
    project_ids: Sequence[int] | None = None,
    depth_max_lt: float | None = None,
    depth_max_gte: float | None = None,
    depth_min_lt: float | None = None,
    depth_min_gte: float | None = None,
    month: int | None = None,
) -> tuple[str, list]:
    """Build the shared WHERE clause + params for sample-level filters.

    Returns ``("WHERE ...", params)`` or ``("", [])`` when no filter applies,
    so it can be spliced into both row-fetch and aggregate queries.
    """
    clauses: list[str] = []
    params: list = []
    if bbox is not None:
        lat_min, lat_max, lon_min, lon_max = bbox
        clauses.append("lat_avg BETWEEN ? AND ?")
        params.extend([lat_min, lat_max])
        clauses.append("lon_avg BETWEEN ? AND ?")
        params.extend([lon_min, lon_max])
    if date_range is not None:
        date_from, date_to = date_range
        clauses.append("date_max >= ? AND date_min <= ?")
        params.extend([date_from, date_to])
    if month is not None:
        clauses.append(
            "CAST(strftime('%m', date_min) AS INTEGER) <= ? "
            "AND CAST(strftime('%m', date_max) AS INTEGER) >= ?"
        )
        params.extend([int(month), int(month)])
    if instrument is not None:
        clauses.append("instrument = ?")
        params.append(instrument)
    if depth_max_lt is not None:
        clauses.append("depth_max < ?")
        params.append(float(depth_max_lt))
    if depth_max_gte is not None:
        clauses.append("depth_max >= ?")
        params.append(float(depth_max_gte))
    if depth_min_lt is not None:
        clauses.append("depth_min < ?")
        params.append(float(depth_min_lt))
    if depth_min_gte is not None:
        clauses.append("depth_min >= ?")
        params.append(float(depth_min_gte))
    if project_ids:
        placeholders = ",".join("?" for _ in project_ids)
        clauses.append(f"project_id IN ({placeholders})")
        params.extend(project_ids)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def query_samples_filtered(
    conn: sqlite3.Connection,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    date_range: tuple[str, str] | None = None,
    instrument: str | None = None,
    project_ids: Sequence[int] | None = None,
    depth_max_lt: float | None = None,
    depth_max_gte: float | None = None,
    depth_min_lt: float | None = None,
    depth_min_gte: float | None = None,
    month: int | None = None,
    limit: int | None = None,
) -> Iterable[sqlite3.Row]:
    where, params = _build_sample_filter(
        bbox=bbox, date_range=date_range, instrument=instrument,
        project_ids=project_ids, depth_max_lt=depth_max_lt,
        depth_max_gte=depth_max_gte, depth_min_lt=depth_min_lt,
        depth_min_gte=depth_min_gte, month=month,
    )
    sql = f"SELECT * FROM samples_cache {where}"
    if limit is not None:
        sql += " LIMIT ?"
        params = [*params, int(limit)]
    return conn.execute(sql, params)


def resolve_samples(
    conn: sqlite3.Connection,
    *,
    reference: str,
    project_id: int | None = None,
) -> list[sqlite3.Row]:
    """Resolve one sample reference across the local EcoTaxa cache.

    Exact, case-insensitive matches are checked against the numeric sample ID,
    label, station, profile, and scalar free-field values. The caller decides
    how to render zero or multiple matches; this function never picks one.
    """
    normalized = " ".join(str(reference).strip().split()).casefold()
    if not normalized:
        return []

    rows = list(
        query_samples_filtered(
            conn,
            project_ids=[int(project_id)] if project_id is not None else None,
        )
    )
    matches: list[sqlite3.Row] = []
    for row in rows:
        candidates = {
            str(row["sample_id"]),
            row["original_id"],
            row["station_id"],
            row["profile_id"],
        }
        try:
            free_fields = json.loads(row["free_fields_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            free_fields = {}
        if isinstance(free_fields, dict):
            candidates.update(
                value for value in free_fields.values()
                if isinstance(value, (str, int, float))
            )
        if any(
            " ".join(str(candidate).strip().split()).casefold() == normalized
            for candidate in candidates
            if candidate is not None
        ):
            matches.append(row)
    return matches


def aggregate_samples_filtered(
    conn: sqlite3.Connection,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    date_range: tuple[str, str] | None = None,
    instrument: str | None = None,
    project_ids: Sequence[int] | None = None,
    depth_max_lt: float | None = None,
    depth_max_gte: float | None = None,
    depth_min_lt: float | None = None,
    depth_min_gte: float | None = None,
    month: int | None = None,
) -> dict:
    """Aggregate the filtered sample set in SQL (no row materialization).

    Returns total count, per-project breakdown (ordered by count desc),
    the date envelope, and the lat/lon centroid — everything the region
    summary needs — computed by SQLite instead of a Python pass over every
    matching row. NULL lat/lon are ignored by AVG, matching the old
    Python mean-over-non-null behaviour.
    """
    where, params = _build_sample_filter(
        bbox=bbox, date_range=date_range, instrument=instrument,
        project_ids=project_ids, depth_max_lt=depth_max_lt,
        depth_max_gte=depth_max_gte, depth_min_lt=depth_min_lt,
        depth_min_gte=depth_min_gte, month=month,
    )
    agg = conn.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            MIN(date_min) AS date_min,
            MAX(date_max) AS date_max,
            AVG(lat_avg) AS lat_c,
            AVG(lon_avg) AS lon_c
        FROM samples_cache {where}
        """,
        params,
    ).fetchone()
    breakdown_rows = conn.execute(
        f"""
        SELECT project_id, COUNT(*) AS n
        FROM samples_cache {where}
        GROUP BY project_id
        ORDER BY n DESC, project_id ASC
        """,
        params,
    ).fetchall()

    lat_c, lon_c = agg["lat_c"], agg["lon_c"]
    centroid = (lat_c, lon_c) if lat_c is not None and lon_c is not None else None
    return {
        "total": int(agg["total"]),
        "date_min": agg["date_min"],
        "date_max": agg["date_max"],
        "centroid": centroid,
        "project_breakdown": [
            (int(r["project_id"]), int(r["n"])) for r in breakdown_rows
        ],
    }


def query_project_envelopes(
    conn: sqlite3.Connection,
    project_ids: Sequence[int],
) -> dict[int, dict]:
    """Return per-project geographic + temporal envelopes from the cache.

    For each requested ``project_id`` :
        - ``n_samples`` : sample count in the cache
        - ``date_min`` / ``date_max`` : temporal envelope across samples
        - ``bbox`` : ``{south, west, north, east}`` of all sample centroids
        - ``instruments`` : sorted list of distinct instruments
        - ``sample_ids`` : list of all sample IDs in the local cache

    Projects with no samples in the cache are simply absent from the result.
    """
    if not project_ids:
        return {}
    placeholders = ",".join("?" for _ in project_ids)
    params = list(project_ids)
    envelopes = conn.execute(
        f"""
        SELECT
            project_id,
            COUNT(*) AS n_samples,
            MIN(date_min) AS date_min,
            MAX(date_max) AS date_max,
            MIN(lat_avg) AS south, MAX(lat_avg) AS north,
            MIN(lon_avg) AS west,  MAX(lon_avg) AS east
        FROM samples_cache
        WHERE project_id IN ({placeholders})
        GROUP BY project_id
        """,
        params,
    ).fetchall()

    out: dict[int, dict] = {}
    for row in envelopes:
        pid = int(row["project_id"])
        out[pid] = {
            "project_id": pid,
            "n_samples": int(row["n_samples"]),
            "date_min": row["date_min"],
            "date_max": row["date_max"],
            "bbox": {
                "south": row["south"], "west": row["west"],
                "north": row["north"], "east": row["east"],
            },
            "instruments": [],
            "sample_ids": [],
        }

    # Fill instruments + sample_ids in a single second pass.
    sample_rows = conn.execute(
        f"SELECT project_id, sample_id, instrument FROM samples_cache "
        f"WHERE project_id IN ({placeholders})",
        params,
    )
    instruments_acc: dict[int, set[str]] = {pid: set() for pid in out}
    for row in sample_rows:
        pid = int(row["project_id"])
        if pid not in out:
            continue
        out[pid]["sample_ids"].append(int(row["sample_id"]))
        if row["instrument"]:
            instruments_acc[pid].add(str(row["instrument"]))
    for pid, names in instruments_acc.items():
        out[pid]["instruments"] = sorted(names)

    return out


def audit_ecotaxa_coverage(
    conn: sqlite3.Connection,
    *,
    sparsest_limit: int = 10,
) -> dict:
    """Availability audit over the cached samples — what is thin, what is missing.

    Returns, entirely from the local cache (no network):
        - ``per_project`` : one row per project ordered by ``n_samples`` ASC
          (sparsest coverage first), with sample count, cached-object total,
          date envelope, instruments and bbox.
        - ``per_year`` : sample and project counts per calendar year.
        - ``sparsest_samples`` : the samples carrying the fewest objects (object
          counts are reliable per sample; the project-level total is sync-capped).
        - ``total_samples`` / ``total_projects``.
    """
    project_rows = conn.execute(
        """
        SELECT
            project_id,
            COUNT(*) AS n_samples,
            SUM(object_count) AS n_objects_cached,
            MIN(date_min) AS date_min,
            MAX(date_max) AS date_max,
            MIN(lat_avg) AS south, MAX(lat_avg) AS north,
            MIN(lon_avg) AS west,  MAX(lon_avg) AS east
        FROM samples_cache
        GROUP BY project_id
        ORDER BY n_samples ASC, project_id ASC
        """
    ).fetchall()

    instruments_acc: dict[int, set[str]] = {}
    for row in conn.execute(
        "SELECT DISTINCT project_id, instrument FROM samples_cache "
        "WHERE instrument IS NOT NULL AND instrument != ''"
    ):
        instruments_acc.setdefault(int(row["project_id"]), set()).add(
            str(row["instrument"])
        )

    per_project = [
        {
            "project_id": int(row["project_id"]),
            "n_samples": int(row["n_samples"]),
            "n_objects_cached": int(row["n_objects_cached"] or 0),
            "date_min": row["date_min"],
            "date_max": row["date_max"],
            "instruments": sorted(instruments_acc.get(int(row["project_id"]), set())),
            "bbox": {
                "south": row["south"], "west": row["west"],
                "north": row["north"], "east": row["east"],
            },
        }
        for row in project_rows
    ]

    per_year = [
        {
            "year": row["year"],
            "n_samples": int(row["n_samples"]),
            "n_projects": int(row["n_projects"]),
        }
        for row in conn.execute(
            """
            SELECT
                strftime('%Y', date_min) AS year,
                COUNT(*) AS n_samples,
                COUNT(DISTINCT project_id) AS n_projects
            FROM samples_cache
            WHERE date_min IS NOT NULL
            GROUP BY year
            ORDER BY year ASC
            """
        ).fetchall()
    ]

    sparsest_samples = [
        {
            "sample_id": int(row["sample_id"]),
            "project_id": int(row["project_id"]),
            "original_id": row["original_id"],
            "object_count": int(row["object_count"] or 0),
        }
        for row in conn.execute(
            """
            SELECT sample_id, project_id, original_id, object_count
            FROM samples_cache
            ORDER BY object_count ASC, sample_id ASC
            LIMIT ?
            """,
            (int(sparsest_limit),),
        ).fetchall()
    ]

    return {
        "per_project": per_project,
        "per_year": per_year,
        "sparsest_samples": sparsest_samples,
        "total_samples": sum(p["n_samples"] for p in per_project),
        "total_projects": len(per_project),
    }


def lookup_sample_projects(
    conn: sqlite3.Connection,
    sample_ids: Sequence[int],
) -> dict[int, int]:
    """Return a ``{sample_id: project_id}`` map for the given sample IDs.

    Samples not present in the cache are simply absent from the result.
    Used by the bulk-export planner to group a sample selection by its
    parent project before launching one ``query_ecotaxa`` per project.
    """
    if not sample_ids:
        return {}
    placeholders = ",".join("?" for _ in sample_ids)
    rows = conn.execute(
        f"SELECT sample_id, project_id FROM samples_cache "
        f"WHERE sample_id IN ({placeholders})",
        list(sample_ids),
    )
    return {int(row["sample_id"]): int(row["project_id"]) for row in rows}


def start_sync_run(conn: sqlite3.Connection, *, started_at: str) -> int:
    cursor = conn.execute(
        "INSERT INTO sync_runs (started_at, status) VALUES (?, ?)",
        (started_at, "running"),
    )
    conn.commit()
    return int(cursor.lastrowid)


def finish_sync_run(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    ended_at: str,
    status: str,
    projects_synced: int,
    samples_synced: int,
    error_message: str | None,
) -> None:
    conn.execute(
        """
        UPDATE sync_runs SET
            ended_at = ?,
            status = ?,
            projects_synced = ?,
            samples_synced = ?,
            error_message = ?
        WHERE run_id = ?
        """,
        (ended_at, status, projects_synced, samples_synced, error_message, run_id),
    )
    conn.commit()


def latest_sync_status(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM sync_runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def is_sync_running(sync_status: dict | None) -> bool:
    """Return True when a sync run has started but not ended."""
    if sync_status is None:
        return False
    return (
        sync_status.get("ended_at") is None
        and sync_status.get("status") in ("running", None)
    )


def cache_progress(conn: sqlite3.Connection) -> dict:
    """Return cache counts plus the latest sync progress in one payload."""
    counts = cache_counts(conn)
    last_sync = latest_sync_status(conn)
    projects_synced = (
        int(last_sync["projects_synced"])
        if last_sync and last_sync.get("projects_synced") is not None
        else counts["projects_indexed"]
    )
    samples_synced = (
        int(last_sync["samples_synced"])
        if last_sync and last_sync.get("samples_synced") is not None
        else counts["samples_indexed"]
    )
    return {
        **counts,
        "sync_running": is_sync_running(last_sync),
        "projects_synced": projects_synced,
        "samples_synced": samples_synced,
        "projects_total_estimated": None,
        "last_sync": last_sync,
    }


def project_cache_coverage(conn: sqlite3.Connection, project_id: int) -> dict:
    """Return what the local cache knows about one project (read-only).

    Lets a caller separate a *real* absence from a project that simply has
    not been indexed yet: the region/time/taxon browsers only read this cache,
    so an un-synced project looks empty even when it exists on EcoTaxa.

    Keys: ``project_id``, ``in_schema_cache`` (the project schema snapshot is
    present), ``n_samples_cached``, ``date_min`` / ``date_max`` (cached temporal
    envelope for the project, or ``None``), and ``last_sync`` (latest sync run
    payload or ``None``).
    """
    pid = int(project_id)
    row = conn.execute(
        "SELECT COUNT(*) AS n, MIN(date_min) AS date_min, MAX(date_max) AS date_max "
        "FROM samples_cache WHERE project_id = ?",
        (pid,),
    ).fetchone()
    n_samples = int(row["n"]) if row is not None else 0
    in_schema = (
        conn.execute(
            "SELECT 1 FROM project_schemas_cache WHERE project_id = ? LIMIT 1",
            (pid,),
        ).fetchone()
        is not None
    )
    return {
        "project_id": pid,
        "in_schema_cache": in_schema,
        "n_samples_cached": n_samples,
        "date_min": row["date_min"] if row is not None else None,
        "date_max": row["date_max"] if row is not None else None,
        "last_sync": latest_sync_status(conn),
    }


def cache_counts(conn: sqlite3.Connection) -> dict:
    samples = conn.execute("SELECT COUNT(*) FROM samples_cache").fetchone()[0]
    projects = conn.execute(
        "SELECT COUNT(DISTINCT project_id) FROM samples_cache"
    ).fetchone()[0]
    schemas = conn.execute("SELECT COUNT(*) FROM project_schemas_cache").fetchone()[0]
    return {
        "samples_indexed": int(samples),
        "projects_indexed": int(projects),
        "schemas_indexed": int(schemas),
    }


def open_connection(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # busy_timeout makes a reader wait out the brief write-lock window of a
    # sync's per-project transaction instead of raising "database is locked".
    # (Rollback journal is kept on purpose: WAL grows unbounded during a full
    # sync because continuous readers starve the passive checkpoint — see
    # docs/mcp note. A concurrent-read benchmark shows this timeout alone
    # yields zero lock errors at 500k+ rows.)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
