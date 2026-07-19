"""Fast path for standard EcoTaxa cast maps."""
from unittest.mock import patch

import sqlite3

import pytest


def test_fast_cast_map_bypasses_react_for_explicit_ecotaxa_request():
    from serve import _try_fast_ecotaxa_cast_map
    from tools.ecotaxa_cast_map import CastMapRequest, RenderedCastMap

    request = CastMapRequest(zone_name="Baie de Baffin", group_by="project")
    rendered = RenderedCastMap(
        image_markdown="![graph](http://test/maps/baffin.png)",
        cast_count=76,
        excluded_missing_cast_ids=0,
        cache_hit=True,
        timings_ms={"query": 10.0, "render": 100.0},
    )
    with patch("serve.parse_ecotaxa_cast_map_request", return_value=request), patch(
        "serve.render_ecotaxa_cast_map", return_value=rendered
    ):
        reply = _try_fast_ecotaxa_cast_map(
            "thread-fast-map", "Show EcoTaxa casts by project in Baffin Bay on a map"
        )

    assert reply == "![graph](http://test/maps/baffin.png)\n\n76 casts affichés, distingués par projet."


def test_fast_cast_map_does_not_capture_ambiguous_request():
    from serve import _try_fast_ecotaxa_cast_map

    with patch("serve.parse_ecotaxa_cast_map_request", return_value=None):
        reply = _try_fast_ecotaxa_cast_map("thread-fast-map", "Montre les casts sur une carte")

    assert reply is None


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
    (tmp_path / "graphs").mkdir()
    request = CastMapRequest(zone_name="Baie de Baffin", group_by="project")

    first = render_ecotaxa_cast_map(request)
    second = render_ecotaxa_cast_map(request)

    assert first.cache_hit is False
    assert second.cache_hit is True


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
