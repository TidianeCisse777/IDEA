"""RC1 — provenance: describe_ecotaxa_project_coverage reconciles network vs cache.

The region/time/taxon browsers only read the local cache, so an un-synced but
accessible project looks empty. This tool must let the agent tell a real
absence from a not-yet-indexed project via an explicit verdict.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import ToolMessage

from core.ecotaxa_browser.cache.repo import (
    init_schema,
    open_connection,
    project_cache_coverage,
    upsert_project_schema,
    upsert_sample,
)


def _seed_cache(path, project_id, n_samples):
    conn = open_connection(str(path))
    init_schema(conn)
    if n_samples:
        upsert_project_schema(
            conn,
            project_id=project_id,
            schema_json='{"title": "seed"}',
            last_synced="2024-01-03T03:00:00Z",
        )
    for i in range(n_samples):
        upsert_sample(
            conn,
            sample_id=project_id * 1000 + i,
            project_id=project_id,
            lat_avg=60.0,
            lon_avg=-60.0,
            date_min="2024-01-01",
            date_max="2024-01-02",
            object_count=10,
            instrument="UVP6",
            last_synced="2024-01-03T03:00:00Z",
            depth_min=0.0,
            depth_max=100.0,
            original_id=f"station_{i}",
        )
    conn.commit()
    conn.close()


def _tool(thread_id):
    from tools.copepod_sources import make_source_tools

    return {t.name: t for t in make_source_tools(thread_id)}[
        "describe_ecotaxa_project_coverage"
    ]


def _call(item, **args) -> ToolMessage:
    message = item.invoke(
        {"type": "tool_call", "id": "cov", "name": item.name, "args": args}
    )
    assert isinstance(message, ToolMessage)
    return message


def _client(n_network, *, geolocated=True, in_scope=True, project_id=42):
    client = MagicMock()
    client.get_project.return_value = {"title": "UVP6 Baffin 2024"}
    coords = (60.0, -60.0) if geolocated else (None, None)
    client.list_samples.return_value = [
        {"sampleid": i, "latitude": coords[0], "longitude": coords[1]}
        for i in range(n_network)
    ]
    client.list_projects.return_value = (
        [{"project_id": project_id}] if in_scope else [{"project_id": 999999}]
    )
    return client


def test_repo_project_cache_coverage_counts_only_that_project(tmp_path):
    db = tmp_path / "cache.sqlite"
    _seed_cache(db, project_id=17498, n_samples=3)
    _seed_cache(db, project_id=2331, n_samples=1)
    conn = open_connection(str(db))
    init_schema(conn)
    coverage = project_cache_coverage(conn, 17498)
    conn.close()
    assert coverage["n_samples_cached"] == 3
    assert coverage["in_schema_cache"] is True
    absent = None
    conn = open_connection(str(db))
    init_schema(conn)
    absent = project_cache_coverage(conn, 999)
    conn.close()
    assert absent["n_samples_cached"] == 0
    assert absent["in_schema_cache"] is False


def test_accessible_but_not_indexed_is_flagged_not_absent(tmp_path, monkeypatch):
    db = tmp_path / "cache.sqlite"
    _seed_cache(db, project_id=42, n_samples=0)  # cache empty for this project
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(db))
    with patch("tools.copepod_sources.EcotaxaClient", return_value=_client(12)):
        message = _call(_tool("cov-not-indexed"), project_id=42)
    from tools.tool_result import validate_tool_artifact

    result = validate_tool_artifact(message.artifact)
    assert result.status == "success"
    assert result.provenance["verdict"] == "non_indexe"
    assert result.metrics["n_samples_network"] == 12
    assert result.metrics["n_samples_cached"] == 0
    assert "resync" in message.content.lower()


def test_readable_by_id_but_out_of_sync_scope(tmp_path, monkeypatch):
    db = tmp_path / "cache.sqlite"
    _seed_cache(db, project_id=2331, n_samples=0)
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(db))
    client = _client(2193, geolocated=True, in_scope=False, project_id=2331)
    with patch("tools.copepod_sources.EcotaxaClient", return_value=client):
        message = _call(_tool("cov-out-of-scope"), project_id=2331)
    from tools.tool_result import validate_tool_artifact

    result = validate_tool_artifact(message.artifact)
    assert result.provenance["verdict"] == "hors_perimetre_sync"
    assert "resync" in message.content.lower()


def test_accessible_but_not_geolocated_is_not_absence(tmp_path, monkeypatch):
    db = tmp_path / "cache.sqlite"
    _seed_cache(db, project_id=42, n_samples=0)
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(db))
    client = _client(2193, geolocated=False, in_scope=True, project_id=42)
    with patch("tools.copepod_sources.EcotaxaClient", return_value=client):
        message = _call(_tool("cov-nogeo"), project_id=42)
    from tools.tool_result import validate_tool_artifact

    result = validate_tool_artifact(message.artifact)
    assert result.provenance["verdict"] == "non_geolocalise"
    assert result.metrics["n_samples_geolocated"] == 0


def test_indexed_and_consistent(tmp_path, monkeypatch):
    db = tmp_path / "cache.sqlite"
    _seed_cache(db, project_id=42, n_samples=12)
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(db))
    with patch("tools.copepod_sources.EcotaxaClient", return_value=_client(12)):
        message = _call(_tool("cov-indexed"), project_id=42)
    from tools.tool_result import validate_tool_artifact

    assert validate_tool_artifact(message.artifact).provenance["verdict"] == "indexe"


def test_partial_index(tmp_path, monkeypatch):
    db = tmp_path / "cache.sqlite"
    _seed_cache(db, project_id=42, n_samples=5)
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(db))
    with patch("tools.copepod_sources.EcotaxaClient", return_value=_client(12)):
        message = _call(_tool("cov-partial"), project_id=42)
    from tools.tool_result import validate_tool_artifact

    assert validate_tool_artifact(message.artifact).provenance["verdict"] == "partiel"


def test_empty_on_source_is_real_absence(tmp_path, monkeypatch):
    db = tmp_path / "cache.sqlite"
    _seed_cache(db, project_id=42, n_samples=0)
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(db))
    with patch("tools.copepod_sources.EcotaxaClient", return_value=_client(0)):
        message = _call(_tool("cov-empty"), project_id=42)
    from tools.tool_result import validate_tool_artifact

    assert validate_tool_artifact(message.artifact).provenance["verdict"] == "vide_source"


def test_inaccessible_when_network_fails_and_cache_empty(tmp_path, monkeypatch):
    db = tmp_path / "cache.sqlite"
    _seed_cache(db, project_id=42, n_samples=0)
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(db))
    client = MagicMock()
    client.login.side_effect = RuntimeError("401 unauthorized")
    with patch("tools.copepod_sources.EcotaxaClient", return_value=client):
        message = _call(_tool("cov-inaccessible"), project_id=42)
    from tools.tool_result import validate_tool_artifact

    assert validate_tool_artifact(message.artifact).provenance["verdict"] == "inaccessible"


def test_network_down_but_cache_present_stays_explorable(tmp_path, monkeypatch):
    db = tmp_path / "cache.sqlite"
    _seed_cache(db, project_id=42, n_samples=4)
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(db))
    client = MagicMock()
    client.login.side_effect = RuntimeError("timeout")
    with patch("tools.copepod_sources.EcotaxaClient", return_value=client):
        message = _call(_tool("cov-netdown"), project_id=42)
    from tools.tool_result import validate_tool_artifact

    result = validate_tool_artifact(message.artifact)
    assert result.provenance["verdict"] == "reseau_indisponible"
    assert result.metrics["n_samples_cached"] == 4
