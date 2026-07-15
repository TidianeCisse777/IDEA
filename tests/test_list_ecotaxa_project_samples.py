"""Tool `list_ecotaxa_project_samples` : label ↔ sample_id numérique."""

from tools.copepod_sources import make_source_tools
from core.ecotaxa_browser.cache.repo import init_schema, open_connection, upsert_sample


def _seed_cache(path: str) -> None:
    conn = open_connection(path)
    init_schema(conn)
    upsert_sample(
        conn,
        sample_id=17498000023,
        project_id=17498,
        lat_avg=74.6024,
        lon_avg=-93.7093,
        date_min="2024-10-01",
        date_max="2024-10-01",
        object_count=500,
        instrument="UVP6",
        last_synced="2026-07-14T00:00:00Z",
        depth_max=116.2,
        original_id="am_leg4_RA76_1",
        station_id="RA76",
    )
    upsert_sample(
        conn,
        sample_id=17498000061,
        project_id=17498,
        lat_avg=79.4981,
        lon_avg=-73.0212,
        date_min="2024-09-16",
        date_max="2024-09-16",
        object_count=800,
        instrument="UVP6",
        last_synced="2026-07-14T00:00:00Z",
        depth_max=177.76,
        original_id="am_leg4_RA41_1",
        station_id="RA41",
    )
    # Sample d'un autre projet : ne doit pas apparaître.
    upsert_sample(
        conn,
        sample_id=14859000001,
        project_id=14859,
        lat_avg=82.399,
        lon_avg=-60.847,
        date_min="2024-08-22",
        date_max="2024-08-22",
        object_count=100,
        instrument="UVP6",
        last_synced="2026-07-14T00:00:00Z",
        original_id="am_leg3_RA09_1",
        station_id="RA09",
    )
    conn.close()


def _get_tool(thread_id: str):
    return next(
        t
        for t in make_source_tools(thread_id)
        if t.name == "list_ecotaxa_project_samples"
    )


def test_lists_numeric_sample_ids_for_project(tmp_path, monkeypatch):
    cache = tmp_path / "ecotaxa_cache.sqlite"
    _seed_cache(str(cache))
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache))

    out = _get_tool("thread-list-1").invoke({"project_id": 17498})

    # Les deux samples du projet, avec leur id numérique ET leur label.
    assert "17498000023" in out
    assert "17498000061" in out
    assert "am_leg4_RA76_1" in out
    assert "am_leg4_RA41_1" in out
    # Aucune fuite d'un autre projet.
    assert "14859000001" not in out
    assert "am_leg3_RA09_1" not in out


def test_empty_project_reports_no_sample(tmp_path, monkeypatch):
    cache = tmp_path / "ecotaxa_cache.sqlite"
    _seed_cache(str(cache))
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache))

    out = _get_tool("thread-list-2").invoke({"project_id": 99999})

    assert "99999" in out
    assert "aucun" in out.lower()
