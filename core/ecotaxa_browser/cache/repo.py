"""SQLite repository for the EcoTaxa cache.

Schema: sample-level aggregate (lat/lon/date), project schema snapshot,
sync run history. Designed for SQLite (file or in-memory) — no spatial
extension required, bbox math is plain numeric SQL.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Sequence

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
    object_count INTEGER,
    instrument TEXT,
    last_synced TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_samples_project
    ON samples_cache(project_id);
CREATE INDEX IF NOT EXISTS idx_samples_bbox
    ON samples_cache(lat_avg, lon_avg);
CREATE INDEX IF NOT EXISTS idx_samples_date
    ON samples_cache(date_min, date_max);

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


def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they do not exist (idempotent)."""
    conn.executescript(_SCHEMA)
    _ensure_column(conn, "samples_cache", "depth_min", "REAL")
    _ensure_column(conn, "samples_cache", "depth_max", "REAL")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_samples_depth_max "
        "ON samples_cache(depth_max)"
    )
    conn.commit()


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


def upsert_sample(
    conn: sqlite3.Connection,
    *,
    sample_id: int,
    project_id: int,
    lat_avg: float | None,
    lon_avg: float | None,
    date_min: str | None,
    date_max: str | None,
    object_count: int,
    instrument: str | None,
    last_synced: str,
    depth_min: float | None = None,
    depth_max: float | None = None,
) -> None:
    """Insert or update a single sample row."""
    conn.execute(
        """
        INSERT INTO samples_cache (
            sample_id, project_id, lat_avg, lon_avg,
            date_min, date_max, depth_min, depth_max,
            object_count, instrument, last_synced
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sample_id) DO UPDATE SET
            project_id = excluded.project_id,
            lat_avg = excluded.lat_avg,
            lon_avg = excluded.lon_avg,
            date_min = excluded.date_min,
            date_max = excluded.date_max,
            depth_min = excluded.depth_min,
            depth_max = excluded.depth_max,
            object_count = excluded.object_count,
            instrument = excluded.instrument,
            last_synced = excluded.last_synced
        """,
        (
            sample_id, project_id, lat_avg, lon_avg,
            date_min, date_max, depth_min, depth_max,
            object_count, instrument, last_synced,
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
        for sample in samples:
            conn.execute(
                """
                INSERT INTO samples_cache (
                    sample_id, project_id, lat_avg, lon_avg,
                    date_min, date_max, depth_min, depth_max,
                    object_count, instrument, last_synced
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(sample["sample_id"]),
                    project_id,
                    sample.get("lat_avg"),
                    sample.get("lon_avg"),
                    sample.get("date_min"),
                    sample.get("date_max"),
                    sample.get("depth_min"),
                    sample.get("depth_max"),
                    int(sample.get("object_count") or 0),
                    sample.get("instrument"),
                    last_synced,
                ),
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
) -> Iterable[sqlite3.Row]:
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
    return conn.execute(f"SELECT * FROM samples_cache {where}", params)


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
    return conn
