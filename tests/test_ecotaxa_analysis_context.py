"""Analysis-ready context contracts for EcoTaxa cache queries."""

import sqlite3

import pandas as pd
from langchain_core.messages import ToolMessage


def _cache_with_station(tmp_path):
    from core.ecotaxa_browser.cache.repo import init_schema, upsert_project, upsert_sample

    path = tmp_path / "ecotaxa-cache.sqlite"
    conn = sqlite3.connect(path)
    init_schema(conn)
    upsert_project(
        conn,
        project_id=42,
        title="Davis Strait survey 2024",
        instrument="UVP5SD",
        status="active",
        last_synced="2026-08-11T00:00:00Z",
    )
    upsert_sample(
        conn,
        sample_id=1,
        project_id=42,
        lat_avg=67.5,
        lon_avg=-63.8,
        date_min="2024-07-01",
        date_max="2024-07-01",
        object_count=100,
        instrument="UVP5SD",
        station_id="DAVIS-01",
        profile_id="CAST-01",
        iho_zone="Détroit de Davis",
        zone_reference="IHO",
        last_synced="2026-08-11T00:00:00Z",
    )
    upsert_sample(
        conn,
        sample_id=2,
        project_id=42,
        lat_avg=67.6,
        lon_avg=-63.7,
        date_min="2024-07-02",
        date_max="2024-07-02",
        object_count=80,
        instrument="UVP5SD",
        station_id="DAVIS-01",
        profile_id="CAST-02",
        iho_zone="MEOW: Baffin Bay - Davis Strait",
        zone_reference="MEOW",
        last_synced="2026-08-11T00:00:00Z",
    )
    conn.close()
    return path


def test_station_analysis_query_automatically_adds_reusable_context(tmp_path, monkeypatch):
    import tools.copepod_sources as sources

    cache_path = _cache_with_station(tmp_path)
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_path))
    query = {
        tool.name: tool for tool in sources.make_source_tools("station-context-incomplete")
    }["query_ecotaxa_cache"]

    message = query.invoke(
        {
            "type": "tool_call",
            "id": "station-context",
            "name": "query_ecotaxa_cache",
            "args": {
                "sql": """
                    SELECT project_id, station_id,
                           COUNT(DISTINCT sample_id) AS n_samples
                    FROM samples_cache
                    WHERE zone_reference = 'IHO'
                      AND iho_zone = 'Détroit de Davis'
                    GROUP BY project_id, station_id
                """,
                "selection_name": "davis_stations",
                "description": "Stations EcoTaxa du détroit de Davis.",
            },
        }
    )

    assert isinstance(message, ToolMessage)
    assert message.artifact["status"] == "success"
    stored = sources._store.get(
        "station-context-incomplete:dataset:" + message.artifact["data_ref"]
    )["df"]
    assert {
        "project_id",
        "project_title",
        "title_years",
        "title_date_hint",
        "temporal_source",
        "temporal_confidence",
        "station_id",
        "latitude",
        "longitude",
        "zones",
        "instruments",
        "first_date",
        "last_date",
        "n_samples",
        "n_profiles",
    }.issubset(stored.columns)
    assert stored.loc[0, "n_samples"] == 1
    assert stored.loc[0, "n_profiles"] == 1
    assert stored.loc[0, "zones"] == "IHO:Détroit de Davis"
    assert stored.loc[0, "title_years"] == "[2024]"
    assert stored.loc[0, "title_date_hint"] is None
    assert stored.loc[0, "temporal_source"] == "project_title"
    assert stored.loc[0, "temporal_confidence"] == "exploratory"


def test_station_analysis_query_persists_complete_reusable_context(tmp_path, monkeypatch):
    from tools.copepod_sources import make_source_tools

    cache_path = _cache_with_station(tmp_path)
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_path))
    query = {
        tool.name: tool for tool in make_source_tools("station-context-complete")
    }["query_ecotaxa_cache"]

    message = query.invoke(
        {
            "type": "tool_call",
            "id": "station-context-complete",
            "name": "query_ecotaxa_cache",
            "args": {
                "sql": """
                    SELECT s.project_id,
                           p.title AS project_title,
                           s.station_id,
                           AVG(s.lat_avg) AS latitude,
                           AVG(s.lon_avg) AS longitude,
                           s.zone_reference,
                           s.iho_zone,
                           GROUP_CONCAT(DISTINCT s.instrument) AS instruments,
                           MIN(s.date_min) AS first_date,
                           MAX(s.date_max) AS last_date,
                           COUNT(DISTINCT s.sample_id) AS n_samples,
                           COUNT(DISTINCT s.profile_id) AS n_profiles
                    FROM samples_cache AS s
                    LEFT JOIN projects_cache AS p USING (project_id)
                    WHERE s.zone_reference = 'IHO'
                      AND s.iho_zone = 'Détroit de Davis'
                    GROUP BY s.project_id, p.title, s.station_id,
                             s.zone_reference, s.iho_zone
                """,
                "selection_name": "davis_stations_complete",
                "description": "Stations EcoTaxa du détroit de Davis avec contexte complet.",
            },
        }
    )

    assert isinstance(message, ToolMessage)
    assert message.artifact["status"] == "success"
    assert message.artifact["persisted"] is True
    assert message.artifact["data_ref"].startswith("df_ecotaxa_cache_result_")


def test_scalar_cache_diagnostic_is_exempt_from_analysis_context(tmp_path, monkeypatch):
    from tools.copepod_sources import make_source_tools

    cache_path = _cache_with_station(tmp_path)
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_path))
    query = {
        tool.name: tool for tool in make_source_tools("scalar-cache-diagnostic")
    }["query_ecotaxa_cache"]

    message = query.invoke(
        {
            "type": "tool_call",
            "id": "scalar-cache-diagnostic",
            "name": "query_ecotaxa_cache",
            "args": {"sql": "SELECT COUNT(*) AS n_samples FROM samples_cache"},
        }
    )

    assert isinstance(message, ToolMessage)
    assert message.artifact["status"] == "success"


def test_project_aggregate_with_dataframe_cte_keeps_partial_context_non_blocking(
    tmp_path, monkeypatch
):
    import tools.copepod_sources as sources
    from tools.dataset_registry import store_dataset
    from tools.session_store import SessionStore

    cache_path = _cache_with_station(tmp_path)
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_path))
    store = SessionStore(storage_dir=tmp_path / "sessions")
    monkeypatch.setattr(sources, "_store", store)
    thread_id = "project-aggregate-dataframe-cte"
    source_variable = "df_selected_projects"
    store_dataset(
        store,
        thread_id,
        pd.DataFrame({"project_id": [42]}),
        variable_name=source_variable,
        meta={"source": "test", "grain": "project"},
    )
    query = {
        tool.name: tool for tool in sources.make_source_tools(thread_id)
    }["query_ecotaxa_cache"]

    message = query.invoke(
        {
            "type": "tool_call",
            "id": "project-status-counts",
            "name": "query_ecotaxa_cache",
            "args": {
                "sql": f"""
                    WITH selected_projects AS (
                        SELECT DISTINCT project_id FROM {source_variable}
                    )
                    SELECT s.project_id,
                           SUM(s.object_count) AS n_objects
                    FROM samples_cache AS s
                    JOIN selected_projects AS selected USING (project_id)
                    GROUP BY s.project_id
                """,
                "dataframe_refs": [source_variable],
                "selection_name": "project_status_counts",
            },
        }
    )

    assert isinstance(message, ToolMessage)
    assert message.artifact["status"] == "success"
    assert message.artifact["metrics"]["analysis_context_grain"] == "project"
    assert message.artifact["metrics"]["analysis_context_complete"] is False
    assert "latitude" in message.artifact["metrics"]["analysis_context_missing"]
    stored = store.get(f"{thread_id}:dataset:{message.artifact['data_ref']}")["df"]
    assert stored.to_dict("records") == [{"project_id": 42, "n_objects": 180}]
