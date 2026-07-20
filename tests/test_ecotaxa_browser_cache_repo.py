"""TDD — core/ecotaxa_browser/cache/repo.py."""

import sqlite3

import pytest


DEPLOYMENT_COLUMNS = {
    "datetime_min", "datetime_max", "time_min", "time_max",
    "temporal_precision", "missing_date_count", "missing_time_count",
    "missing_depth_min_count", "missing_depth_max_count", "depth_complete",
    "metadata_objects_scanned", "metadata_complete", "metadata_coverage_pct",
}


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def test_init_schema_creates_required_tables(conn):
    from core.ecotaxa_browser.cache.repo import init_schema

    init_schema(conn)
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {
        "samples_cache",
        "project_schemas_cache",
        "project_signatures_cache",
        "sync_runs",
    }.issubset(tables)


def test_init_schema_is_idempotent(conn):
    from core.ecotaxa_browser.cache.repo import init_schema

    init_schema(conn)
    init_schema(conn)  # second call must not raise
    count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='samples_cache'"
    ).fetchone()[0]
    assert count == 1


def test_init_schema_migrates_existing_samples_cache_with_light_sample_metadata_columns(conn):
    from core.ecotaxa_browser.cache.repo import init_schema

    conn.execute(
        """
        CREATE TABLE samples_cache (
            sample_id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            lat_avg REAL,
            lon_avg REAL,
            date_min TEXT,
            date_max TEXT,
            object_count INTEGER,
            instrument TEXT,
            last_synced TEXT NOT NULL
        )
        """
    )
    conn.commit()

    init_schema(conn)

    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(samples_cache)")
    }
    assert {
        "depth_min",
        "depth_max",
        "original_id",
        "station_id",
        "profile_id",
        "free_fields_json",
    }.issubset(columns)
    assert DEPLOYMENT_COLUMNS <= columns


def test_init_schema_migrates_sample_deployment_metadata_columns(conn):
    from core.ecotaxa_browser.cache.repo import init_schema

    conn.execute(
        "CREATE TABLE samples_cache (sample_id INTEGER PRIMARY KEY, "
        "project_id INTEGER NOT NULL, last_synced TEXT NOT NULL)"
    )
    init_schema(conn)

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(samples_cache)")}
    indexes = {row["name"] for row in conn.execute("PRAGMA index_list(samples_cache)")}
    assert DEPLOYMENT_COLUMNS <= columns
    assert "idx_samples_datetime" in indexes


def test_upsert_sample_round_trips_deployment_metadata(conn):
    from core.ecotaxa_browser.cache.repo import init_schema, upsert_sample

    init_schema(conn)
    upsert_sample(
        conn,
        sample_id=42,
        project_id=7,
        lat_avg=67.0,
        lon_avg=-63.0,
        date_min="2015-05-22",
        date_max="2015-05-22",
        object_count=10,
        instrument="UVP5",
        last_synced="ts",
        datetime_min="2015-05-22T14:03:58",
        datetime_max="2015-05-22T14:08:01",
        time_min="14:03:58",
        time_max="14:08:01",
        temporal_precision="datetime",
        missing_date_count=0,
        missing_time_count=0,
        missing_depth_min_count=0,
        missing_depth_max_count=0,
        depth_complete=True,
        metadata_objects_scanned=10,
        metadata_complete=True,
        metadata_coverage_pct=100.0,
    )

    row = conn.execute("SELECT * FROM samples_cache WHERE sample_id=42").fetchone()
    assert row["datetime_min"] == "2015-05-22T14:03:58"
    assert row["time_max"] == "14:08:01"
    assert row["metadata_complete"] == 1
    assert row["depth_complete"] == 1
    assert row["metadata_coverage_pct"] == pytest.approx(100.0)


def test_upsert_sample_preserves_unknown_authoritative_counts_as_null(conn):
    from core.ecotaxa_browser.cache.repo import init_schema, upsert_sample

    init_schema(conn)
    upsert_sample(
        conn,
        sample_id=42,
        project_id=7,
        lat_avg=None,
        lon_avg=None,
        date_min=None,
        date_max=None,
        object_count=None,
        instrument="UVP5",
        last_synced="ts",
        metadata_objects_scanned=3,
        metadata_complete=None,
        metadata_coverage_pct=None,
    )

    row = conn.execute("SELECT * FROM samples_cache WHERE sample_id=42").fetchone()
    assert row["object_count"] is None
    assert row["metadata_complete"] is None
    assert row["metadata_coverage_pct"] is None


def test_replace_project_samples_persists_deployment_metadata(conn):
    from core.ecotaxa_browser.cache.repo import init_schema, replace_project_samples

    init_schema(conn)
    replace_project_samples(
        conn,
        project_id=7,
        samples=[{
            "sample_id": 42,
            "lat_avg": 67.0,
            "lon_avg": -63.0,
            "date_min": "2015-05-22",
            "date_max": "2015-05-22",
            "object_count": None,
            "instrument": "UVP5",
            "datetime_min": "2015-05-22T14:03:58",
            "datetime_max": "2015-05-22T14:08:01",
            "time_min": "14:03:58",
            "time_max": "14:08:01",
            "temporal_precision": "datetime",
            "missing_date_count": 0,
            "missing_time_count": 0,
            "missing_depth_min_count": 0,
            "missing_depth_max_count": 0,
            "depth_complete": True,
            "metadata_objects_scanned": 10,
            "metadata_complete": True,
            "metadata_coverage_pct": 100.0,
            "station_id": "station-1",
            "profile_id": "profile-1",
        }],
        last_synced="ts",
    )

    row = conn.execute("SELECT * FROM samples_cache WHERE sample_id=42").fetchone()
    assert row["object_count"] is None
    assert row["datetime_max"] == "2015-05-22T14:08:01"
    assert row["metadata_objects_scanned"] == 10
    assert row["metadata_complete"] == 1
    assert row["station_id"] == "station-1"
    assert row["profile_id"] == "profile-1"


def test_upsert_sample_inserts_and_then_updates(conn):
    from core.ecotaxa_browser.cache.repo import init_schema, upsert_sample

    init_schema(conn)
    upsert_sample(
        conn,
        sample_id=42000001,
        project_id=42,
        lat_avg=70.1,
        lon_avg=-64.5,
        date_min="2018-08-01",
        date_max="2018-08-30",
        object_count=120,
        instrument="UVP5SD",
        last_synced="2026-06-15T03:00:00Z",
        original_id="gn2015_l2_001",
        station_id="ice-camp",
        profile_id="001",
        free_fields_json='{"stationid": "ice-camp", "profileid": "001"}',
    )
    upsert_sample(
        conn,
        sample_id=42000001,
        project_id=42,
        lat_avg=70.2,
        lon_avg=-64.6,
        date_min="2018-08-01",
        date_max="2018-09-05",
        object_count=130,
        instrument="UVP5SD",
        last_synced="2026-06-16T03:00:00Z",
        original_id="gn2015_l2_001b",
        station_id="station-b",
        profile_id="001b",
        free_fields_json='{"stationid": "station-b", "profileid": "001b"}',
    )

    rows = list(conn.execute("SELECT * FROM samples_cache"))
    assert len(rows) == 1
    assert rows[0]["lat_avg"] == 70.2
    assert rows[0]["object_count"] == 130
    assert rows[0]["last_synced"] == "2026-06-16T03:00:00Z"
    assert rows[0]["original_id"] == "gn2015_l2_001b"
    assert rows[0]["station_id"] == "station-b"
    assert rows[0]["profile_id"] == "001b"
    assert rows[0]["free_fields_json"] == '{"stationid": "station-b", "profileid": "001b"}'


def test_audit_ecotaxa_coverage_ranks_projects_and_years(conn):
    from core.ecotaxa_browser.cache.repo import (
        audit_ecotaxa_coverage,
        init_schema,
        upsert_sample,
    )

    init_schema(conn)
    # Projet 42 : 1 sample (le plus rare), 2015.
    upsert_sample(
        conn, sample_id=1, project_id=42, lat_avg=67.0, lon_avg=-63.0,
        date_min="2015-04-19", date_max="2015-04-19", object_count=50,
        instrument="UVP5", last_synced="ts",
    )
    # Projet 17498 : 3 samples, 2024.
    for sid, oc in ((10, 5000), (11, 300), (12, 120)):
        upsert_sample(
            conn, sample_id=sid, project_id=17498, lat_avg=80.0, lon_avg=-70.0,
            date_min="2024-09-10", date_max="2024-09-10", object_count=oc,
            instrument="UVP6", last_synced="ts",
        )

    audit = audit_ecotaxa_coverage(conn)

    # Projets classés par n_samples croissant : le plus pauvre d'abord.
    per_project = audit["per_project"]
    assert per_project[0]["project_id"] == 42
    assert per_project[0]["n_samples"] == 1
    assert per_project[-1]["project_id"] == 17498
    assert per_project[-1]["n_samples"] == 3

    # Distribution temporelle par année.
    per_year = {row["year"]: row for row in audit["per_year"]}
    assert per_year["2015"]["n_samples"] == 1
    assert per_year["2024"]["n_samples"] == 3
    assert per_year["2024"]["n_projects"] == 1

    # Samples les plus pauvres en objets (fiable au niveau sample).
    sparsest = audit["sparsest_samples"]
    assert sparsest[0]["sample_id"] == 1  # object_count 50
    assert sparsest[0]["object_count"] == 50

    assert audit["total_samples"] == 4
    assert audit["total_projects"] == 2


def test_query_samples_in_bbox_returns_inclusive_borders(conn):
    from core.ecotaxa_browser.cache.repo import init_schema, query_samples_in_bbox, upsert_sample

    init_schema(conn)
    upsert_sample(
        conn, sample_id=1, project_id=42, lat_avg=70.0, lon_avg=-64.0,
        date_min="2018-08-01", date_max="2018-08-01", object_count=10,
        instrument="UVP5", last_synced="ts",
    )
    upsert_sample(
        conn, sample_id=2, project_id=42, lat_avg=55.0, lon_avg=-70.0,
        date_min="2018-08-01", date_max="2018-08-01", object_count=10,
        instrument="UVP5", last_synced="ts",
    )
    upsert_sample(
        conn, sample_id=3, project_id=42, lat_avg=75.0, lon_avg=-55.0,
        date_min="2018-08-01", date_max="2018-08-01", object_count=10,
        instrument="UVP5", last_synced="ts",
    )

    result = list(query_samples_in_bbox(
        conn, lat_min=55.0, lat_max=75.0, lon_min=-70.0, lon_max=-55.0,
    ))
    sample_ids = sorted(r["sample_id"] for r in result)
    assert sample_ids == [1, 2, 3]


def test_query_samples_in_date_range_filters_correctly(conn):
    from core.ecotaxa_browser.cache.repo import init_schema, query_samples_in_date_range, upsert_sample

    init_schema(conn)
    upsert_sample(
        conn, sample_id=1, project_id=42, lat_avg=70.0, lon_avg=-64.0,
        date_min="2018-08-01", date_max="2018-08-10", object_count=10,
        instrument="UVP5", last_synced="ts",
    )
    upsert_sample(
        conn, sample_id=2, project_id=42, lat_avg=70.0, lon_avg=-64.0,
        date_min="2019-09-01", date_max="2019-09-10", object_count=10,
        instrument="UVP5", last_synced="ts",
    )
    upsert_sample(
        conn, sample_id=3, project_id=42, lat_avg=70.0, lon_avg=-64.0,
        date_min="2020-07-01", date_max="2020-07-10", object_count=10,
        instrument="UVP5", last_synced="ts",
    )

    result = list(query_samples_in_date_range(
        conn, date_from="2018-01-01", date_to="2019-12-31",
    ))
    sample_ids = sorted(r["sample_id"] for r in result)
    assert sample_ids == [1, 2]


def test_query_samples_combined_filters(conn):
    from core.ecotaxa_browser.cache.repo import init_schema, query_samples_filtered, upsert_sample

    init_schema(conn)
    upsert_sample(
        conn, sample_id=1, project_id=42, lat_avg=70.0, lon_avg=-64.0,
        date_min="2018-08-01", date_max="2018-08-10", object_count=10,
        instrument="UVP5SD", last_synced="ts",
    )
    upsert_sample(
        conn, sample_id=2, project_id=42, lat_avg=70.0, lon_avg=-64.0,
        date_min="2018-08-01", date_max="2018-08-10", object_count=10,
        instrument="UVP6", last_synced="ts",
    )
    upsert_sample(
        conn, sample_id=3, project_id=42, lat_avg=50.0, lon_avg=-50.0,
        date_min="2018-08-01", date_max="2018-08-10", object_count=10,
        instrument="UVP5SD", last_synced="ts",
    )

    result = list(query_samples_filtered(
        conn,
        bbox=(60.0, 80.0, -70.0, -60.0),
        date_range=("2018-01-01", "2019-01-01"),
        instrument="UVP5SD",
    ))
    sample_ids = sorted(r["sample_id"] for r in result)
    assert sample_ids == [1]


def test_replace_project_samples_drops_obsolete_rows(conn):
    from core.ecotaxa_browser.cache.repo import init_schema, replace_project_samples

    init_schema(conn)
    replace_project_samples(
        conn,
        project_id=42,
        samples=[
            {"sample_id": 1, "lat_avg": 70.0, "lon_avg": -64.0,
             "date_min": "2018-08-01", "date_max": "2018-08-10",
             "object_count": 10, "instrument": "UVP5",
             "original_id": "sample-1", "station_id": "station-1",
             "profile_id": "profile-1", "free_fields_json": '{"stationid": "station-1"}'},
            {"sample_id": 2, "lat_avg": 71.0, "lon_avg": -63.0,
             "date_min": "2018-08-05", "date_max": "2018-08-12",
             "object_count": 20, "instrument": "UVP5"},
        ],
        last_synced="ts1",
    )
    rows_after_first = list(conn.execute(
        "SELECT sample_id FROM samples_cache WHERE project_id=42"
    ))
    assert sorted(r["sample_id"] for r in rows_after_first) == [1, 2]

    replace_project_samples(
        conn,
        project_id=42,
        samples=[
            {"sample_id": 1, "lat_avg": 70.0, "lon_avg": -64.0,
             "date_min": "2018-08-01", "date_max": "2018-08-10",
             "object_count": 15, "instrument": "UVP5"},
            {"sample_id": 3, "lat_avg": 72.0, "lon_avg": -65.0,
             "date_min": "2018-08-20", "date_max": "2018-08-25",
             "object_count": 30, "instrument": "UVP5"},
        ],
        last_synced="ts2",
    )
    rows_after_second = list(conn.execute(
        "SELECT sample_id, object_count, last_synced, original_id, station_id, "
        "profile_id, free_fields_json FROM samples_cache "
        "WHERE project_id=42 ORDER BY sample_id"
    ))
    assert [(r["sample_id"], r["object_count"]) for r in rows_after_second] == [
        (1, 15), (3, 30)
    ]
    assert all(r["last_synced"] == "ts2" for r in rows_after_second)
    assert rows_after_second[0]["original_id"] is None
    assert rows_after_second[0]["station_id"] is None


def test_replace_project_samples_is_transactional(conn):
    from core.ecotaxa_browser.cache.repo import init_schema, replace_project_samples, upsert_sample

    init_schema(conn)
    upsert_sample(
        conn, sample_id=1, project_id=42, lat_avg=70.0, lon_avg=-64.0,
        date_min="2018-08-01", date_max="2018-08-10", object_count=10,
        instrument="UVP5", last_synced="ts_baseline",
    )
    bad_payload = [
        {"sample_id": 2, "lat_avg": 71.0, "lon_avg": -63.0,
         "date_min": "ok", "date_max": "ok", "object_count": 20, "instrument": "x"},
        {"sample_id": "NOT_AN_INT", "lat_avg": 71.0, "lon_avg": -63.0,
         "date_min": "ok", "date_max": "ok", "object_count": 20, "instrument": "x"},
    ]
    with pytest.raises(Exception):
        replace_project_samples(conn, project_id=42, samples=bad_payload, last_synced="ts_fail")

    surviving = list(conn.execute(
        "SELECT sample_id, last_synced FROM samples_cache WHERE project_id=42"
    ))
    assert len(surviving) == 1
    assert surviving[0]["sample_id"] == 1
    assert surviving[0]["last_synced"] == "ts_baseline"


def test_upsert_project_schema_inserts_and_updates(conn):
    from core.ecotaxa_browser.cache.repo import init_schema, upsert_project_schema

    init_schema(conn)
    upsert_project_schema(
        conn,
        project_id=42,
        schema_json='{"title": "v1"}',
        last_synced="2026-06-15T03:00:00Z",
    )
    upsert_project_schema(
        conn,
        project_id=42,
        schema_json='{"title": "v2"}',
        last_synced="2026-06-16T03:00:00Z",
    )
    row = conn.execute(
        "SELECT schema_json, last_synced FROM project_schemas_cache WHERE project_id=42"
    ).fetchone()
    assert row["schema_json"] == '{"title": "v2"}'
    assert row["last_synced"] == "2026-06-16T03:00:00Z"


def test_project_signature_inserts_updates_and_reads_rounded_tuple(conn):
    from core.ecotaxa_browser.cache.repo import (
        get_project_signature,
        init_schema,
        upsert_project_signature,
    )

    init_schema(conn)
    assert get_project_signature(conn, 42) is None

    upsert_project_signature(
        conn,
        project_id=42,
        objcount=100,
        pctvalidated=12.345678,
        pctclassified=98.765432,
        last_synced="2026-06-15T03:00:00Z",
    )
    assert get_project_signature(conn, 42) == (100, 12.3457, 98.7654)

    upsert_project_signature(
        conn,
        project_id=42,
        objcount=101,
        pctvalidated=12.0,
        pctclassified=99.0,
        last_synced="2026-06-16T03:00:00Z",
    )

    assert get_project_signature(conn, 42) == (101, 12.0, 99.0)


def test_start_and_finish_sync_run_record_status(conn):
    from core.ecotaxa_browser.cache.repo import (
        init_schema,
        finish_sync_run,
        start_sync_run,
    )

    init_schema(conn)
    run_id = start_sync_run(conn, started_at="2026-06-15T03:00:00Z")
    assert isinstance(run_id, int)
    running = conn.execute(
        "SELECT status, ended_at FROM sync_runs WHERE run_id=?",
        (run_id,),
    ).fetchone()
    assert running["status"] == "running"
    assert running["ended_at"] is None
    finish_sync_run(
        conn,
        run_id=run_id,
        ended_at="2026-06-15T03:04:00Z",
        status="ok",
        projects_synced=7,
        samples_synced=320,
        error_message=None,
    )
    row = conn.execute(
        "SELECT status, projects_synced, samples_synced FROM sync_runs WHERE run_id=?",
        (run_id,),
    ).fetchone()
    assert row["status"] == "ok"
    assert row["projects_synced"] == 7
    assert row["samples_synced"] == 320


def test_cache_progress_reports_running_sync(conn):
    from core.ecotaxa_browser.cache.repo import (
        cache_progress,
        init_schema,
        start_sync_run,
        upsert_sample,
    )

    init_schema(conn)
    upsert_sample(
        conn,
        sample_id=1,
        project_id=42,
        lat_avg=70.0,
        lon_avg=-64.0,
        date_min="d",
        date_max="d",
        object_count=10,
        instrument="UVP5",
        last_synced="ts",
    )
    start_sync_run(conn, started_at="2026-06-15T03:00:00Z")

    progress = cache_progress(conn)

    assert progress["sync_running"] is True
    assert progress["projects_indexed"] == 1
    assert progress["samples_indexed"] == 1
    assert progress["projects_synced"] == 1
    assert progress["samples_synced"] == 1
    assert progress["projects_total_estimated"] is None
    assert progress["last_sync"]["status"] == "running"


def test_latest_sync_status_returns_most_recent(conn):
    from core.ecotaxa_browser.cache.repo import (
        finish_sync_run,
        init_schema,
        latest_sync_status,
        start_sync_run,
    )

    init_schema(conn)
    r1 = start_sync_run(conn, started_at="2026-06-14T03:00:00Z")
    finish_sync_run(conn, run_id=r1, ended_at="2026-06-14T03:05:00Z",
                    status="ok", projects_synced=7, samples_synced=300,
                    error_message=None)
    r2 = start_sync_run(conn, started_at="2026-06-15T03:00:00Z")
    finish_sync_run(conn, run_id=r2, ended_at="2026-06-15T03:06:00Z",
                    status="partial", projects_synced=6, samples_synced=310,
                    error_message="project 9999 failed")

    latest = latest_sync_status(conn)
    assert latest["status"] == "partial"
    assert latest["samples_synced"] == 310
    assert latest["ended_at"] == "2026-06-15T03:06:00Z"


def test_cache_counts_returns_indexed_sizes(conn):
    from core.ecotaxa_browser.cache.repo import (
        cache_counts,
        init_schema,
        upsert_project_schema,
        upsert_sample,
    )

    init_schema(conn)
    upsert_sample(conn, sample_id=1, project_id=42, lat_avg=70.0, lon_avg=-64.0,
                  date_min="d", date_max="d", object_count=10,
                  instrument="UVP5", last_synced="ts")
    upsert_sample(conn, sample_id=2, project_id=42, lat_avg=70.0, lon_avg=-64.0,
                  date_min="d", date_max="d", object_count=10,
                  instrument="UVP5", last_synced="ts")
    upsert_sample(conn, sample_id=3, project_id=99, lat_avg=70.0, lon_avg=-64.0,
                  date_min="d", date_max="d", object_count=10,
                  instrument="UVP5", last_synced="ts")
    upsert_project_schema(conn, project_id=42, schema_json="{}", last_synced="ts")

    counts = cache_counts(conn)
    assert counts["samples_indexed"] == 3
    assert counts["projects_indexed"] == 2  # distinct project_id in samples_cache
    assert counts["schemas_indexed"] == 1


def _seed_rows(conn, rows):
    from core.ecotaxa_browser.cache.repo import upsert_sample

    for row in rows:
        upsert_sample(
            conn,
            sample_id=row["sample_id"],
            project_id=row.get("project_id", 42),
            lat_avg=row.get("lat_avg", 70.0),
            lon_avg=row.get("lon_avg", -64.0),
            date_min=row.get("date_min", "2018-08-01"),
            date_max=row.get("date_max", "2018-08-10"),
            object_count=row.get("object_count", 10),
            instrument=row.get("instrument", "UVP5"),
            last_synced="ts",
        )


def test_query_samples_filtered_respects_limit(conn):
    from core.ecotaxa_browser.cache.repo import init_schema, query_samples_filtered

    init_schema(conn)
    _seed_rows(conn, [{"sample_id": i} for i in range(1, 11)])

    unlimited = list(query_samples_filtered(conn))
    limited = list(query_samples_filtered(conn, limit=3))

    assert len(unlimited) == 10
    assert len(limited) == 3


def test_aggregate_samples_filtered_returns_total_breakdown_dates_centroid(conn):
    from core.ecotaxa_browser.cache.repo import (
        aggregate_samples_filtered,
        init_schema,
    )

    init_schema(conn)
    _seed_rows(conn, [
        {"sample_id": 1, "project_id": 42, "lat_avg": 60.0, "lon_avg": -80.0,
         "date_min": "2018-01-01", "date_max": "2018-01-10"},
        {"sample_id": 2, "project_id": 42, "lat_avg": 62.0, "lon_avg": -82.0,
         "date_min": "2019-05-01", "date_max": "2019-05-10"},
        {"sample_id": 3, "project_id": 99, "lat_avg": 64.0, "lon_avg": -84.0,
         "date_min": "2017-03-01", "date_max": "2020-06-30"},
    ])

    agg = aggregate_samples_filtered(conn)

    assert agg["total"] == 3
    # ordered by count desc: project 42 (2) before project 99 (1)
    assert agg["project_breakdown"] == [(42, 2), (99, 1)]
    assert agg["date_min"] == "2017-03-01"
    assert agg["date_max"] == "2020-06-30"
    # centroid is the mean of the three lat/lon pairs
    assert agg["centroid"] == (62.0, -82.0)


def test_aggregate_samples_filtered_honours_filters(conn):
    from core.ecotaxa_browser.cache.repo import (
        aggregate_samples_filtered,
        init_schema,
    )

    init_schema(conn)
    _seed_rows(conn, [
        {"sample_id": 1, "project_id": 42, "lat_avg": 70.0, "lon_avg": -64.0,
         "instrument": "UVP6"},
        {"sample_id": 2, "project_id": 42, "lat_avg": 70.0, "lon_avg": -64.0,
         "instrument": "UVP5"},
    ])

    agg = aggregate_samples_filtered(conn, instrument="UVP6")

    assert agg["total"] == 1
    assert agg["project_breakdown"] == [(42, 1)]


def test_aggregate_samples_filtered_empty_returns_none_centroid(conn):
    from core.ecotaxa_browser.cache.repo import (
        aggregate_samples_filtered,
        init_schema,
    )

    init_schema(conn)

    agg = aggregate_samples_filtered(conn)

    assert agg["total"] == 0
    assert agg["project_breakdown"] == []
    assert agg["centroid"] is None
    assert agg["date_min"] is None


def test_open_connection_sets_busy_timeout(tmp_path):
    from core.ecotaxa_browser.cache.repo import open_connection

    db = tmp_path / "cache.sqlite"
    connection = open_connection(str(db))
    try:
        timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == 5000
    finally:
        connection.close()


def _secondary_index_names(conn):
    return {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_samples_%'"
        )
    }


def test_init_schema_creates_the_declared_secondary_indexes(conn):
    from core.ecotaxa_browser.cache.repo import _SECONDARY_INDEXES, init_schema

    init_schema(conn)
    assert _secondary_index_names(conn) == set(_SECONDARY_INDEXES)


def test_drop_and_create_secondary_indexes_round_trip(conn):
    from core.ecotaxa_browser.cache.repo import (
        _SECONDARY_INDEXES,
        create_secondary_indexes,
        drop_secondary_indexes,
        init_schema,
    )

    init_schema(conn)
    drop_secondary_indexes(conn)
    assert _secondary_index_names(conn) == set()
    create_secondary_indexes(conn)
    assert _secondary_index_names(conn) == set(_SECONDARY_INDEXES)


def test_is_samples_cache_empty(conn):
    from core.ecotaxa_browser.cache.repo import (
        init_schema,
        is_samples_cache_empty,
        upsert_sample,
    )

    init_schema(conn)
    assert is_samples_cache_empty(conn) is True
    upsert_sample(
        conn, sample_id=1, project_id=42, lat_avg=70.0, lon_avg=-64.0,
        date_min="2018-08-01", date_max="2018-08-01", object_count=10,
        instrument="UVP5", last_synced="ts",
    )
    assert is_samples_cache_empty(conn) is False


def test_deferred_secondary_indexes_drops_then_rebuilds(conn):
    from core.ecotaxa_browser.cache.repo import (
        _SECONDARY_INDEXES,
        deferred_secondary_indexes,
        init_schema,
        query_samples_in_bbox,
        upsert_sample,
    )

    init_schema(conn)
    with deferred_secondary_indexes(conn):
        # Indexes are gone during the bulk load.
        assert _secondary_index_names(conn) == set()
        upsert_sample(
            conn, sample_id=1, project_id=42, lat_avg=70.0, lon_avg=-64.0,
            date_min="2018-08-01", date_max="2018-08-01", object_count=10,
            instrument="UVP5", last_synced="ts",
        )
    # Rebuilt on exit, and reads through the index still return the row.
    assert _secondary_index_names(conn) == set(_SECONDARY_INDEXES)
    rows = list(query_samples_in_bbox(
        conn, lat_min=60.0, lat_max=75.0, lon_min=-70.0, lon_max=-60.0,
    ))
    assert [r["sample_id"] for r in rows] == [1]


def test_deferred_secondary_indexes_rebuilds_even_on_error(conn):
    from core.ecotaxa_browser.cache.repo import (
        _SECONDARY_INDEXES,
        deferred_secondary_indexes,
        init_schema,
    )

    init_schema(conn)
    with pytest.raises(RuntimeError):
        with deferred_secondary_indexes(conn):
            raise RuntimeError("load blew up mid-sync")
    # A crash mid-load must not leave the cache permanently index-less.
    assert _secondary_index_names(conn) == set(_SECONDARY_INDEXES)
