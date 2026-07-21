"""Tests for cache-aware /health and /admin/resync (A2 async) endpoints."""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from core.ecotaxa_browser.cache.repo import (
    cache_counts,
    cache_needs_resync,
    finish_sync_run,
    get_schema_version,
    init_schema,
    set_schema_version,
    start_sync_run,
    upsert_sample,
    SCHEMA_VERSION,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def cache_db(tmp_path):
    path = tmp_path / "ecotaxa_cache.sqlite"
    conn = sqlite3.connect(path)
    init_schema(conn)
    conn.close()
    yield str(path)


@pytest.mark.anyio
async def test_health_reports_empty_cache_when_no_sync_yet(monkeypatch, cache_db):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("ECOTAXA_CACHE_DB", cache_db)
    from core.mcp.ecotaxa_server import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["cache"]["samples_indexed"] == 0
    assert body["cache"]["projects_indexed"] == 0
    assert body["cache"]["last_sync_status"] is None
    assert body["cache"]["cache_age_hours"] is None
    assert body["cache"]["schema_version"] == 0
    assert body["cache"]["schema_current"] is False


@pytest.mark.anyio
async def test_health_reports_cache_age_and_status_after_sync(
    monkeypatch, cache_db
):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("ECOTAXA_CACHE_DB", cache_db)
    from core.mcp.ecotaxa_server import create_app

    conn = sqlite3.connect(cache_db)
    conn.row_factory = sqlite3.Row
    upsert_sample(
        conn, sample_id=1, project_id=42, lat_avg=70.0, lon_avg=-64.0,
        date_min="d", date_max="d", object_count=10,
        instrument="UVP5", last_synced="ts",
    )
    six_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    five_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    run_id = start_sync_run(conn, started_at=six_hours_ago)
    finish_sync_run(
        conn, run_id=run_id, ended_at=five_hours_ago, status="ok",
        projects_synced=1, samples_synced=1, error_message=None,
    )
    set_schema_version(conn, SCHEMA_VERSION)
    conn.close()

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    body = response.json()
    assert response.status_code == 200
    assert body["cache"]["samples_indexed"] == 1
    assert body["cache"]["projects_indexed"] == 1
    assert body["cache"]["last_sync_status"] == "ok"
    assert 4.5 < body["cache"]["cache_age_hours"] < 5.5
    assert body["cache"]["schema_version"] == SCHEMA_VERSION
    assert body["cache"]["schema_current"] is True


@pytest.mark.anyio
async def test_admin_resync_requires_bearer(monkeypatch, cache_db):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("ECOTAXA_CACHE_DB", cache_db)
    from core.mcp.ecotaxa_server import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/admin/resync")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_admin_resync_returns_202_with_run_id(monkeypatch, cache_db):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("ECOTAXA_CACHE_DB", cache_db)

    # Patch the sync runner to be instant and deterministic.
    import core.mcp.ecotaxa_server as server

    def fake_run_sync(cache_path):
        conn = sqlite3.connect(cache_path)
        run_id = start_sync_run(conn, started_at="ts_started")
        finish_sync_run(
            conn, run_id=run_id, ended_at="ts_ended", status="ok",
            projects_synced=0, samples_synced=0, error_message=None,
        )
        conn.close()

    monkeypatch.setattr(server, "_run_full_sync_with_real_client", fake_run_sync)

    app = server.create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/admin/resync",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 202
    body = response.json()
    assert "run_id" in body
    assert body["status"] == "started"

    # Background task should complete shortly.
    await asyncio.sleep(0.1)
    conn = sqlite3.connect(cache_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT status FROM sync_runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row["status"] == "ok"


@pytest.mark.anyio
async def test_admin_sync_runs_status_endpoint(monkeypatch, cache_db):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("ECOTAXA_CACHE_DB", cache_db)

    conn = sqlite3.connect(cache_db)
    run_id = start_sync_run(conn, started_at="ts_started")
    finish_sync_run(
        conn, run_id=run_id, ended_at="ts_ended", status="partial",
        projects_synced=1, samples_synced=5, error_message="42: oops",
    )
    conn.close()

    from core.mcp.ecotaxa_server import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/admin/sync_runs/{run_id}",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["status"] == "partial"
    assert body["samples_synced"] == 5
    assert body["error_message"] == "42: oops"


@pytest.mark.anyio
async def test_admin_sync_runs_status_returns_404_when_missing(monkeypatch, cache_db):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("ECOTAXA_CACHE_DB", cache_db)

    from core.mcp.ecotaxa_server import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/admin/sync_runs/99999",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 404


# --- schema version / cache_needs_resync unit tests ---


def test_init_schema_does_not_stamp_schema_version(tmp_path):
    """init_schema migrates columns but does NOT stamp the version.

    The version is only stamped after a successful EcoTaxa sync so the boot
    logic can still detect a stale-schema cache after migrations run.
    """
    path = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(str(path))
    init_schema(conn)
    assert get_schema_version(conn) == 0  # untouched by init_schema
    conn.close()


def test_cache_needs_resync_false_after_set_schema_version(tmp_path):
    path = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(str(path))
    init_schema(conn)
    set_schema_version(conn, SCHEMA_VERSION)
    assert not cache_needs_resync(conn)
    conn.close()


def test_cache_needs_resync_true_when_version_is_zero(tmp_path):
    """Simulates an old cache built before schema versioning was introduced."""
    path = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(str(path))
    init_schema(conn)
    set_schema_version(conn, 0)
    assert cache_needs_resync(conn)
    conn.close()


def test_cache_needs_resync_true_when_version_is_stale(tmp_path):
    path = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(str(path))
    init_schema(conn)
    set_schema_version(conn, SCHEMA_VERSION - 1)
    assert cache_needs_resync(conn)
    conn.close()


def test_boot_check_triggers_resync_when_schema_stale(monkeypatch, tmp_path):
    """Boot check (cache_empty or schema_stale) is True for an outdated cache.

    The lifespan fires run_in_executor when this condition holds. We test the
    check condition directly because ASGITransport does not run ASGI lifespans.
    """
    path = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    upsert_sample(
        conn, sample_id=1, project_id=42, lat_avg=70.0, lon_avg=-64.0,
        date_min="2024-01-01", date_max="2024-01-01",
        object_count=10, instrument="UVP6", last_synced="2024-01-01T00:00:00Z",
    )
    # Simulate an old-format cache (version not yet stamped by a sync)
    set_schema_version(conn, 0)
    conn.close()

    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(path))

    from core.mcp.ecotaxa_server import _open_cache
    from core.ecotaxa_browser.cache.repo import cache_counts, cache_needs_resync

    conn = _open_cache()
    try:
        counts = cache_counts(conn)
        cache_empty = (
            counts.get("samples_indexed", 0) == 0
            and counts.get("projects_indexed", 0) == 0
        )
        schema_stale = cache_needs_resync(conn)
    finally:
        conn.close()

    assert not cache_empty, "cache has data — should not be considered empty"
    assert schema_stale, "version=0 should be detected as stale"
    assert cache_empty or schema_stale, "boot should trigger a resync"


def test_boot_check_triggers_resync_when_current_schema_cache_is_too_old(
    monkeypatch, tmp_path
):
    """Age alone refreshes an otherwise structurally current cache."""
    import core.mcp.ecotaxa_server as server

    path = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    upsert_sample(
        conn, sample_id=1, project_id=42, lat_avg=70.0, lon_avg=-64.0,
        date_min="2024-01-01", date_max="2024-01-01",
        object_count=10, instrument="UVP6", last_synced="2024-01-01T00:00:00Z",
    )
    conn.execute(
        "INSERT INTO projects_cache (project_id, title, last_synced) "
        "VALUES (42, 'test', '2024-01-01T00:00:00Z')"
    )
    set_schema_version(conn, SCHEMA_VERSION)
    conn.execute(
        "INSERT INTO sync_runs (started_at, ended_at, status, projects_synced, samples_synced) "
        "VALUES ('2024-01-01T00:00:00+00:00', '2024-01-01T01:00:00+00:00', 'ok', 1, 1)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(path))
    monkeypatch.setenv("ECOTAXA_CACHE_MAX_AGE_HOURS", "24")
    conn = server._open_cache()
    try:
        assert server._cache_requires_bootstrap(conn) is True
    finally:
        conn.close()


def test_unreadable_cache_is_quarantined_before_rebuild(tmp_path):
    """A non-SQLite cache must be preserved, never overwritten in place."""
    import core.mcp.ecotaxa_server as server

    path = tmp_path / "cache.sqlite"
    path.write_text("not a sqlite database", encoding="utf-8")

    quarantined = server._quarantine_unreadable_cache(str(path))

    assert path.exists() is False
    assert quarantined is not None
    assert quarantined.exists()
    assert quarantined.read_text(encoding="utf-8") == "not a sqlite database"
