"""EcoTaxa cast-map parsing and rendering."""

import sqlite3

import pytest


def test_parser_resolves_english_baffin_bay_to_cached_zone(tmp_path, monkeypatch):
    from core.ecotaxa_browser.cache.repo import init_schema
    from tools.ecotaxa_cast_map import parse_ecotaxa_cast_map_request

    cache_db = tmp_path / "ecotaxa.sqlite"
    with sqlite3.connect(cache_db) as connection:
        init_schema(connection)
        connection.execute(
            "INSERT INTO samples_cache (sample_id, project_id, iho_zone, last_synced) "
            "VALUES (1, 10, 'Baie de Baffin', '2026-07-19T00:00:00Z')"
        )
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))

    request = parse_ecotaxa_cast_map_request(
        "Show EcoTaxa casts by project in Baffin Bay on a map"
    )

    assert request is not None
    assert request.zone_name == "Baie de Baffin"
    assert request.group_by == "project"


def test_second_identical_cast_map_reuses_rendered_image(tmp_path, monkeypatch):
    pytest.importorskip("cartopy.crs")
    from core.ecotaxa_browser.cache.repo import init_schema, upsert_sample
    from tools.ecotaxa_cast_map import CastMapRequest, render_ecotaxa_cast_map

    cache_db = tmp_path / "ecotaxa.sqlite"
    with sqlite3.connect(cache_db) as connection:
        init_schema(connection)
        upsert_sample(
            connection, sample_id=1, project_id=10, profile_id="cast-1",
            lat_avg=78.0, lon_avg=-70.0, iho_zone="Baie de Baffin",
            date_min="2024-08-01", date_max="2024-08-01", object_count=1,
            instrument="UVP6",
            last_synced="2026-07-19T00:00:00Z",
        )
        connection.execute(
            "INSERT INTO sync_runs (started_at, ended_at, status) "
            "VALUES ('2026-07-19T00:00:00Z', '2026-07-19T00:01:00Z', 'ok')"
        )
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))
    monkeypatch.setattr("tools.ecotaxa_cast_map.graphs_dir", lambda: tmp_path / "graphs")
    configured = []
    monkeypatch.setattr(
        "tools.ecotaxa_cast_map.configure_offline_cartopy",
        lambda: configured.append(True),
    )
    (tmp_path / "graphs").mkdir()
    request = CastMapRequest(zone_name="Baie de Baffin", group_by="project")

    first = render_ecotaxa_cast_map(request)
    second = render_ecotaxa_cast_map(request)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert configured == [True]


def test_fast_cast_map_records_zero_model_calls_for_local_diagnostics():
    import agent

    agent.clear_harness_trace("thread-fast-map-metrics")
    agent.record_harness_fast_route(
        "thread-fast-map-metrics",
        route="fast_ecotaxa_cast_map",
        timings_ms={"query": 12.0, "render": 640.0},
        cache_hit=True,
    )

    trace = agent.get_harness_trace("thread-fast-map-metrics")

    assert trace["route"] == "fast_ecotaxa_cast_map"
    assert trace["model_calls"] == []
    assert trace["timings_ms"]["render"] == 640.0
    assert trace["cache_hit"] is True
