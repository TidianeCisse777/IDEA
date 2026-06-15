"""TDD — core/ecotaxa_browser/cache/sync.py."""

import json
import sqlite3
from unittest.mock import MagicMock

import pytest

from core.ecotaxa_browser.cache.repo import (
    cache_counts,
    init_schema,
    upsert_sample,
)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_schema(connection)
    yield connection
    connection.close()


def _make_client(
    *,
    projects: list[dict],
    objects_by_project: dict[int, list[list]],
    project_details: dict[int, dict] | None = None,
):
    client = MagicMock()
    client.login.return_value = None
    client.list_projects.return_value = projects
    client.get_project.side_effect = lambda pid: (project_details or {}).get(
        pid, {"projid": pid, "title": f"Project {pid}", "instrument": "UVP5"}
    )

    def _query_objects(*, project_id, filters, fields, window_start, window_size):
        rows = objects_by_project.get(project_id, [])
        page = rows[window_start : window_start + window_size]
        return {"details": page, "total_ids": len(rows)}

    client.query_objects.side_effect = _query_objects
    return client


def test_sync_one_project_aggregates_lat_lon_date_per_sample(conn):
    from core.ecotaxa_browser.cache.sync import sync_project

    objects = [
        # [latitude, longitude, objdate, sample_id, instrument]
        [70.0, -64.0, "2018-08-01", "1", "UVP5SD"],
        [70.2, -64.4, "2018-08-03", "1", "UVP5SD"],
        [60.0, -50.0, "2018-08-10", "2", "UVP5SD"],
        [60.5, -50.5, "2018-08-15", "2", "UVP5SD"],
    ]
    client = _make_client(
        projects=[{"projid": 42, "title": "P", "instrument": "UVP5SD"}],
        objects_by_project={42: objects},
    )

    samples_synced = sync_project(conn, client, project_id=42, last_synced="ts")

    assert samples_synced == 2
    rows = list(conn.execute(
        "SELECT * FROM samples_cache WHERE project_id=42 ORDER BY sample_id"
    ))
    assert rows[0]["sample_id"] == 1
    assert rows[0]["lat_avg"] == pytest.approx(70.1)
    assert rows[0]["lon_avg"] == pytest.approx(-64.2)
    assert rows[0]["date_min"] == "2018-08-01"
    assert rows[0]["date_max"] == "2018-08-03"
    assert rows[0]["object_count"] == 2

    assert rows[1]["sample_id"] == 2
    assert rows[1]["date_min"] == "2018-08-10"
    assert rows[1]["date_max"] == "2018-08-15"


def test_sync_drops_objects_without_lat_lon_silently(conn):
    from core.ecotaxa_browser.cache.sync import sync_project

    objects = [
        [70.0, -64.0, "2018-08-01", "1", "UVP5"],
        [None, None, "2018-08-02", "1", "UVP5"],
        [None, -64.0, "2018-08-03", "1", "UVP5"],
        [70.0, None, "2018-08-04", "1", "UVP5"],
    ]
    client = _make_client(
        projects=[{"projid": 42, "title": "P", "instrument": "UVP5"}],
        objects_by_project={42: objects},
    )
    samples_synced = sync_project(conn, client, project_id=42, last_synced="ts")

    assert samples_synced == 1
    row = conn.execute("SELECT * FROM samples_cache WHERE sample_id=1").fetchone()
    assert row["object_count"] == 1
    assert row["lat_avg"] == pytest.approx(70.0)


def test_sync_paginates_until_exhausted(conn):
    from core.ecotaxa_browser.cache.sync import sync_project

    objects = [
        [70.0, -64.0, "2018-08-01", str(idx), "UVP5"]
        for idx in range(1, 11)
    ]
    client = _make_client(
        projects=[{"projid": 42, "title": "P", "instrument": "UVP5"}],
        objects_by_project={42: objects},
    )
    samples_synced = sync_project(
        conn, client, project_id=42, last_synced="ts", window_size=3,
    )
    assert samples_synced == 10
    # 10 objects / window 3 = 4 calls (3+3+3+1)
    assert client.query_objects.call_count == 4


def test_sync_respects_object_cap(conn):
    from core.ecotaxa_browser.cache.sync import sync_project

    objects = [
        [70.0, -64.0, "2018-08-01", str(idx % 5), "UVP5"]
        for idx in range(100)
    ]
    client = _make_client(
        projects=[{"projid": 42, "title": "P", "instrument": "UVP5"}],
        objects_by_project={42: objects},
    )
    samples_synced = sync_project(
        conn,
        client,
        project_id=42,
        last_synced="ts",
        window_size=10,
        object_cap=30,
    )
    # We stopped after 30 objects → only the first 30 are aggregated.
    assert client.query_objects.call_count == 3
    total_objects = sum(
        row["object_count"]
        for row in conn.execute("SELECT object_count FROM samples_cache")
    )
    assert total_objects == 30
    assert samples_synced > 0


def test_sync_project_rollback_on_failure_keeps_previous_state(conn):
    """E3: a failing project sync must not corrupt that project's existing cache."""
    from core.ecotaxa_browser.cache.sync import sync_project

    upsert_sample(
        conn, sample_id=999, project_id=42, lat_avg=10.0, lon_avg=10.0,
        date_min="prev", date_max="prev", object_count=5,
        instrument="UVP5", last_synced="ts_old",
    )

    client = MagicMock()
    client.login.return_value = None
    client.get_project.return_value = {"projid": 42, "title": "P", "instrument": "UVP5"}
    client.query_objects.side_effect = RuntimeError("EcoTaxa exploded")

    with pytest.raises(RuntimeError):
        sync_project(conn, client, project_id=42, last_synced="ts_new")

    row = conn.execute("SELECT * FROM samples_cache WHERE project_id=42").fetchone()
    assert row is not None
    assert row["sample_id"] == 999
    assert row["last_synced"] == "ts_old"


def test_run_full_sync_records_status_ok_when_all_projects_succeed(conn):
    from core.ecotaxa_browser.cache.sync import run_full_sync

    client = _make_client(
        projects=[
            {"projid": 42, "title": "A", "instrument": "UVP5"},
            {"projid": 99, "title": "B", "instrument": "UVP5"},
        ],
        objects_by_project={
            42: [[70.0, -64.0, "2018-08-01", "1", "UVP5"]],
            99: [[60.0, -50.0, "2019-08-01", "2", "UVP5"]],
        },
    )
    result = run_full_sync(conn, client, now_iso="2026-06-15T03:00:00Z")
    assert result["status"] == "ok"
    assert result["projects_synced"] == 2
    assert result["samples_synced"] == 2
    counts = cache_counts(conn)
    assert counts["samples_indexed"] == 2
    assert counts["projects_indexed"] == 2
    assert counts["schemas_indexed"] == 2


def test_run_full_sync_marks_partial_on_per_project_failure(conn):
    from core.ecotaxa_browser.cache.sync import run_full_sync

    client = _make_client(
        projects=[
            {"projid": 42, "title": "A", "instrument": "UVP5"},
            {"projid": 99, "title": "B", "instrument": "UVP5"},
        ],
        objects_by_project={42: [[70.0, -64.0, "2018-08-01", "1", "UVP5"]]},
    )

    real_side_effect = client.query_objects.side_effect

    def selective_failure(*, project_id, filters, fields, window_start, window_size):
        if project_id == 99:
            raise RuntimeError("transient 500")
        return real_side_effect(
            project_id=project_id, filters=filters, fields=fields,
            window_start=window_start, window_size=window_size,
        )

    client.query_objects.side_effect = selective_failure

    result = run_full_sync(conn, client, now_iso="2026-06-15T03:00:00Z")
    assert result["status"] == "partial"
    assert result["projects_synced"] == 1
    assert result["samples_synced"] == 1
    assert "99" in (result.get("error_message") or "")

    # Project 42's data is committed; project 99 has nothing.
    rows_42 = list(conn.execute("SELECT * FROM samples_cache WHERE project_id=42"))
    rows_99 = list(conn.execute("SELECT * FROM samples_cache WHERE project_id=99"))
    assert len(rows_42) == 1
    assert rows_99 == []


def test_run_full_sync_stores_schema_snapshot_per_project(conn):
    from core.ecotaxa_browser.cache.sync import run_full_sync

    client = _make_client(
        projects=[{"projid": 42, "title": "A", "instrument": "UVP5SD"}],
        objects_by_project={42: [[70.0, -64.0, "2018-08-01", "1", "UVP5SD"]]},
        project_details={
            42: {
                "projid": 42,
                "title": "A",
                "instrument": "UVP5SD",
                "sample_free_cols": {"profileid": "t01"},
                "acquisition_free_cols": {"pixel": "n05"},
                "obj_free_cols": {"area": "n01"},
            }
        },
    )
    run_full_sync(conn, client, now_iso="2026-06-15T03:00:00Z")

    row = conn.execute(
        "SELECT schema_json FROM project_schemas_cache WHERE project_id=42"
    ).fetchone()
    schema = json.loads(row["schema_json"])
    assert schema["instrument"] == "UVP5SD"
    assert "sample" in schema["levels"]
