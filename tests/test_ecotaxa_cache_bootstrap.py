"""Bootstrap contract for the canonical EcoTaxa SQLite cache."""

from __future__ import annotations

import sqlite3

import pytest

from core.ecotaxa_browser.cache.repo import SCHEMA_VERSION, get_schema_version


class DeterministicSyncClient:
    """Small local EcoTaxa double that always returns one complete sample."""

    project = {
        "projid": 42,
        "title": "Deterministic project",
        "instrument": "UVP5",
        "objcount": 1,
        "pctvalidated": 100.0,
        "pctclassified": 100.0,
    }

    def login(self) -> None:
        return None

    def list_projects(self) -> list[dict]:
        return [dict(self.project)]

    def get_project(self, project_id: int) -> dict:
        assert project_id == 42
        return dict(self.project)

    def list_samples(self, project_id: int) -> list[dict]:
        assert project_id == 42
        return [
            {
                "sampleid": 42000001,
                "projid": 42,
                "orig_id": "sample_001",
                "latitude": 67.0,
                "longitude": -63.0,
                "free_columns": {},  # always empty from search endpoint
            }
        ]

    def get_sample(self, sample_id: int) -> dict:
        assert sample_id == 42000001
        return {
            "sampleid": 42000001,
            "projid": 42,
            "orig_id": "sample_001",
            "latitude": 67.0,
            "longitude": -63.0,
            "free_columns": {
                "stationid": "station-1",
                "profileid": "profile-1",
                "sampledatetime": "20150522-140358",
            },
        }

    def sample_taxo_stats(self, sample_ids: list[int]) -> list[dict]:
        assert sample_ids == [42000001]
        return [
            {
                "sample_id": 42000001,
                "nb_validated": 1,
                "nb_predicted": 0,
                "nb_dubious": 0,
                "nb_unclassified": 0,
                "used_taxa": [25828],
            }
        ]


def _create_v2_cache(path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE samples_cache (
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
            iho_zone TEXT
        );
        CREATE TABLE project_schemas_cache (
            project_id INTEGER PRIMARY KEY,
            schema_json TEXT NOT NULL,
            last_synced TEXT NOT NULL
        );
        CREATE TABLE project_signatures_cache (
            project_id INTEGER PRIMARY KEY,
            objcount INTEGER NOT NULL,
            pctvalidated REAL NOT NULL,
            pctclassified REAL NOT NULL,
            last_synced TEXT NOT NULL
        );
        CREATE TABLE sync_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT,
            projects_synced INTEGER,
            samples_synced INTEGER,
            error_message TEXT
        );
        INSERT INTO samples_cache (
            sample_id, project_id, lat_avg, lon_avg, date_min, date_max,
            depth_min, depth_max, object_count, nb_validated, nb_predicted,
            nb_dubious, nb_unclassified, instrument, last_synced
        ) VALUES (
            42000001, 42, 66.0, -62.0, '2014-01-01', '2014-01-01',
            NULL, NULL, 1, 1, 0, 0, 0, 'UVP5', 'legacy-sync'
        );
        INSERT INTO project_signatures_cache (
            project_id, objcount, pctvalidated, pctclassified, last_synced
        ) VALUES (42, 1, 100.0, 100.0, 'legacy-sync');
        PRAGMA user_version = 2;
        """
    )
    conn.close()


def _read_sample(path) -> tuple[int, sqlite3.Row]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        version = get_schema_version(conn)
        row = conn.execute(
            "SELECT * FROM samples_cache WHERE sample_id = 42000001"
        ).fetchone()
        assert row is not None
        return version, row
    finally:
        conn.close()


def _assert_current_complete_sample(path) -> None:
    version, row = _read_sample(path)
    assert version == SCHEMA_VERSION
    # No object download and no per-sample date API — all temporal/depth fields NULL
    assert row["date_min"] is None
    assert row["datetime_min"] is None
    assert row["time_min"] is None
    assert row["depth_min"] is None
    assert row["depth_max"] is None
    assert row["temporal_precision"] == "none"
    assert row["depth_complete"] == 0
    assert row["metadata_complete"] == 0
    assert row["lat_avg"] == pytest.approx(67.0)
    assert row["lon_avg"] == pytest.approx(-63.0)


def test_bootstrap_creates_missing_cache_with_current_complete_sample(
    monkeypatch, tmp_path
):
    import core.mcp.ecotaxa_server as server

    cache_path = tmp_path / "ecotaxa_cache.sqlite"
    monkeypatch.setattr(server, "EcotaxaClient", DeterministicSyncClient)

    server._run_full_sync_with_real_client(str(cache_path))

    assert cache_path.exists()
    _assert_current_complete_sample(cache_path)


def test_bootstrap_forces_v2_refresh_despite_unchanged_signature(
    monkeypatch, tmp_path
):
    import core.mcp.ecotaxa_server as server

    cache_path = tmp_path / "ecotaxa_cache.sqlite"
    _create_v2_cache(cache_path)
    monkeypatch.setattr(server, "EcotaxaClient", DeterministicSyncClient)

    server._run_full_sync_with_real_client(str(cache_path))

    _assert_current_complete_sample(cache_path)
    conn = sqlite3.connect(cache_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM samples_cache WHERE project_id = 42"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_partial_bootstrap_keeps_schema_stale(monkeypatch, tmp_path):
    import core.mcp.ecotaxa_server as server

    cache_path = tmp_path / "ecotaxa_cache.sqlite"
    _create_v2_cache(cache_path)
    seen: dict[str, bool] = {}

    def partial_sync(conn, client, *, force, **kwargs):
        seen["force"] = force
        return {"status": "partial"}

    monkeypatch.setattr(server, "EcotaxaClient", DeterministicSyncClient)
    monkeypatch.setattr(server, "run_full_sync", partial_sync)

    server._run_full_sync_with_real_client(str(cache_path))

    assert seen == {"force": True}
    conn = sqlite3.connect(cache_path)
    try:
        assert get_schema_version(conn) == 2
    finally:
        conn.close()
