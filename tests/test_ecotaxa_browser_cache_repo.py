"""TDD — core/ecotaxa_browser/cache/repo.py."""

import sqlite3

import pytest


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
    )

    rows = list(conn.execute("SELECT * FROM samples_cache"))
    assert len(rows) == 1
    assert rows[0]["lat_avg"] == 70.2
    assert rows[0]["object_count"] == 130
    assert rows[0]["last_synced"] == "2026-06-16T03:00:00Z"


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
             "object_count": 10, "instrument": "UVP5"},
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
        "SELECT sample_id, object_count, last_synced FROM samples_cache "
        "WHERE project_id=42 ORDER BY sample_id"
    ))
    assert [(r["sample_id"], r["object_count"]) for r in rows_after_second] == [
        (1, 15), (3, 30)
    ]
    assert all(r["last_synced"] == "ts2" for r in rows_after_second)


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
