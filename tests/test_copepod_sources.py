"""Tests TDD — tools/copepod_sources.py"""
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tools.session_store import default_store as _store


@pytest.fixture(autouse=True)
def clear_sessions():
    if hasattr(_store, "_store"):
        _store._store.clear()
    yield
    if hasattr(_store, "_store"):
        _store._store.clear()


def _make_fake_client(df: pd.DataFrame):
    """Retourne un EcotaxaClient mocké qui renvoie df."""
    client = MagicMock()
    client.start_export.return_value = 42
    client.wait_for_job.return_value = {"state": "F"}
    client.download_tsv.return_value = df
    return client


# ── Comportement 1 : session store peuplé ──────────────────────────────────

def test_query_ecotaxa_stores_df_in_session(tmp_path):
    df = pd.DataFrame({
        "object_id":    ["obj_001", "obj_002"],
        "sample_id":    ["ips_007", "ips_007"],
        "object_major": [12.5, 8.3],
    })
    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        MockClient.return_value = _make_fake_client(df)
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-1")
        query = next(t for t in tools if t.name == "query_ecotaxa")
        query.invoke({"project_id": 1165})

    assert _store.has("thread-1")
    assert _store.get("thread-1")["df"].shape == (2, 3)


def test_query_ecotaxa_preserves_multiple_projects():
    from tools.copepod_sources import make_source_tools

    thread_id = "thread-multi-ecotaxa"
    df_1165 = pd.DataFrame({"project": [1165]})
    df_2331 = pd.DataFrame({"project": [2331]})
    client = _make_fake_client(df_1165)
    client.download_tsv.side_effect = [df_1165, df_2331]

    with patch("tools.copepod_sources.EcotaxaClient", return_value=client):
        query = next(t for t in make_source_tools(thread_id) if t.name == "query_ecotaxa")
        result_1165 = query.invoke({"project_id": 1165})
        result_2331 = query.invoke({"project_id": 2331})

    assert _store.get(f"{thread_id}:dataset:df_ecotaxa_1165")["df"].equals(df_1165)
    assert _store.get(f"{thread_id}:dataset:df_ecotaxa_2331")["df"].equals(df_2331)
    assert _store.get(f"{thread_id}:ecotaxa")["df"].equals(df_2331)
    assert "df_ecotaxa_1165" in result_1165
    assert "df_ecotaxa_2331" in result_2331


# ── Comportement 2 : lien de téléchargement dans le résumé ─────────────────

def test_query_ecotaxa_returns_download_link(monkeypatch):
    monkeypatch.delenv("SERVE_BASE_URL", raising=False)
    df = pd.DataFrame({"object_id": ["obj_001"], "sample_id": ["ips_007"]})
    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        MockClient.return_value = _make_fake_client(df)
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-2")
        query = next(t for t in tools if t.name == "query_ecotaxa")
        result = query.invoke({"project_id": 1165})

    assert "localhost:8000/downloads/" in result
    assert ".tsv" in result


# ── Comportement 3 : hint UVP dans le résumé ───────────────────────────────

def test_query_ecotaxa_uvp_hint_in_summary():
    df = pd.DataFrame({
        "object_id":    ["obj_001"],
        "sample_id":    ["ips_007"],
        "object_major": [12.5],
        "object_area":  [88.0],
        "object_annotation_category": ["Copepoda"],
    })
    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        MockClient.return_value = _make_fake_client(df)
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-3")
        query = next(t for t in tools if t.name == "query_ecotaxa")
        result = query.invoke({"project_id": 1165})

    assert "uvp_ecotaxa" in result


def test_query_ecotaxa_filters_by_sample_ids():
    df = pd.DataFrame({"object_id": ["obj_001"], "sample_id": [42000002]})
    client = _make_fake_client(df)

    with patch("tools.copepod_sources.EcotaxaClient", return_value=client):
        from tools.copepod_sources import make_source_tools

        query = next(t for t in make_source_tools("thread-sample-filter") if t.name == "query_ecotaxa")
        result = query.invoke({"project_id": 1165, "sample_ids": [42000002, 42000003]})

    client.start_export.assert_called_once_with(
        1165,
        {"statusfilter": "V", "samples": "42000002,42000003"},
    )
    assert "samples 42000002,42000003" in result


def test_query_ecotaxa_sample_resolves_project_and_exports_sample():
    df = pd.DataFrame({"object_id": ["obj_001"], "sample_id": [42000002]})
    client = _make_fake_client(df)
    fake_sample = {
        "sample_id": 42000002,
        "project_id": 1165,
        "original_id": "Station 7",
    }

    with (
        patch("tools.copepod_sources.core_get_sample", return_value=fake_sample),
        patch("tools.copepod_sources.EcotaxaClient", return_value=client),
    ):
        from tools.copepod_sources import make_source_tools

        query_sample = next(
            t for t in make_source_tools("thread-query-sample") if t.name == "query_ecotaxa_sample"
        )
        result = query_sample.invoke({"sample_id": 42000002})

    client.start_export.assert_called_once_with(
        1165,
        {"statusfilter": "V", "samples": "42000002"},
    )
    assert _store.get("thread-query-sample:dataset:df_ecotaxa_sample_42000002")["df"].equals(df)
    assert "Sample 42000002" in result


# ── Comportement 4 : EcotaxaClient.login() pose le header Bearer ───────────

def test_ecotaxa_client_login_sets_bearer_from_token(monkeypatch):
    monkeypatch.setenv("ECOTAXA_TOKEN", "my-jwt-token")
    monkeypatch.delenv("ECOTAXA_USERNAME", raising=False)

    from tools.ecotaxa_client import EcotaxaClient
    client = EcotaxaClient()
    client.login()

    assert client._session.headers["Authorization"] == "Bearer my-jwt-token"


# ── Comportement 5 : wait_for_job lève si state == "E" ─────────────────────

def test_ecotaxa_client_wait_for_job_raises_on_error():
    from unittest.mock import patch as _patch
    from tools.ecotaxa_client import EcotaxaClient

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"state": "E"}

    client = EcotaxaClient()
    with _patch.object(client._session, "get", return_value=mock_resp):
        with pytest.raises(RuntimeError, match=r"failed \(state=E\)"):
            client.wait_for_job(job_id=99)


def test_ecotaxa_client_wait_for_job_retries_transient_connection_error():
    import requests
    from tools.ecotaxa_client import EcotaxaClient

    finished_response = MagicMock()
    finished_response.json.return_value = {"state": "F"}

    client = EcotaxaClient()
    with (
        patch.object(
            client._session,
            "get",
            side_effect=[requests.ConnectionError("connection closed"), finished_response],
        ) as mock_get,
        patch("tools.ecotaxa_client.time.sleep") as mock_sleep,
    ):
        job = client.wait_for_job(job_id=99, poll_seconds=1, max_polls=2)

    assert job == {"state": "F"}
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(1)


# ── Comportement 6 : auth échouée → message d'erreur, pas de crash ─────────

def test_query_ecotaxa_auth_failure_returns_error():
    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        MockClient.return_value.start_export.side_effect = RuntimeError("EcoTaxa credentials missing")
        from tools.copepod_sources import make_source_tools
        # Thread id unique : le session store peut être un Postgres persistant
        # partagé (via .env) — un id figé collerait à des lignes de runs passés.
        thread_id = f"thread-err-{uuid.uuid4().hex}"
        tools = make_source_tools(thread_id)
        query = next(t for t in tools if t.name == "query_ecotaxa")
        result = query.invoke({"project_id": 1165})

    # Marqueur explicite consommé par le system prompt.
    assert result.startswith("EXPORT_FAILED")
    assert "credentials missing" in result
    assert not _store.has(thread_id)


def test_query_ecotaxa_export_failure_surfaces_server_message():
    """Échec HTTP côté serveur EcoTaxa → message serveur visible + diagnostic."""
    from tools.ecotaxa_client import EcotaxaExportError

    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        MockClient.return_value.start_export.side_effect = EcotaxaExportError(
            project_id=14853,
            status_code=403,
            server_message="User has no Export right on this project",
        )
        from tools.copepod_sources import make_source_tools
        thread_id = f"thread-fail-{uuid.uuid4().hex}"
        tools = make_source_tools(thread_id)
        query = next(t for t in tools if t.name == "query_ecotaxa")
        result = query.invoke({"project_id": 14853, "sample_ids": [14853000003]})

    assert result.startswith("EXPORT_FAILED")
    assert "14853" in result
    assert "HTTP 403" in result
    assert "no Export right" in result
    # Diagnostic suggéré.
    assert "preview_ecotaxa_project(14853)" in result
    # Interdiction explicite de retomber sur la recherche.
    assert "find_ecotaxa_samples_in_region" in result
    assert not _store.has(thread_id)


def test_query_ecotaxa_sample_export_failure_keeps_sample_context():
    from tools.ecotaxa_client import EcotaxaExportError

    sample_meta = {"sample_id": 42000002, "project_id": "1165", "original_id": "stn-A"}
    with patch("tools.copepod_sources.core_get_sample", return_value=sample_meta), \
         patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        MockClient.return_value.start_export.side_effect = EcotaxaExportError(
            project_id=1165, status_code=403, server_message="forbidden",
        )
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-fail-sample")
        query = next(t for t in tools if t.name == "query_ecotaxa_sample")
        result = query.invoke({"sample_id": 42000002})

    assert result.startswith("EXPORT_FAILED")
    assert "sample 42000002" in result
    assert "projet 1165" in result


def test_query_ecotaxa_logs_in_before_starting_export():
    calls = []
    df = pd.DataFrame({"object_id": ["obj_001"]})

    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        client = MockClient.return_value
        client.login.side_effect = lambda: calls.append("login")
        client.start_export.side_effect = lambda project_id, filters: calls.append("start_export") or 42
        client.wait_for_job.return_value = {"state": "F"}
        client.download_tsv.return_value = df

        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-auth")
        query = next(t for t in tools if t.name == "query_ecotaxa")
        query.invoke({"project_id": 1165})

    assert calls == ["login", "start_export"]


def test_ecotaxa_client_list_projects_normalizes_api_response():
    from tools.ecotaxa_client import EcotaxaClient

    response = MagicMock()
    response.json.return_value = [
        {"projid": 2331, "title": "LOKI ArcticNet", "instrument": "LOKI"},
        {"projid": "1165", "title": "UVP5 Amundsen 2018", "instrument": "UVP5"},
    ]
    client = EcotaxaClient()

    with patch.object(client._session, "get", return_value=response) as mock_get:
        projects = client.list_projects()

    mock_get.assert_called_once_with(
        "https://ecotaxa.obs-vlfr.fr/api/projects/search",
        params={"title_filter": "", "instrument_filter": ""},
        timeout=60,
    )
    response.raise_for_status.assert_called_once_with()
    assert projects == [
        {
            "projid": 2331,
            "project_id": 2331,
            "name": "LOKI ArcticNet",
            "title": "LOKI ArcticNet",
            "instrument": "LOKI",
        },
        {
            "projid": 1165,
            "project_id": 1165,
            "name": "UVP5 Amundsen 2018",
            "title": "UVP5 Amundsen 2018",
            "instrument": "UVP5",
        },
    ]


def test_ecotaxa_client_list_projects_preserves_cache_signature_fields():
    from tools.ecotaxa_client import EcotaxaClient

    response = MagicMock()
    response.json.return_value = [
        {
            "projid": 1165,
            "title": "UVP5 Amundsen 2018",
            "objcount": 47469,
            "pctvalidated": 81.234567,
            "pctclassified": 99.5,
        },
    ]
    client = EcotaxaClient()

    with patch.object(client._session, "get", return_value=response):
        projects = client.list_projects()

    assert projects == [
        {
            "projid": 1165,
            "project_id": 1165,
            "name": "UVP5 Amundsen 2018",
            "title": "UVP5 Amundsen 2018",
            "objcount": 47469,
            "pctvalidated": 81.234567,
            "pctclassified": 99.5,
        }
    ]


def test_ecotaxa_client_preview_project_combines_metadata_summary_and_objects():
    from tools.ecotaxa_client import EcotaxaClient

    metadata_response = MagicMock()
    metadata_response.json.return_value = {
        "projid": 14622,
        "title": "LOKI_ArcticNet_2015",
        "instrument": "Loki",
        "status": "Annotate",
        "highest_right": "Annotate",
        "objcount": 1687393,
        "pctvalidated": 10.08,
        "pctclassified": 100.0,
    }
    summary_response = MagicMock()
    summary_response.json.return_value = {
        "total_objects": 1687393,
        "validated_objects": 170066,
        "dubious_objects": 11355,
        "predicted_objects": 1505972,
    }
    query_response = MagicMock()
    query_response.json.return_value = {
        "details": [
            ["object-001", "2015-04-22", 357.1, "Metridia longa"],
            ["object-002", "2015-04-22", 357.0, "badsegmentation"],
        ],
        "total_ids": 1687393,
    }

    client = EcotaxaClient()
    with (
        patch.object(client._session, "get", return_value=metadata_response) as mock_get,
        patch.object(
            client._session,
            "post",
            side_effect=[summary_response, query_response],
        ) as mock_post,
    ):
        preview = client.preview_project(14622, limit=2)

    mock_get.assert_called_once_with(
        "https://ecotaxa.obs-vlfr.fr/api/projects/14622",
        timeout=60,
    )
    assert mock_post.call_args_list[0].kwargs == {
        "params": {"only_total": False},
        "json": {},
        "timeout": 60,
    }
    assert mock_post.call_args_list[1].kwargs == {
        "params": {
            "fields": "obj.orig_id,obj.objdate,obj.depth_min,txo.display_name",
            "order_field": "obj.objid",
            "window_start": 0,
            "window_size": 2,
        },
        "json": {},
        "timeout": 60,
    }
    assert preview["metadata"]["project_id"] == 14622
    assert preview["summary"]["validated_objects"] == 170066
    assert preview["objects"] == [
        {
            "orig_id": "object-001",
            "date": "2015-04-22",
            "depth_min": 357.1,
            "taxon": "Metridia longa",
        },
        {
            "orig_id": "object-002",
            "date": "2015-04-22",
            "depth_min": 357.0,
            "taxon": "badsegmentation",
        },
    ]


def test_source_tools_include_list_ecotaxa_projects():
    from tools.copepod_sources import make_source_tools

    tool_names = {source_tool.name for source_tool in make_source_tools("thread-projects")}

    assert "list_ecotaxa_projects" in tool_names


def test_source_tools_include_preview_ecotaxa_project():
    from tools.copepod_sources import make_source_tools

    tool_names = {source_tool.name for source_tool in make_source_tools("thread-preview")}

    assert "preview_ecotaxa_project" in tool_names


def test_preview_ecotaxa_project_renders_markdown_without_storing_session():
    preview = {
        "metadata": {
            "project_id": 14622,
            "name": "LOKI_ArcticNet_2015",
            "instrument": "Loki",
            "status": "Annotate",
            "access": "Annotate",
            "object_count": 1687393,
            "percent_validated": 10.08,
            "percent_classified": 100.0,
        },
        "summary": {
            "total_objects": 1687393,
            "validated_objects": 170066,
            "dubious_objects": 11355,
            "predicted_objects": 1505972,
        },
        "objects": [
            {
                "orig_id": "object-001",
                "date": "2015-04-22",
                "depth_min": 357.1,
                "taxon": "Metridia longa",
            }
        ],
    }

    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        client = MockClient.return_value
        client.preview_project.return_value = preview
        from tools.copepod_sources import make_source_tools
        source_tools = make_source_tools("thread-preview")
        preview_tool = next(t for t in source_tools if t.name == "preview_ecotaxa_project")
        result = preview_tool.invoke({"project_id": 14622})

    client.login.assert_called_once_with()
    client.preview_project.assert_called_once_with(14622, limit=10)
    assert "LOKI_ArcticNet_2015" in result
    assert "1 687 393" in result
    assert "10.08 %" in result
    assert "| object-001 | 2015-04-22 | 357.1 | Metridia longa |" in result
    assert not _store.has("thread-preview")


def test_preview_ecotaxa_project_handles_empty_objects():
    preview = {
        "metadata": {
            "project_id": 42,
            "name": "Empty project",
            "instrument": "UVP5",
            "status": "Annotate",
            "access": "View",
            "object_count": 0,
            "percent_validated": 0,
            "percent_classified": 0,
        },
        "summary": {
            "total_objects": 0,
            "validated_objects": 0,
            "dubious_objects": 0,
            "predicted_objects": 0,
        },
        "objects": [],
    }

    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        MockClient.return_value.preview_project.return_value = preview
        from tools.copepod_sources import make_source_tools
        source_tools = make_source_tools("thread-empty-preview")
        preview_tool = next(t for t in source_tools if t.name == "preview_ecotaxa_project")
        result = preview_tool.invoke({"project_id": 42})

    assert "Aucun objet dans l'aperçu." in result


def test_preview_ecotaxa_project_returns_controlled_error():
    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        MockClient.return_value.preview_project.side_effect = RuntimeError("preview failed")
        from tools.copepod_sources import make_source_tools
        source_tools = make_source_tools("thread-preview-error")
        preview_tool = next(t for t in source_tools if t.name == "preview_ecotaxa_project")
        result = preview_tool.invoke({"project_id": 14622})

    assert result.startswith("Erreur lors de l'accès à EcoTaxa :")
    assert not _store.has("thread-preview-error")


def test_list_ecotaxa_projects_logs_in_sorts_and_renders_markdown():
    projects = [
        {"project_id": 1165, "name": "UVP5 Amundsen"},
        {"project_id": 42, "name": "Green Edge"},
    ]

    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        client = MockClient.return_value
        client.list_projects.return_value = projects
        from tools.copepod_sources import make_source_tools
        source_tools = make_source_tools("thread-projects")
        list_projects = next(t for t in source_tools if t.name == "list_ecotaxa_projects")
        result = list_projects.invoke({})

    client.login.assert_called_once_with()
    assert "| project_id | name |" in result
    assert result.index("| 42 | Green Edge |") < result.index("| 1165 | UVP5 Amundsen |")
    assert not _store.has("thread-projects")


def test_list_ecotaxa_projects_handles_empty_list():
    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        MockClient.return_value.list_projects.return_value = []
        from tools.copepod_sources import make_source_tools
        source_tools = make_source_tools("thread-empty")
        list_projects = next(t for t in source_tools if t.name == "list_ecotaxa_projects")
        result = list_projects.invoke({})

    assert result == "Aucun projet EcoTaxa accessible."


def test_list_ecotaxa_projects_returns_controlled_error():
    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        MockClient.return_value.login.side_effect = RuntimeError("invalid credentials")
        from tools.copepod_sources import make_source_tools
        source_tools = make_source_tools("thread-error")
        list_projects = next(t for t in source_tools if t.name == "list_ecotaxa_projects")
        result = list_projects.invoke({})

    assert result.startswith("Erreur lors de l'accès à EcoTaxa :")
    assert not _store.has("thread-error")




def test_ecotaxa_skill_routes_preview_without_export():
    skill = Path("agents/skills/ecotaxa_query.md").read_text(encoding="utf-8")

    assert "query_ecotaxa_cache" in skill
    assert "query_ecotaxa" in skill
    assert "Ne lance pas `query_ecotaxa`" in skill


def test_query_ecotaxa_also_stores_named_slot_for_join():
    df = pd.DataFrame({"obj_orig_id": ["ips_007_1"], "object_major": [12.5]})
    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        MockClient.return_value = _make_fake_client(df)
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-join-et")
        query = next(t for t in tools if t.name == "query_ecotaxa")
        query.invoke({"project_id": 1165})

    assert _store.has("thread-join-et:ecotaxa")
    assert _store.get("thread-join-et:ecotaxa")["df"].shape == (1, 2)


def test_source_tools_include_get_ecotaxa_sample():
    from tools.copepod_sources import make_source_tools

    tool_names = {source_tool.name for source_tool in make_source_tools("thread-get-sample")}

    assert "get_ecotaxa_sample" in tool_names
    assert "summarize_ecotaxa_sample_deployment" in tool_names
    assert "query_ecotaxa_sample" in tool_names


def test_ecotaxa_navigation_tools_describe_the_preseeded_navigation_contract():
    from tools.copepod_sources import make_source_tools

    tools_by_name = {source_tool.name: source_tool for source_tool in make_source_tools("thread-descriptions")}
    navigation_tools = [
        "count_ecotaxa_taxa",
        "compare_ecotaxa_projects",
        "find_ecotaxa_samples_in_region",
        "find_ecotaxa_projects_in_region",
        "group_ecotaxa_project_samples_by_region",
        "find_ecotaxa_observations",
        "get_ecotaxa_sample",
        "summarize_ecotaxa_sample_deployment",
        "summarize_ecotaxa_samples",
        "summarize_ecotaxa_sample",
        "summarize_ecotaxa_projects",
        "summarize_ecotaxa_project",
        "export_ecotaxa_samples",
    ]

    for tool_name in navigation_tools:
        assert tool_name in tools_by_name
        assert "already pre-activated with this source family" in tools_by_name[tool_name].description


def test_get_ecotaxa_sample_renders_sample_metadata():
    fake_sample = {
        "sample_id": 42000002,
        "project_id": 42,
        "original_id": "GE2015_st12_p",
        "latitude": 67.480,
        "longitude": -63.790,
        "free_fields": {
            "station": "ST12",
            "volume_filtered_m3": 12.4,
            "depth_total_m": 350.0,
        },
    }
    with patch("tools.copepod_sources.core_get_sample", return_value=fake_sample):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-get-sample-render")
        get_sample_tool = next(t for t in tools if t.name == "get_ecotaxa_sample")
        result = get_sample_tool.invoke({"sample_id": 42000002})

    assert "42000002" in result
    assert "GE2015_st12_p" in result
    assert "67.480" in result
    assert "-63.790" in result
    assert "station" in result
    assert "ST12" in result
    assert "volume_filtered_m3" in result


def test_summarize_ecotaxa_sample_deployment_renders_metadata_depths_and_uvp_fields():
    fake_deployment = {
        "sample": {
            "sample_id": 42000013,
            "project_id": 42,
            "original_id": "gn2015_l2_019",
            "latitude": 67.4795,
            "longitude": -63.79,
            "free_fields": {"profileid": "019", "stationid": "ice-camp"},
        },
        "acquisitions": [{
            "acquisition_id": 420000014,
            "sample_id": 42000013,
            "original_id": "uvp5_gn2015_l2_019",
            "instrument": "uvp5",
            "free_fields": {"pixel": 0.147, "exposure": 12},
        }],
        "object_summary": {
            "total_objects": 3420,
            "objects_scanned": 3420,
            "truncated": False,
            "date_min": "2015-05-22",
            "date_max": "2015-05-23",
            "datetime_min": "2015-05-22T14:03:58",
            "datetime_max": "2015-05-23T14:08:01",
            "temporal_precision": "datetime",
            "depth_min": 1.8,
            "depth_max": 4.5,
            "metadata_complete": True,
            "metadata_coverage_pct": 100.0,
            "count_discrepancy": False,
            "query_total_objects": 3420,
            "nb_validated": 3000,
            "nb_predicted": 400,
            "nb_dubious": 10,
            "nb_unclassified": 10,
            "acquisition_ids": [420000014],
        },
    }

    with patch("tools.copepod_sources.summarize_sample_deployment", return_value=fake_deployment):
        from tools.copepod_sources import make_source_tools

        tools = make_source_tools("thread-deployment-summary")
        tool = next(t for t in tools if t.name == "summarize_ecotaxa_sample_deployment")
        result = tool.invoke({"sample_id": 42000013})

    assert "Déploiement EcoTaxa" in result
    assert "42000013" in result
    assert "gn2015_l2_019" in result
    assert "2015-05-22" in result
    assert "2015-05-23" in result
    assert "14:03:58" in result
    assert "1.8" in result
    assert "4.5" in result
    assert "validés" in result.lower()
    assert "prédits" in result.lower()
    assert "100" in result
    assert "profileid" in result
    assert "pixel=0.147" in result
    assert "uvp5" in result


def test_summarize_ecotaxa_sample_deployment_marks_partial_metadata_and_count_mismatch():
    fake_deployment = {
        "sample": {
            "sample_id": 42000013,
            "project_id": 42,
            "original_id": "gn2015_l2_019",
            "latitude": None,
            "longitude": None,
            "free_fields": {},
        },
        "acquisitions": [],
        "object_summary": {
            "total_objects": 3,
            "objects_scanned": 2,
            "truncated": True,
            "date_min": "2015-05-22",
            "date_max": "2015-05-22",
            "datetime_min": "2015-05-22T14:03:58",
            "datetime_max": "2015-05-22T14:08:01",
            "temporal_precision": "datetime",
            "depth_min": 1.8,
            "depth_max": 4.5,
            "metadata_complete": False,
            "metadata_coverage_pct": 66.666,
            "count_discrepancy": True,
            "query_total_objects": 2,
            "nb_validated": 3,
            "nb_predicted": 0,
            "nb_dubious": 0,
            "nb_unclassified": 0,
            "acquisition_ids": [],
        },
    }

    with patch("tools.copepod_sources.summarize_sample_deployment", return_value=fake_deployment):
        from tools.copepod_sources import make_source_tools

        tools = make_source_tools("thread-deployment-partial")
        tool = next(t for t in tools if t.name == "summarize_ecotaxa_sample_deployment")
        result = tool.invoke({"sample_id": 42000013})

    assert "partielle" in result.lower()
    assert "statistiques du sample" in result.lower()
    assert "| objets total (statistiques sample) | 3 |" in result
    assert "requête d’objets (2)" in result


def test_find_ecotaxa_samples_in_region_requires_filter():
    from tools.copepod_sources import make_source_tools
    tools = make_source_tools("thread-no-filter-samples")
    fn = next(t for t in tools if t.name == "find_ecotaxa_samples_in_region")
    result = fn.invoke({})  # no bbox, no date_range, no instrument
    assert "filtre" in result.lower() or "filter" in result.lower()
    assert "bbox" in result.lower() or "date" in result.lower() or "instrument" in result.lower()


def test_find_ecotaxa_projects_in_region_requires_filter():
    from tools.copepod_sources import make_source_tools
    tools = make_source_tools("thread-no-filter-projects")
    fn = next(t for t in tools if t.name == "find_ecotaxa_projects_in_region")
    result = fn.invoke({})
    assert "filtre" in result.lower() or "filter" in result.lower()


def test_get_ecotaxa_sample_handles_browser_error():
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError

    def _raise(sample_id):
        raise EcoTaxaBrowserError("SAMPLE_NOT_FOUND", "sample 999 not accessible")

    with patch("tools.copepod_sources.core_get_sample", side_effect=_raise):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-get-sample-error")
        get_sample_tool = next(t for t in tools if t.name == "get_ecotaxa_sample")
        result = get_sample_tool.invoke({"sample_id": 999})

    assert "SAMPLE_NOT_FOUND" in result
    assert "999" in result


# --- Object-level read (browse content without export) ----------------------


def test_source_tools_include_object_read_tools():
    from tools.copepod_sources import make_source_tools

    names = {t.name for t in make_source_tools("thread-objects")}
    assert "list_ecotaxa_sample_objects" in names
    assert "get_ecotaxa_object" in names


def test_object_read_tools_do_not_request_a_redundant_skill_load():
    from tools.copepod_sources import make_source_tools

    by_name = {t.name: t for t in make_source_tools("thread-objects-desc")}
    for name in ("list_ecotaxa_sample_objects", "get_ecotaxa_object"):
        assert 'load_skill("ecotaxa_navigation")' not in by_name[name].description


def test_get_ecotaxa_object_renders_full_context():
    fake = {
        "object": {
            "object_id": 1749800000001, "original_id": "o1", "acquisition_id": 4,
            "sample_id": 17498000001, "project_id": 17498, "taxon_id": 25828,
            "classification_status": "V", "date": "2024-09-21",
            "depth_min": 5.0, "depth_max": 120.0,
            "latitude": 67.48, "longitude": -63.79,
            "free_fields": {"area": 1234, "major": 45.6},
        },
        "acquisition": {"acquisition_id": 4, "instrument": "uvp6",
                        "free_fields": {"pixel": 0.147}},
        "sample": {"sample_id": 17498000001, "original_id": "st12",
                   "latitude": 67.48, "longitude": -63.79},
        "project": {"project_id": 17498},
    }
    with patch("tools.copepod_sources.core_get_object", return_value=fake):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-get-object")
        fn = next(t for t in tools if t.name == "get_ecotaxa_object")
        result = fn.invoke({"object_id": 1749800000001})

    assert "1749800000001" in result
    assert "st12" in result           # sample context
    assert "uvp6" in result           # acquisition context
    assert "area" in result           # object free fields
    assert "120" in result            # depth


def test_get_ecotaxa_object_error_steers_to_list_when_sample_id_passed():
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError

    def _raise(object_id):
        raise EcoTaxaBrowserError("OBJECT_NOT_FOUND", "object not accessible")

    with patch("tools.copepod_sources.core_get_object", side_effect=_raise):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-get-object-error")
        fn = next(t for t in tools if t.name == "get_ecotaxa_object")
        result = fn.invoke({"object_id": 17498000001})
    assert "OBJECT_NOT_FOUND" in result
    # the error steers the model to the list tool if a sample_id was passed.
    assert "list_ecotaxa_sample_objects" in result


def test_list_ecotaxa_sample_objects_renders_rows_without_export():
    fake_objects = [
        {"object_id": 42000002001, "original_id": "o1", "acquisition_id": 4,
         "sample_id": 42000002, "project_id": 42, "taxon_id": 25828,
         "taxon": "Copepoda", "classification_status": "V",
         "date": "2015-05-22", "depth_min": 5.0, "depth_max": 120.0},
        {"object_id": 42000002002, "original_id": "o2", "acquisition_id": 4,
         "sample_id": 42000002, "project_id": 42, "taxon_id": 11111,
         "taxon": "Calanus", "classification_status": "P",
         "date": "2015-05-22", "depth_min": 5.0, "depth_max": 120.0},
    ]
    with patch("tools.copepod_sources.core_list_sample_objects", return_value=fake_objects) as mocked:
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-list-objects")
        fn = next(t for t in tools if t.name == "list_ecotaxa_sample_objects")
        result = fn.invoke({"sample_id": 42000002})

    # object-level rows are rendered directly — no export job triggered.
    assert "42000002001" in result
    assert "Copepoda" in result and "Calanus" in result
    assert "V" in result and "P" in result
    assert "120" in result
    # the sample_id was forwarded to the paginated object query.
    assert mocked.call_args.kwargs.get("sample_id", None) == 42000002 or \
        mocked.call_args.args[0] == 42000002


def test_list_ecotaxa_sample_objects_empty_page():
    with patch("tools.copepod_sources.core_list_sample_objects", return_value=[]):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-list-objects-empty")
        fn = next(t for t in tools if t.name == "list_ecotaxa_sample_objects")
        result = fn.invoke({"sample_id": 42000002, "page": 9})
    assert "aucun" in result.lower()




def test_count_ecotaxa_taxa_shows_resolved_taxon_id_and_u_count():
    fake = {
        "project_ids_resolved": [14853],
        "taxa_resolved": [{
            "input": "copépodes",
            "taxon_id": 25828,
            "matched_name": "Copepoda<Multicrustacea",
        }],
        "rows": [{
            "project_id": 14853,
            "taxon_id": 25828,
            "taxon_name": "Copepoda<Multicrustacea",
            "count_V": 2063,
            "count_P": 15589,
            "count_D": 0,
            "count_U": 0,
            "count_total": 17652,
        }],
        "inaccessible_project_ids": [],
        "unresolved_taxa": [],
    }
    with patch("tools.copepod_sources.taxa_stats", return_value=fake):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-count-taxa")
        fn = next(t for t in tools if t.name == "count_ecotaxa_taxa")
        result = fn.invoke({"project_ids": [14853], "taxa": ["copépodes"]})

    assert "taxon_id" in result
    assert "25828" in result
    assert "Copepoda<Multicrustacea" in result
    assert "2063" in result
    assert "non classés" in result


# ════════════════════════════════════════════════════════════════════════════
# Navigation slices — gate tests (1 par slice).
# Chaque slice est jugée OK quand ce test passe au niveau LC tool.
# ════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def seeded_cache(tmp_path):
    """SQLite cache EcoTaxa patché pour la durée du test."""
    import sqlite3
    from core.ecotaxa_browser.cache.repo import init_schema, upsert_sample

    path = tmp_path / "ecotaxa_cache.sqlite"
    conn = sqlite3.connect(str(path))
    init_schema(conn)

    samples = [
        # Projet 14853 (UVP6 2024 Baie de Baffin)
        {"sample_id": 14853000001, "project_id": 14853, "lat": 73.5, "lon": -66.0,
         "date_min": "2024-10-10", "date_max": "2024-10-10", "instrument": "UVP6"},
        {"sample_id": 14853000002, "project_id": 14853, "lat": 73.7, "lon": -66.8,
         "date_min": "2024-10-11", "date_max": "2024-10-11", "instrument": "UVP6"},
        # Projet 2331 (LOKI dans Baie de Baffin aussi)
        {"sample_id": 2331000001, "project_id": 2331, "lat": 74.0, "lon": -67.0,
         "date_min": "2015-08-01", "date_max": "2015-08-01", "instrument": "Loki"},
        # Projet 4042 hors Baffin
        {"sample_id": 4042000001, "project_id": 4042, "lat": 45.0, "lon": -60.0,
         "date_min": "2018-06-01", "date_max": "2018-06-01", "instrument": "UVP5"},
    ]
    for s in samples:
        upsert_sample(
            conn,
            sample_id=s["sample_id"],
            project_id=s["project_id"],
            lat_avg=s["lat"],
            lon_avg=s["lon"],
            date_min=s["date_min"],
            date_max=s["date_max"],
            object_count=100,
            instrument=s["instrument"],
            last_synced="ts",
        )
    conn.close()

    with patch("core.ecotaxa_browser.region._cache_db_path", return_value=str(path)), \
         patch("core.ecotaxa_browser.observations._cache_db_path", return_value=str(path)):
        yield str(path)


# ── SLICE 1 GATE ──────────────────────────────────────────────────────────────

def test_slice1_find_ecotaxa_samples_in_region_filters_by_project_ids(seeded_cache):
    """L'agent doit pouvoir dire : « samples de Baie de Baffin DANS le projet 2331 »
    en un seul appel. project_ids est un filtre cache (SQL IN), pas un post-process.
    """
    from tools.copepod_sources import make_source_tools
    tools = make_source_tools("thread-slice1")
    fn = next(t for t in tools if t.name == "find_ecotaxa_samples_in_region")

    bbox = {"south": 70.0, "west": -80.0, "north": 80.0, "east": -60.0}

    # Sans filtre projet : 3 samples Baffin (14853 ×2, 2331 ×1)
    result_all = fn.invoke({"bbox": bbox})
    assert "14853000001" in result_all
    assert "14853000002" in result_all
    assert "2331000001" in result_all

    # Avec project_ids=[2331] : seul le sample LOKI doit ressortir
    result_loki = fn.invoke({"bbox": bbox, "project_ids": [2331]})
    assert "2331000001" in result_loki
    assert "14853000001" not in result_loki
    assert "14853000002" not in result_loki


def test_find_ecotaxa_samples_in_region_stores_named_selection(seeded_cache):
    from tools.copepod_sources import make_source_tools
    from tools.session_store import default_store

    thread_id = "thread-selection-memory"
    tools = make_source_tools(thread_id)
    fn = next(t for t in tools if t.name == "find_ecotaxa_samples_in_region")

    result = fn.invoke({
        "zone_name": "Baie de Baffin",
        "instrument": "UVP6",
    })

    assert "Sélection mémorisée" in result
    assert "Résumé de la sélection" in result
    assert "lignes affichées" in result
    assert "Tableau des samples" in result
    assert "selection_baie_de_baffin_uvp6" in result
    assert "Actions possibles" in result
    assert "résume cette sélection" in result
    assert "exporte cette sélection" in result

    latest = default_store.get(f"{thread_id}:ecotaxa_selection_latest")
    assert latest is not None
    assert latest["meta"]["selection_name"] == "selection_baie_de_baffin_uvp6"
    assert latest["meta"]["sample_ids"] == [14853000001, 14853000002]

    named = default_store.get(
        f"{thread_id}:selection:selection_baie_de_baffin_uvp6"
    )
    assert named is not None
    assert named["meta"]["sample_ids"] == [14853000001, 14853000002]


def test_export_ecotaxa_samples_uses_named_selection_for_dry_run(seeded_cache):
    from tools.copepod_sources import make_source_tools
    from tools.session_store import default_store

    thread_id = "thread-export-selection"
    default_store.set(
        f"{thread_id}:selection:selection_baie_de_baffin_uvp6",
        None,
        {
            "selection_name": "selection_baie_de_baffin_uvp6",
            "sample_ids": [14853000001, 2331000001],
        },
    )

    tools = make_source_tools(thread_id)
    fn = next(t for t in tools if t.name == "export_ecotaxa_samples")
    result = fn.invoke({
        "selection_name": "selection_baie_de_baffin_uvp6",
    })

    assert "selection_baie_de_baffin_uvp6" in result
    assert "14853" in result
    assert "2331" in result
    assert "14853000001" in result
    assert "2331000001" in result


def test_export_ecotaxa_samples_uses_derived_sample_table_for_dry_run(seeded_cache):
    """A persisted pandas subset with sample_id is a reusable export scope."""
    import pandas as pd

    from tools.copepod_sources import make_source_tools
    from tools.dataset_registry import store_dataset
    from tools.session_store import default_store

    thread_id = "thread-export-derived-selection"
    store_dataset(
        default_store,
        thread_id,
        pd.DataFrame({
            "sample_id": [14853000001, 2331000001],
            "station_id": ["RA25", "RA27"],
        }),
        variable_name="df_derived_baffin_samples",
        meta={"source": "analysis:derived", "description": "Subset Baffin"},
    )

    fn = next(
        tool for tool in make_source_tools(thread_id)
        if tool.name == "export_ecotaxa_samples"
    )
    result = fn.invoke({"selection_name": "df_derived_baffin_samples"})

    assert "df_derived_baffin_samples" in result
    assert "14853000001" in result
    assert "2331000001" in result


def test_summarize_ecotaxa_samples_uses_latest_selection(monkeypatch):
    from tools.copepod_sources import make_source_tools
    from tools.session_store import default_store

    thread_id = "thread-summarize-selection"
    default_store.set(
        f"{thread_id}:ecotaxa_selection_latest",
        None,
        {
            "selection_name": "selection_baie_de_baffin_uvp6",
            "sample_ids": [14853000001, 14853000002],
        },
    )

    monkeypatch.setattr(
        "tools.copepod_sources.summarize_samples",
        lambda sample_ids: [
            {
                "sample_id": sample_ids[0],
                "projid": 14853,
                "nb_validated": 10,
                "nb_predicted": 20,
                "nb_dubious": 0,
                "nb_unclassified": 1,
                "per_taxon": [{"name": "Calanus"}],
            },
            {
                "sample_id": sample_ids[1],
                "projid": 14853,
                "nb_validated": 11,
                "nb_predicted": 21,
                "nb_dubious": 0,
                "nb_unclassified": 2,
                "per_taxon": [{"name": "Copepoda"}],
            },
        ],
    )

    tools = make_source_tools(thread_id)
    fn = next(t for t in tools if t.name == "summarize_ecotaxa_samples")
    result = fn.invoke({"selection_name": "latest"})

    assert "Sélection : selection_baie_de_baffin_uvp6" in result
    assert "14853000001" in result
    assert "14853000002" in result
    assert "Calanus" in result
    assert "Copepoda" in result


# ── SLICE 2 GATE ──────────────────────────────────────────────────────────────

def test_slice2_summarize_ecotaxa_samples_returns_vpd_breakdown_and_top_taxa():
    """L'agent doit pouvoir scanner un batch de samples (sans télécharger) et voir
    pour chacun : V/P/D counts + top taxa. Source = endpoint EcoTaxa
    /sample_set/taxo_stats (mockée ici).
    """
    fake_stats = [
        {
            "sample_id": 14853000001,
            "used_taxa": [80126, 80155],  # Calanus, Metridia
            "nb_validated": 82,
            "nb_predicted": 340,
            "nb_dubious": 12,
            "nb_unclassified": 0,
            "projid": 14853,
            "per_taxon": [
                {"taxon_id": 80126, "name": "Calanus", "count_V": 62, "count_P": 200, "count_D": 5},
                {"taxon_id": 80155, "name": "Metridia", "count_V": 20, "count_P": 140, "count_D": 7},
            ],
        },
        {
            "sample_id": 14853000002,
            "used_taxa": [80126],
            "nb_validated": 50,
            "nb_predicted": 100,
            "nb_dubious": 3,
            "nb_unclassified": 0,
            "projid": 14853,
            "per_taxon": [
                {"taxon_id": 80126, "name": "Calanus", "count_V": 50, "count_P": 100, "count_D": 3},
            ],
        },
    ]

    with patch("tools.copepod_sources.summarize_samples", return_value=fake_stats):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-slice2")
        fn = next(t for t in tools if t.name == "summarize_ecotaxa_samples")
        result = fn.invoke({"sample_ids": [14853000001, 14853000002]})

    # Les counts V/P/D des deux samples sont visibles.
    assert "14853000001" in result
    assert "14853000002" in result
    assert "82" in result and "340" in result and "12" in result  # sample 1
    assert "50" in result and "100" in result and "3" in result   # sample 2
    # Top taxa surface dans le résumé.
    assert "Calanus" in result
    assert "Metridia" in result


def test_sample_summary_derives_project_id_when_taxo_stats_omits_projid(seeded_cache):
    from core.ecotaxa_browser.sample_summary import summarize_samples

    with patch("core.ecotaxa_browser.sample_summary.EcotaxaClient") as MockClient:
        client = MockClient.return_value
        client.sample_taxo_stats.return_value = [
            {
                "sample_id": 14853000001,
                "used_taxa": [80126],
                "nb_validated": 80,
                "nb_predicted": 8348,
                "nb_dubious": 0,
                "nb_unclassified": 0,
            },
            {
                "sample_id": 14853000003,
                "used_taxa": [80126],
                "nb_validated": 7761,
                "nb_predicted": 11580,
                "nb_dubious": 0,
                "nb_unclassified": 0,
            },
        ]
        client.get_taxon.return_value = {"id": 80126, "display_name": "Calanus"}

        result = summarize_samples([14853000001, 14853000003])

    by_sample = {row["sample_id"]: row for row in result}
    assert by_sample[14853000001]["projid"] == 14853  # from cache
    assert by_sample[14853000003]["projid"] == 14853  # derived from sample_id


# ── SLICE 3 GATE ──────────────────────────────────────────────────────────────

def test_slice3_export_ecotaxa_samples_dry_run_groups_by_project(seeded_cache):
    """Sans confirmed=True, le tool doit montrer le breakdown par projet
    SANS lancer aucun export (CT-AG-06 : confirmation avant op lourde).
    """
    from tools.copepod_sources import make_source_tools
    tools = make_source_tools("thread-slice3-dry")
    fn = next(t for t in tools if t.name == "export_ecotaxa_samples")

    # 3 samples spanning 2 projects (14853 ×2 + 2331 ×1)
    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        result = fn.invoke({
            "sample_ids": [14853000001, 14853000002, 2331000001],
        })
        # Pas de start_export ni de download tant que non confirmé.
        MockClient.return_value.start_export.assert_not_called()

    # Le résumé dry-run liste les deux projets et le nb de samples par projet.
    assert "14853" in result
    assert "2331" in result
    assert "2" in result  # 2 samples sur 14853
    # Marqueur clair que c'est un dry-run en attente de confirmation.
    assert "confirm" in result.lower() or "dry" in result.lower()


def test_export_ecotaxa_samples_dry_run_preflights_every_sample_and_blocks_empty_status(
    seeded_cache,
):
    """Le plan distingue les projets réellement exportables pour le statut demandé."""
    from tools.copepod_sources import make_source_tools

    sample_ids = [14853000001, 14853000002, 2331000001]
    stats = [
        {
            "sample_id": 14853000001,
            "projid": 14853,
            "nb_validated": 0,
            "nb_predicted": 12,
            "nb_dubious": 0,
            "nb_unclassified": 0,
            "per_taxon": [],
        },
        {
            "sample_id": 14853000002,
            "projid": 14853,
            "nb_validated": 0,
            "nb_predicted": 8,
            "nb_dubious": 0,
            "nb_unclassified": 0,
            "per_taxon": [],
        },
        {
            "sample_id": 2331000001,
            "projid": 2331,
            "nb_validated": 5,
            "nb_predicted": 0,
            "nb_dubious": 0,
            "nb_unclassified": 0,
            "per_taxon": [],
        },
    ]

    with patch(
        "tools.copepod_sources.summarize_samples", return_value=stats
    ) as summarize, patch("tools.copepod_sources.EcotaxaClient") as client:
        tool = next(
            item for item in make_source_tools("thread-export-preflight")
            if item.name == "export_ecotaxa_samples"
        )
        result = tool.invoke({"sample_ids": sample_ids, "status": "V"})

    summarize.assert_called_once_with(sample_ids)
    assert "Préflight" in result
    assert "| 14853 | BLOQUÉ |" in result
    assert "aucun objet validé" in result.lower()
    assert "| 2331 | PRÊT |" in result
    assert "1/2 projets exportables" in result
    client.return_value.start_export.assert_not_called()


def test_export_ecotaxa_samples_dry_run_derives_project_for_cache_miss(seeded_cache):
    from tools.copepod_sources import make_source_tools
    tools = make_source_tools("thread-slice3-derived")
    fn = next(t for t in tools if t.name == "export_ecotaxa_samples")

    result = fn.invoke({
        "sample_ids": [14853000001, 14853000003],
    })

    assert "14853" in result
    assert "2" in result
    assert "14853000003" in result
    assert "absents du cache" not in result.lower()


def test_slice3_export_ecotaxa_samples_confirmed_runs_one_export_per_project(seeded_cache):
    """Avec confirmed=True, un query_ecotaxa est lancé par projet (groupage
    automatique via le cache). Les sample_ids sont passés au bon projet."""
    df = pd.DataFrame({"object_id": ["o1", "o2"]})

    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        client = MockClient.return_value
        client.start_export.return_value = 42
        client.wait_for_job.return_value = {"state": "F"}
        client.download_tsv.return_value = df

        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-slice3-go")
        fn = next(t for t in tools if t.name == "export_ecotaxa_samples")
        result = fn.invoke({
            "sample_ids": [14853000001, 14853000002, 2331000001],
            "confirmed": True,
        })

        # Un appel start_export par projet (2 projets distincts).
        assert client.start_export.call_count == 2
        # Pour chaque appel, le bon project_id et les bons sample_ids.
        call_args_by_project = {
            call.args[0] if call.args else call.kwargs.get("project_id"): call
            for call in client.start_export.call_args_list
        }
        assert set(call_args_by_project.keys()) == {14853, 2331}

    assert "14853" in result
    assert "2331" in result
    # Mention de réussite ou de comptage de lignes téléchargées.
    assert "✅" in result or "succès" in result.lower() or "ok" in result.lower()


def test_bulk_export_persists_a_consolidated_campaign_table_for_analysis(seeded_cache):
    """A multi-project campaign becomes one durable active table for the
    immediate analysis, while each raw project export stays available."""
    project_14853 = pd.DataFrame({
        "object_id": ["a", "b"],
        "sample_id": [14853000001, 14853000002],
    })
    project_2331 = pd.DataFrame({
        "object_id": ["c"],
        "sample_id": [2331000001],
    })
    client = _make_fake_client(project_14853)
    # The bulk tool processes project IDs in ascending order: 2331, then 14853.
    client.download_tsv.side_effect = [project_2331, project_14853]
    thread_id = "thread-bulk-campaign-analysis"

    with patch("tools.copepod_sources.EcotaxaClient", return_value=client):
        from tools.copepod_sources import make_source_tools

        export = next(
            tool for tool in make_source_tools(thread_id)
            if tool.name == "export_ecotaxa_samples"
        )
        result = export.invoke({
            "sample_ids": [14853000001, 14853000002, 2331000001],
            "confirmed": True,
        })

    active = _store.get(thread_id)
    campaign_variable = active["meta"]["variable_name"]
    assert campaign_variable.startswith("df_ecotaxa_campaign_samples_")
    campaign = _store.get(f"{thread_id}:dataset:{campaign_variable}")
    assert campaign is not None
    assert campaign["df"].to_dict("records") == [
        {"object_id": "c", "sample_id": 2331000001, "export_project_id": 2331},
        {"object_id": "a", "sample_id": 14853000001, "export_project_id": 14853},
        {"object_id": "b", "sample_id": 14853000002, "export_project_id": 14853},
    ]
    assert active["df"].equals(campaign["df"])
    assert _store.get(f"{thread_id}:ecotaxa")["df"].equals(campaign["df"])
    assert _store.get(f"{thread_id}:dataset:df_ecotaxa_14853_bulk_14853000001_14853000002")["df"].equals(project_14853)
    assert _store.get(f"{thread_id}:dataset:df_ecotaxa_2331_bulk_2331000001")["df"].equals(project_2331)
    assert campaign_variable in result
    assert "## Colonnes de l'export" not in result

    from tools.session_context import build_dataset_state_capsule

    capsule = build_dataset_state_capsule(_store, thread_id)
    assert "shape=3x3" in capsule
    assert "object_id" in capsule
    assert "sample_id" in capsule
    assert "export_project_id" in capsule


def test_bulk_export_reuses_exact_cached_campaign_without_redownload(
    seeded_cache, monkeypatch, tmp_path
):
    """A repeated confirmed export restores every object row from the cache."""
    monkeypatch.setenv("ERDDAP_CACHE_PATH", str(tmp_path / "remote-results.sqlite"))
    exported = pd.DataFrame({
        "object_id": ["a", "b"],
        "sample_id": [14853000001, 14853000002],
    })
    client = _make_fake_client(exported)
    thread_id = "thread-bulk-campaign-cache"

    with patch("tools.copepod_sources.EcotaxaClient", return_value=client):
        from tools.copepod_sources import make_source_tools

        export = next(
            tool for tool in make_source_tools(thread_id)
            if tool.name == "export_ecotaxa_samples"
        )
        first = export.invoke({
            "sample_ids": [14853000001, 14853000002],
            "confirmed": True,
        })
        client.start_export.reset_mock()
        client.download_tsv.reset_mock()
        second = export.invoke({
            "sample_ids": [14853000001, 14853000002],
            "confirmed": True,
        })

    assert "cache" not in first.lower()
    assert "cache" in second.lower()
    client.start_export.assert_not_called()
    client.download_tsv.assert_not_called()
    active = _store.get(thread_id)
    assert active["df"]["object_id"].tolist() == ["a", "b"]
    assert active["meta"]["cache_hit"] is True
    assert active["meta"]["n_rows"] == 2


# ── SLICE 4 GATE ──────────────────────────────────────────────────────────────

def test_project_summary_uses_project_taxo_stats_not_sample_rollup(seeded_cache):
    from core.ecotaxa_browser.project_summary import summarize_projects

    def _project_taxo_stats(project_ids, taxa_ids=""):
        assert project_ids == [14853]
        if taxa_ids == "all":
            return [
                {
                    "projid": 14853,
                    "used_taxa": [80126],
                    "nb_validated": 500,
                    "nb_predicted": 7000,
                    "nb_dubious": 10,
                    "nb_unclassified": 0,
                },
                {
                    "projid": 14853,
                    "used_taxa": [80155],
                    "nb_validated": 1000,
                    "nb_predicted": 1000,
                    "nb_dubious": 40,
                    "nb_unclassified": 200,
                },
            ]
        return [{
            "projid": 14853,
            "used_taxa": [80126, 80155],
            "nb_validated": 1500,
            "nb_predicted": 8000,
            "nb_dubious": 50,
            "nb_unclassified": 200,
        }]

    def _get_taxon(taxon_id):
        return {
            80126: {"display_name": "Calanus"},
            80155: {"display_name": "Metridia"},
        }[taxon_id]

    with patch("core.ecotaxa_browser.project_summary.EcotaxaClient") as MockClient:
        client = MockClient.return_value
        client.project_taxo_stats.side_effect = _project_taxo_stats
        client.get_taxon.side_effect = _get_taxon

        result = summarize_projects([14853])

    assert result[0]["nb_validated"] == 1500
    assert result[0]["nb_predicted"] == 8000
    assert result[0]["nb_dubious"] == 50
    assert result[0]["nb_unclassified"] == 200
    assert result[0]["per_taxon"][0]["name"] == "Calanus"
    assert result[0]["per_taxon"][0]["total"] == 7510
    assert result[0]["per_taxon"][1]["name"] == "Metridia"
    client.sample_taxo_stats.assert_not_called()


def test_slice4_summarize_ecotaxa_projects_returns_overview_per_project():
    """Pendant projet de summarize_ecotaxa_samples : pour chaque project_id,
    renvoie n_samples, envelope géo/temporelle, V/P/D/U project-level
    (via /project_set/taxo_stats), et top taxa.
    """
    fake = [
        {
            "project_id": 14853,
            "n_samples": 20,
            "instruments": ["UVP6"],
            "date_min": "2024-10-01",
            "date_max": "2024-10-15",
            "bbox": {"south": 70.0, "west": -75.0, "north": 76.5, "east": -65.0},
            "nb_validated": 1500,
            "nb_predicted": 8000,
            "nb_dubious": 50,
            "nb_unclassified": 200,
            "used_taxa": [80126, 80155],
            "per_taxon": [
                {"taxon_id": 80126, "name": "Calanus"},
                {"taxon_id": 80155, "name": "Metridia"},
            ],
        },
        {
            "project_id": 2331,
            "n_samples": 8,
            "instruments": ["Loki"],
            "date_min": "2015-07-15",
            "date_max": "2015-08-10",
            "bbox": {"south": 73.0, "west": -68.0, "north": 75.0, "east": -66.0},
            "nb_validated": 400,
            "nb_predicted": 50,
            "nb_dubious": 5,
            "nb_unclassified": 0,
            "used_taxa": [80126],
            "per_taxon": [
                {"taxon_id": 80126, "name": "Calanus"},
            ],
        },
    ]

    with patch("tools.copepod_sources.summarize_projects", return_value=fake):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-slice4")
        fn = next(t for t in tools if t.name == "summarize_ecotaxa_projects")
        result = fn.invoke({"project_ids": [14853, 2331]})

    # Les 2 projets apparaissent.
    assert "14853" in result
    assert "2331" in result
    # n_samples visible.
    assert "20" in result and "8" in result
    # V/P/D/U counts visibles.
    assert "1500" in result and "8000" in result
    assert "400" in result and "50" in result
    # Envelope temporelle.
    assert "2024-10-01" in result and "2024-10-15" in result
    assert "2015-07-15" in result
    # Instruments.
    assert "UVP6" in result and "Loki" in result
    # Top taxa résolus.
    assert "Calanus" in result
    assert "Metridia" in result


def test_summarize_ecotaxa_projects_reports_missing_cache_ids():
    fake = [{
        "project_id": 14853,
        "n_samples": 4,
        "instruments": ["UVP6"],
        "date_min": "2024-10-06",
        "date_max": "2024-10-11",
        "bbox": {"south": 72.69, "west": -78.67, "north": 74.31, "east": -66.73},
        "nb_validated": 0,
        "nb_predicted": 0,
        "nb_dubious": 0,
        "nb_unclassified": 0,
        "used_taxa": [],
        "per_taxon": [],
    }]
    with patch("tools.copepod_sources.summarize_projects", return_value=fake):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-slice4-missing")
        fn = next(t for t in tools if t.name == "summarize_ecotaxa_projects")
        result = fn.invoke({"project_ids": [14853, 2331]})

    assert "14853" in result
    assert "2331" in result
    assert "absent" in result.lower()
    assert "cache" in result.lower()


def test_slice4_summarize_ecotaxa_project_singular_wraps_batch():
    """Variante mono-projet : wrap autour de summarize_ecotaxa_projects."""
    fake = [{
        "project_id": 14853, "n_samples": 1, "instruments": ["UVP6"],
        "date_min": "2024-01-01", "date_max": "2024-12-31",
        "bbox": {"south": 0, "west": 0, "north": 0, "east": 0},
        "nb_validated": 1, "nb_predicted": 0, "nb_dubious": 0, "nb_unclassified": 0,
        "used_taxa": [], "per_taxon": [],
    }]
    with patch("tools.copepod_sources.summarize_projects", return_value=fake):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-slice4-single")
        fn = next(t for t in tools if t.name == "summarize_ecotaxa_project")
        result = fn.invoke({"project_id": 14853})
    assert "14853" in result


def test_slice3_export_ecotaxa_samples_reports_partial_failure(seeded_cache):
    """Si un projet refuse l'export (EXPORT_FAILED), les autres doivent quand
    même passer, et le résumé doit lister succès ET échecs (réutilise
    le marqueur EXPORT_FAILED du fix B)."""
    from tools.ecotaxa_client import EcotaxaExportError
    df = pd.DataFrame({"object_id": ["o1"]})

    def _start_export(project_id, filters):
        if project_id == 14853:
            raise EcotaxaExportError(14853, 403, "User has no Export right")
        return 42

    with patch("tools.copepod_sources.EcotaxaClient") as MockClient:
        client = MockClient.return_value
        client.start_export.side_effect = _start_export
        client.wait_for_job.return_value = {"state": "F"}
        client.download_tsv.return_value = df

        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-slice3-partial")
        fn = next(t for t in tools if t.name == "export_ecotaxa_samples")
        result = fn.invoke({
            "sample_ids": [14853000001, 2331000001],
            "confirmed": True,
        })

    # Succès projet 2331 visible.
    assert "2331" in result
    # Échec projet 14853 explicite avec le marqueur consommé par le system prompt.
    assert "EXPORT_FAILED" in result
    assert "14853" in result
    assert "403" in result or "no Export right" in result


# ── QW1 : search_ecotaxa_taxa — autocomplete taxon ────────────────────────

def test_search_ecotaxa_taxa_returns_markdown_table_of_matches():
    """Le tool doit retourner un tableau markdown listant les candidats."""
    with patch("tools.copepod_sources.search_taxa") as mock_search:
        mock_search.return_value = [
            {
                "taxon_id": 84963,
                "name": "Calanus glacialis",
                "status": "1",
                "in_project": True,
                "aphia_id": 104470,
                "replacement_id": None,
            },
            {
                "taxon_id": 84964,
                "name": "Calanus finmarchicus",
                "status": "1",
                "in_project": True,
                "aphia_id": 104464,
                "replacement_id": None,
            },
        ]
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-qw1")
        fn = next(t for t in tools if t.name == "search_ecotaxa_taxa")
        result = fn.invoke({"query": "Calanus"})

    assert "Calanus glacialis" in result
    assert "Calanus finmarchicus" in result
    assert "84963" in result
    assert "84964" in result
    assert mock_search.call_count == 1
    call_args, call_kwargs = mock_search.call_args
    assert call_args == ("Calanus",) or call_kwargs.get("query") == "Calanus"


def test_search_ecotaxa_taxa_reports_no_match():
    with patch("tools.copepod_sources.search_taxa") as mock_search:
        mock_search.return_value = []
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-qw1-empty")
        fn = next(t for t in tools if t.name == "search_ecotaxa_taxa")
        result = fn.invoke({"query": "zzznotataxon"})

    assert "Aucun" in result or "aucun" in result


def test_search_ecotaxa_taxa_rejects_blank_query():
    from tools.copepod_sources import make_source_tools
    tools = make_source_tools("thread-qw1-blank")
    fn = next(t for t in tools if t.name == "search_ecotaxa_taxa")
    result = fn.invoke({"query": "  "})
    assert "vide" in result.lower() or "blank" in result.lower() or "query" in result.lower()


def test_find_ecotaxa_samples_in_region_surfaces_partial_sync(monkeypatch):
    from tools.copepod_sources import make_source_tools

    monkeypatch.setattr(
        "tools.copepod_sources.samples_in_region",
        lambda **kwargs: {
            "samples": [{
                "sample_id": 1,
                "project_id": 42,
                "lat": 60.0,
                "lon": -80.0,
                "date_min": "2024-01-01",
                "date_max": "2024-01-01",
                "instrument": "UVP6",
            }],
            "total_matching": 1,
            "truncated": False,
            "summary": {},
            "partial": True,
            "sync_in_progress": True,
        },
    )
    fn = next(
        t for t in make_source_tools("thread-partial-samples")
        if t.name == "find_ecotaxa_samples_in_region"
    )

    result = fn.invoke({"project_ids": [42]})

    assert "résultat partiel" in result.lower()
    assert "partial=True" in result


def test_find_ecotaxa_projects_in_region_surfaces_partial_sync(monkeypatch):
    from tools.copepod_sources import make_source_tools

    monkeypatch.setattr(
        "tools.copepod_sources.projects_in_region",
        lambda **kwargs: {
            "projects": [{
                "project_id": 42,
                "sample_count": 1,
                "object_count": 10,
                "instruments": ["UVP6"],
                "date_min": "2024-01-01",
                "date_max": "2024-01-01",
            }],
            "total_projects": 1,
            "total_samples": 1,
            "partial": True,
            "sync_in_progress": True,
        },
    )
    fn = next(
        t for t in make_source_tools("thread-partial-projects")
        if t.name == "find_ecotaxa_projects_in_region"
    )

    result = fn.invoke({"project_ids": [42]})

    assert "résultat partiel" in result.lower()
    assert "partial=True" in result


def test_find_ecotaxa_observations_surfaces_partial_sync(monkeypatch):
    from tools.copepod_sources import make_source_tools

    monkeypatch.setattr(
        "tools.copepod_sources.find_observations",
        lambda **kwargs: {
            "taxon": {"matched_name": "Copepoda"},
            "status_filter": "V",
            "samples": [{
                "sample_id": 1,
                "project_id": 42,
                "lat": 60.0,
                "lon": -80.0,
                "date_min": "2024-01-01",
                "date_max": "2024-01-01",
            }],
            "total_matching": 1,
            "truncated": False,
            "attested_projects": [42],
            "partial": True,
            "sync_in_progress": True,
        },
    )
    fn = next(
        t for t in make_source_tools("thread-partial-observations")
        if t.name == "find_ecotaxa_observations"
    )

    result = fn.invoke({"taxon": "Copepoda"})

    assert "résultat partiel" in result.lower()
    assert "partial=True" in result


def test_group_ecotaxa_samples_by_year_requires_filter():
    from tools.copepod_sources import make_source_tools
    tools = make_source_tools("thread-year-no-filter")
    fn = next(t for t in tools if t.name == "group_ecotaxa_samples_by_year")
    result = fn.invoke({})
    assert "filtre" in result.lower()


def test_group_ecotaxa_samples_by_year_renders_year_table_and_stores_selection():
    from unittest.mock import patch
    fake = {
        "years": [
            {"year": 2018, "n_samples": 2, "n_stations": 2, "date_min": "2018-07-02",
             "date_max": "2018-08-14", "instruments": ["UVP5"], "project_ids": [42, 240],
             "sample_ids": [1, 2]},
            {"year": 2019, "n_samples": 1, "n_stations": 1, "date_min": "2019-07-05",
             "date_max": "2019-07-05", "instruments": ["UVP5"], "project_ids": [388],
             "sample_ids": [3]},
        ],
        "total_matching": 3, "n_years": 2, "station": None,
        "sample_ids": [1, 2, 3], "partial": False, "sync_in_progress": False,
    }
    with patch("tools.copepod_sources.samples_by_year", return_value=fake):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-year-render")
        fn = next(t for t in tools if t.name == "group_ecotaxa_samples_by_year")
        result = fn.invoke({"zone_name": "Baie de Baffin"})

    assert "2018" in result and "2019" in result
    assert "n_stations" in result
    assert "Sélection mémorisée" in result
    # la sélection couvre bien les 3 samples multi-années
    export_tool = next(t for t in tools if t.name == "export_ecotaxa_samples")
    import re
    m = re.search(r"`(selection_[^`]+)`", result)
    assert m, "nom de sélection introuvable dans la sortie"


def test_group_ecotaxa_samples_by_year_station_filter_passed_through():
    from unittest.mock import patch
    captured = {}

    def _fake(**kwargs):
        captured.update(kwargs)
        return {"years": [], "total_matching": 0, "n_years": 0,
                "station": kwargs.get("station"), "sample_ids": [],
                "partial": False, "sync_in_progress": False}

    with patch("tools.copepod_sources.samples_by_year", side_effect=_fake):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-year-station")
        fn = next(t for t in tools if t.name == "group_ecotaxa_samples_by_year")
        fn.invoke({"station": "St-27"})

    assert captured["station"] == "St-27"


def test_group_ecotaxa_samples_by_year_depth_filters_passed_through():
    from unittest.mock import patch
    captured = {}

    def _fake(**kwargs):
        captured.update(kwargs)
        return {"years": [], "total_matching": 0, "n_years": 0,
                "station": None, "sample_ids": [],
                "partial": False, "sync_in_progress": False}

    with patch("tools.copepod_sources.samples_by_year", side_effect=_fake):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-year-depth")
        fn = next(t for t in tools if t.name == "group_ecotaxa_samples_by_year")
        fn.invoke({
            "zone_name": "Baie de Baffin",
            "depth_min_gte": 50,
            "depth_max_lt": 200,
        })

    assert captured["depth_min_gte"] == 50
    assert captured["depth_max_lt"] == 200
    assert captured["depth_max_gte"] is None
    assert captured["depth_min_lt"] is None


def test_group_ecotaxa_samples_by_year_depth_alone_is_a_valid_filter():
    from unittest.mock import patch

    def _fake(**kwargs):
        return {"years": [], "total_matching": 0, "n_years": 0,
                "station": None, "sample_ids": [],
                "partial": False, "sync_in_progress": False}

    with patch("tools.copepod_sources.samples_by_year", side_effect=_fake):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-year-depth-only")
        fn = next(t for t in tools if t.name == "group_ecotaxa_samples_by_year")
        result = fn.invoke({"depth_min_gte": 100, "depth_max_lt": 300})

    # profondeur seule ne doit PAS déclencher l'erreur « au moins un filtre »
    assert "filtre requis" not in result.lower()


def test_group_ecotaxa_samples_by_year_stores_depth_in_selection_filters():
    from unittest.mock import patch
    fake = {
        "years": [
            {"year": 2018, "n_samples": 2, "n_stations": 1, "date_min": "2018-07-02",
             "date_max": "2018-08-14", "instruments": ["UVP5"], "project_ids": [42],
             "sample_ids": [1, 2]},
        ],
        "total_matching": 2, "n_years": 1, "station": None,
        "sample_ids": [1, 2], "partial": False, "sync_in_progress": False,
    }
    with patch("tools.copepod_sources.samples_by_year", return_value=fake):
        from tools.copepod_sources import make_source_tools
        tools = make_source_tools("thread-year-depth-sel")
        fn = next(t for t in tools if t.name == "group_ecotaxa_samples_by_year")
        fn.invoke({"zone_name": "Baie de Baffin", "depth_min_gte": 50, "depth_max_lt": 200})

    # la sélection mémorisée doit tracer la tranche de profondeur pour l'export
    meta = _store.get("thread-year-depth-sel:ecotaxa_selection_latest")
    filters = (meta or {}).get("meta", {}).get("filters", {})
    assert filters.get("depth_min_gte") == 50
    assert filters.get("depth_max_lt") == 200


def test_add_year_column_from_object_date():
    import pandas as pd
    from tools.copepod_sources import _add_year_column
    df = pd.DataFrame({
        "sample_id": [1, 2, 3],
        "object_date": ["20150422", "20240730", "20241011"],
        "taxon": ["Calanus", "Oithona", "Calanus"],
    })
    out = _add_year_column(df)
    assert list(out.columns)[0] == "year"
    assert out["year"].tolist() == [2015, 2024, 2024]


def test_add_year_column_noop_without_date_column():
    import pandas as pd
    from tools.copepod_sources import _add_year_column
    df = pd.DataFrame({"sample_id": [1], "taxon": ["Calanus"]})
    out = _add_year_column(df)
    assert "year" not in out.columns  # rien à dériver, DataFrame inchangé


def test_add_year_column_handles_iso_dates():
    import pandas as pd
    from tools.copepod_sources import _add_year_column
    df = pd.DataFrame({"sample_id": [1, 2], "sample_date": ["2015-04-22", "2024-07-30"]})
    out = _add_year_column(df)
    assert out["year"].tolist() == [2015, 2024]


def test_query_ecotaxa_cache_persists_select_as_dataframe(tmp_path, monkeypatch):
    import sqlite3

    import tools.copepod_sources as source_module
    from core.ecotaxa_browser.cache.repo import init_schema
    from tools.session_store import SessionStore

    cache_db = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(cache_db)
    init_schema(conn)
    conn.execute(
        "INSERT INTO samples_cache "
        "(sample_id, project_id, station_id, profile_id, date_min, date_max, last_synced) "
        "VALUES (1, 10, 'ST-1', 'CAST-1', '2024-01-01', '2024-01-01', 'test')"
    )
    conn.commit()
    conn.close()

    store = SessionStore(tmp_path / "sessions")
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))
    monkeypatch.setattr(source_module, "_store", store)

    tool = next(
        item for item in source_module.make_source_tools("sql-query-thread")
        if item.name == "query_ecotaxa_cache"
    )
    result = tool.invoke({
        "sql": "SELECT station_id, COUNT(*) AS n FROM samples_cache GROUP BY station_id"
    })

    session = store.get("sql-query-thread")
    assert "lignes retournées" in result
    assert "toutes les 1 lignes" in result
    assert "station_id" in result
    assert session["meta"]["variable_name"] == "df_ecotaxa_cache_query"
    assert session["df"].to_dict("records") == [{"station_id": "ST-1", "n": 1}]


def test_net_uvp_match_tool_requires_explicit_call_and_matches_by_deployment(tmp_path, monkeypatch):
    """The matching tool is opt-in and persists only time-compatible joins."""
    import sqlite3

    import tools.copepod_sources as source_module
    from core.ecotaxa_browser.cache.repo import init_schema
    from tools.dataset_registry import store_dataset
    from tools.session_store import SessionStore

    cache_db = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(cache_db)
    init_schema(conn)
    conn.execute(
        "INSERT INTO samples_cache "
        "(sample_id, project_id, station_id, profile_id, cruise_id, ctd_rosette_filename, instrument, "
        "lat_avg, lon_avg, date_min, datetime_min, last_synced) "
        "VALUES (1, 10, 'cache-name', 'uvp_profile', 'amundsen2024', '062', 'UVP5SD', "
        "67.5, -63.8, '2024-06-02', '2024-06-02T00:00:00', 'test')"
    )
    conn.commit()
    conn.close()

    thread_id = "net-uvp-thread"
    store = SessionStore(tmp_path / "sessions")
    store_dataset(
        store,
        thread_id,
        pd.DataFrame(
            {
                "Sample ID": [101, 102, 103],
                "Deployment ID": [7, 7, 6],
                    "Station Name": ["cache-name", "cache-name", "cache-name"],
                "Latitude": [67.5, 67.5, 67.5],
                "Longitude": [-63.8, -63.8, -63.8],
                "Deployment Datetime Start": ["2024-06-01", "2024-06-01", "2022-06-01"],
            }
        ),
        variable_name="df_file_net",
        meta={"source": "file"},
        is_loaded_file=True,
    )
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))
    monkeypatch.setattr(source_module, "_store", store)
    import tools.amundsen_sources as amundsen_module
    metadata_call = {}

    def fake_fetch_ctd_metadata(**kwargs):
        metadata_call.update(kwargs)
        return pd.DataFrame({
            "filename": ["2406_062.int.nc"],
            "station": ["cache-name"],
            "cast_number": [62],
            "latitude": [67.5],
            "longitude": [-63.8],
            "time": ["2024-06-02T00:00:00Z"],
        })

    monkeypatch.setattr(
        amundsen_module,
        "_fetch_amundsen_ctd_metadata_by_filename",
        fake_fetch_ctd_metadata,
        raising=False,
    )

    tool = next(
        item for item in source_module.make_source_tools(thread_id)
        if item.name == "find_uvp_matches_for_net_table"
    )
    assert tool.args_schema.model_fields["max_time_gap_days"].default == 0.5
    result = tool.invoke({"date_from": "2023-01-01", "max_time_gap_days": 1.0})

    assert "jointures certifiées : 1." in result
    assert "Station concordante : 1 déploiement(s) sur 1." in result
    assert "net_sample_id" not in result
    assert "Étape suivante" not in result
    matches = store.get(f"{thread_id}:dataset:df_net_uvp_matches")["df"]
    assert matches["net_sample_id"].tolist() == [101, 102]
    assert matches["net_deployment_id"].eq("7").all()
    assert matches["uvp_sample_id"].eq(1).all()
    assert matches["join_eligible"].all()
    assert matches["match_status"].eq("matched").all()
    assert matches["ctd_filename_match_status"].eq("matched").all()
    assert "62" in metadata_call["filename_aliases"]

    def unavailable_ctd_metadata(**_kwargs):
        raise TimeoutError("Amundsen indisponible")

    monkeypatch.setattr(
        amundsen_module,
        "_fetch_amundsen_ctd_metadata_by_filename",
        unavailable_ctd_metadata,
        raising=False,
    )
    unavailable_result = tool.invoke({"date_from": "2023-01-01", "max_time_gap_days": 1.0})
    unavailable_matches = store.get(f"{thread_id}:dataset:df_net_uvp_matches")["df"]
    assert "CTD Amundsen indisponible : export provisoire possible" in unavailable_result
    assert "variables CTD n'ont pas été reçus" not in unavailable_result
    assert "Aucune paire synchrone" not in unavailable_result
    assert unavailable_matches["ctd_filename_match_status"].eq("source_unavailable").all()
    assert not unavailable_matches["join_eligible"].any()


def test_net_uvp_audit_prefers_station_id_over_station_name_when_both_exist(
    tmp_path, monkeypatch
):
    """La clé stable station_id prime sur un libellé de station affiché."""
    from tools.dataset_registry import store_dataset

    def fetch_ctd_metadata(**_kwargs):
        return pd.DataFrame(
            {
                "filename": ["2406_062.int.nc"],
                "station": ["ST-101"],
                "cast_number": [62],
                "latitude": [67.5],
                "longitude": [-63.8],
                "time": ["2024-06-02T00:00:00Z"],
            }
        )

    tool, store, thread_id = _net_uvp_certification_tool(
        tmp_path, monkeypatch, fetch_ctd_metadata
    )
    store_dataset(
        store,
        thread_id,
        pd.DataFrame(
            {
                "Sample ID": [501],
                "Deployment ID": [1],
                "Station Name": ["Nom lisible différent"],
                "Station ID": ["ST-101"],
                "Latitude": [67.5],
                "Longitude": [-63.8],
                "Deployment Datetime Start": ["2024-06-01"],
            }
        ),
        variable_name="df_file_baffin_2024",
        meta={"source": "file"},
        is_loaded_file=True,
    )

    result = tool.invoke(
        {"net_variable_name": "df_file_baffin_2024", "max_time_gap_days": 1.0}
    )

    assert "jointures certifiées : 1." in result
    audit = store.get(f"{thread_id}:dataset:df_net_uvp_matches")["df"]
    assert audit["station"].tolist() == ["ST-101"]
    assert audit["station_name_match"].all()


def test_net_uvp_audit_rejects_loaded_file_after_scoped_subsets_exist(tmp_path, monkeypatch):
    """Une préparation ciblée ne doit jamais retomber sur le fichier complet."""
    import tools.copepod_sources as source_module
    from tools.dataset_registry import store_dataset
    from tools.session_store import SessionStore

    thread_id = "net-uvp-scoped-guard"
    store = SessionStore(tmp_path / "sessions")
    raw = pd.DataFrame({"station": ["A"], "latitude": [74.0], "longitude": [-68.0]})
    store_dataset(
        store, thread_id, raw, variable_name="df_file_net",
        meta={"source": "file"}, is_loaded_file=True,
    )
    store_dataset(
        store, thread_id, raw, variable_name="df_net_uvp_scope_baffin_2024",
        meta={"source": "net_uvp_audit_subset"}, set_active=False,
    )
    monkeypatch.setattr(source_module, "_store", store)
    tool = next(
        item for item in source_module.make_source_tools(thread_id)
        if item.name == "find_uvp_matches_for_net_table"
    )

    result = tool.invoke({"net_variable_name": "df_file_net"})

    assert "sous-ensembles préparés" in result
    assert "df_net_uvp_scope_baffin_2024" in result


def _selection_name_from(result: str) -> str:
    import re

    match = re.search(r"`selection:([^`]+)`", result)
    assert match, result
    return match.group(1)


def _net_uvp_certification_tool(
    tmp_path,
    monkeypatch,
    fetch_ctd_metadata,
    *,
    row_order: list[int] | None = None,
    duplicate_first_row: bool = False,
):
    import sqlite3

    import tools.amundsen_sources as amundsen_module
    import tools.copepod_sources as source_module
    from core.ecotaxa_browser.cache.repo import init_schema
    from tools.dataset_registry import store_dataset
    from tools.session_store import SessionStore

    tmp_path.mkdir(parents=True, exist_ok=True)
    cache_db = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(cache_db)
    init_schema(conn)
    conn.executemany(
        "INSERT INTO samples_cache "
        "(sample_id, project_id, station_id, profile_id, cruise_id, ctd_rosette_filename, instrument, "
        "lat_avg, lon_avg, date_min, datetime_min, last_synced) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (101, 10, "ST-101", "uvp-101", "amundsen2024", "062", "UVP5SD", 67.5, -63.8, "2024-06-02", "2024-06-02T00:00:00", "test"),
            (203, 20, "ST-203", "uvp-203", "amundsen2024", "063", "UVP5SD", 68.0, -64.0, "2024-06-03", "2024-06-03T00:00:00", "test"),
            (404, 30, "ST-404", "uvp-404", "amundsen2024", "064", "UVP5SD", 68.5, -64.2, "2024-06-04", "2024-06-04T00:00:00", "test"),
        ],
    )
    conn.commit()
    conn.close()

    thread_id = "net-uvp-certified-thread"
    store = SessionStore(tmp_path / "sessions")
    net_rows = pd.DataFrame(
        {
            "Sample ID": [501, 502, 503],
            "Deployment ID": [1, 2, 3],
            "Station Name": ["ST-101", "ST-203", "ST-404"],
            "Latitude": [67.5, 68.0, 68.5],
            "Longitude": [-63.8, -64.0, -64.2],
            "Deployment Datetime Start": ["2024-06-01", "2024-06-02", "2024-06-03"],
        }
    )
    if duplicate_first_row:
        duplicate = net_rows.iloc[[0]].copy()
        duplicate["Sample ID"] = 504
        duplicate["Deployment ID"] = 4
        net_rows = pd.concat([net_rows, duplicate], ignore_index=True)
    if row_order:
        net_rows = net_rows.iloc[row_order].reset_index(drop=True)

    store_dataset(
        store,
        thread_id,
        net_rows,
        variable_name="df_file_baffin_2024",
        meta={"source": "file"},
        is_loaded_file=True,
    )
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))
    monkeypatch.setattr(source_module, "_store", store)
    monkeypatch.setattr(
        amundsen_module,
        "_fetch_amundsen_ctd_metadata_by_filename",
        fetch_ctd_metadata,
        raising=False,
    )
    tool = next(
        item for item in source_module.make_source_tools(thread_id)
        if item.name == "find_uvp_matches_for_net_table"
    )
    return tool, store, thread_id


def test_audit_publishes_only_ctd_certified_selection(tmp_path, monkeypatch):
    def fetch_ctd_metadata(**_kwargs):
        return pd.DataFrame(
            {
                "filename": ["2406_062.int.nc", "2406_063.int.nc"],
                "station": ["ST-101", "ST-203"],
                "cast_number": [62, 63],
                "latitude": [67.5, 68.0],
                "longitude": [-63.8, -64.0],
                "time": ["2024-06-02T00:00:00Z", "2024-06-03T00:00:00Z"],
            }
        )

    tool, store, thread_id = _net_uvp_certification_tool(
        tmp_path, monkeypatch, fetch_ctd_metadata
    )

    result = tool.invoke({"net_variable_name": "df_file_baffin_2024", "max_time_gap_days": 1.0})

    name = _selection_name_from(result)
    meta = store.get(f"{thread_id}:selection:{name}")["meta"]
    assert meta["sample_ids"] == [101, 203]
    assert meta["project_ids"] == [10, 20]
    assert meta["source"] == "net_uvp_certified_selection"
    assert meta["audit_variable"] == "df_net_uvp_matches"
    assert meta["net_variable_name"] == "df_file_baffin_2024"
    audit_meta = store.get(f"{thread_id}:dataset:df_net_uvp_matches")["meta"]
    assert meta["net_dataframe_fingerprint"] == audit_meta[
        "net_dataframe_fingerprint"
    ]
    assert meta["date_from"] is None
    assert meta["date_to"] is None


def test_audit_without_ctd_certificate_creates_no_selection(tmp_path, monkeypatch):
    def unavailable_ctd_metadata(**_kwargs):
        raise TimeoutError("Amundsen indisponible")

    tool, store, thread_id = _net_uvp_certification_tool(
        tmp_path, monkeypatch, unavailable_ctd_metadata
    )

    tool.invoke({"net_variable_name": "df_file_baffin_2024"})

    assert not any(
        ":selection:net_uvp_certified_" in key for key in store.keys(thread_id)
    )


def test_audit_unavailable_ctd_opt_in_publishes_exploratory_selection(
    tmp_path, monkeypatch
):
    def unavailable_ctd_metadata(**_kwargs):
        raise TimeoutError("Amundsen indisponible")

    tool, store, thread_id = _net_uvp_certification_tool(
        tmp_path, monkeypatch, unavailable_ctd_metadata
    )

    result = tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "allow_unverified_ctd": True,
            "max_time_gap_days": 1.0,
        }
    )

    name = _selection_name_from(result)
    selection_meta = store.get(f"{thread_id}:selection:{name}")["meta"]
    audit = store.get(f"{thread_id}:dataset:df_net_uvp_matches")

    assert selection_meta["source"] == "net_uvp_exploratory_selection"
    assert selection_meta["ctd_verification"] == "unavailable"
    assert selection_meta["exploratory"] is True
    assert audit["meta"]["ctd_verification"] == "unavailable"
    assert audit["meta"]["exploratory"] is True
    eligible = audit["df"]["spatiotemporal_eligible"]
    assert audit["df"].loc[eligible, "ctd_verification"].eq("unavailable").all()
    assert audit["df"].loc[eligible, "exploratory"].all()
    assert not audit["df"]["join_eligible"].any()
    assert "CTD non vérifié" in result


def test_audit_ctd_no_match_never_publishes_exploratory_selection(
    tmp_path, monkeypatch
):
    tool, store, thread_id = _net_uvp_certification_tool(
        tmp_path, monkeypatch, lambda **_kwargs: pd.DataFrame()
    )

    tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "allow_unverified_ctd": True,
        }
    )

    assert not any(
        ":selection:net_uvp_exploratory_" in key
        for key in store.keys(thread_id)
    )


def test_empty_exploratory_audit_invalidates_latest_selection(
    tmp_path, monkeypatch
):
    """A failed re-audit cannot make a later dry-run reuse another scope."""
    tool, store, thread_id = _net_uvp_certification_tool(
        tmp_path, monkeypatch, lambda **_kwargs: pd.DataFrame()
    )
    store.set(
        f"{thread_id}:ecotaxa_selection_latest",
        None,
        {
            "selection_name": "old_other_file_scope",
            "sample_ids": [999999],
            "project_ids": [999],
            "n_samples": 1,
        },
    )

    tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "allow_unverified_ctd": True,
        }
    )

    latest = store.get(f"{thread_id}:ecotaxa_selection_latest")
    assert latest["meta"]["source"] == "net_uvp_empty_selection"
    assert latest["meta"]["sample_ids"] == []


def test_export_after_empty_net_uvp_audit_explains_no_validated_match(
    tmp_path, monkeypatch
):
    """An export request after a failed audit must explain the outcome plainly."""
    import tools.copepod_sources as source_module

    tool, _store, thread_id = _net_uvp_certification_tool(
        tmp_path, monkeypatch, lambda **_kwargs: pd.DataFrame()
    )
    tool.invoke({"net_variable_name": "df_file_baffin_2024"})
    latest = _store.get(f"{thread_id}:ecotaxa_selection_latest")
    assert latest["meta"]["source"] == "net_uvp_empty_selection"

    export = next(
        item for item in source_module.make_source_tools(thread_id)
        if item.name == "export_ecotaxa_samples"
    )
    result = export.invoke({"selection_name": "latest"})

    assert "Aucune correspondance validée à exporter" in result
    assert "Relance une recherche EcoTaxa" not in result


def test_audit_selection_is_canonical_across_permuted_matches(tmp_path, monkeypatch):
    def fetch_ctd_metadata(**_kwargs):
        return pd.DataFrame(
            {
                "filename": ["2406_062.int.nc", "2406_063.int.nc"],
                "station": ["ST-101", "ST-203"],
                "cast_number": [62, 63],
                "latitude": [67.5, 68.0],
                "longitude": [-63.8, -64.0],
                "time": ["2024-06-02T00:00:00Z", "2024-06-03T00:00:00Z"],
            }
        )

    first_tool, first_store, first_thread = _net_uvp_certification_tool(
        tmp_path / "first", monkeypatch, fetch_ctd_metadata
    )
    first_name = _selection_name_from(
        first_tool.invoke({"net_variable_name": "df_file_baffin_2024", "max_time_gap_days": 1.0})
    )
    first_meta = first_store.get(f"{first_thread}:selection:{first_name}")["meta"]

    second_tool, second_store, second_thread = _net_uvp_certification_tool(
        tmp_path / "second", monkeypatch, fetch_ctd_metadata, row_order=[2, 1, 0]
    )
    second_name = _selection_name_from(
        second_tool.invoke({"net_variable_name": "df_file_baffin_2024", "max_time_gap_days": 1.0})
    )
    second_meta = second_store.get(f"{second_thread}:selection:{second_name}")["meta"]

    assert first_name == second_name
    assert first_meta["sample_ids"] == second_meta["sample_ids"] == [101, 203]
    assert first_meta["project_ids"] == second_meta["project_ids"] == [10, 20]


def test_audit_selection_deduplicates_repeated_certified_project_sample_pair(
    tmp_path, monkeypatch
):
    def fetch_ctd_metadata(**_kwargs):
        return pd.DataFrame(
            {
                "filename": ["2406_062.int.nc", "2406_063.int.nc"],
                "station": ["ST-101", "ST-203"],
                "cast_number": [62, 63],
                "latitude": [67.5, 68.0],
                "longitude": [-63.8, -64.0],
                "time": ["2024-06-02T00:00:00Z", "2024-06-03T00:00:00Z"],
            }
        )

    tool, store, thread_id = _net_uvp_certification_tool(
        tmp_path, monkeypatch, fetch_ctd_metadata, duplicate_first_row=True
    )

    name = _selection_name_from(
        tool.invoke({"net_variable_name": "df_file_baffin_2024", "max_time_gap_days": 1.0})
    )
    meta = store.get(f"{thread_id}:selection:{name}")["meta"]

    assert meta["sample_ids"] == [101, 203]
    assert meta["project_ids"] == [10, 20]
    assert meta["n_samples"] == 2


def test_audit_with_empty_ctd_response_creates_no_selection(tmp_path, monkeypatch):
    tool, store, thread_id = _net_uvp_certification_tool(
        tmp_path, monkeypatch, lambda **_kwargs: pd.DataFrame()
    )

    tool.invoke({"net_variable_name": "df_file_baffin_2024"})

    assert not any(
        ":selection:net_uvp_certified_" in key for key in store.keys(thread_id)
    )


def _net_uvp_enriched_tool(
    tmp_path,
    monkeypatch,
    *,
    audit_meta: dict | None = None,
    exploratory_audit: bool = False,
    enriched_meta: dict | None = None,
    enriched_has_object_id: bool = True,
    net_density_first: float = 12.0,
):
    import tools.copepod_sources as source_module
    from tools.dataset_registry import store_dataset
    from tools.session_store import SessionStore

    thread_id = "net-uvp-enriched-thread"
    store = SessionStore(tmp_path / "sessions")
    net_df = pd.DataFrame(
        {
            "SAMPLE_ID": [501, 502],
            "ANALYSIS_ID": [9001, 9002],
            "TAXON_ID": ["Calanus", "Oithona"],
            "CLASS": ["Copepoda", "Copepoda"],
            "MIN_SAMPLE_DEPTH": [0.0, 10.0],
            "MAX_SAMPLE_DEPTH": [10.0, 20.0],
            "ALL_STAGES_ABUND (ind./m3 depth vol.)": [
                net_density_first,
                15.0,
            ],
            "net_density_ind_m3": [net_density_first, 15.0],
        }
    )
    store_dataset(
        store,
        thread_id,
        net_df,
        variable_name="df_file_baffin_2024",
        meta={"source": "file"},
        is_loaded_file=True,
    )
    audit_df = pd.DataFrame(
        {
            "net_sample_id": [501, 502],
            "uvp_project_id": [10, 20],
            "uvp_profile_str": ["uvp-101", "uvp-203"],
            "join_eligible": [not exploratory_audit, False],
            "ctd_filename_join_eligible": [not exploratory_audit, False],
        }
    )
    if exploratory_audit:
        audit_df["ctd_verification"] = ["unavailable", "unavailable"]
        audit_df["exploratory"] = [True, True]
    store_dataset(
        store,
        thread_id,
        audit_df,
        variable_name="df_net_uvp_matches",
        meta=audit_meta or {
            "source": "net_uvp_match",
            "net_variable_name": "df_file_baffin_2024",
            "ctd_filename_verified": 0 if exploratory_audit else 1,
            "ctd_verification": (
                "unavailable" if exploratory_audit else "verified"
            ),
            "exploratory": exploratory_audit,
            "allow_unverified_ctd": exploratory_audit,
            "net_dataframe_fingerprint": source_module._net_dataframe_fingerprint(
                net_df
            ),
        },
        set_active=False,
    )
    enriched = {
        "export_project_id": [10, 10, 20],
        "sample_profileid": ["uvp-101", "uvp-101", "uvp-203"],
        "depth_bin": [2.5, 7.5, 12.5],
        "object_annotation_hierarchy": [
            "living>Crustacea>Copepoda",
            "living>Crustacea>Copepoda",
            "living>Crustacea>Copepoda",
        ],
        "ecopart_Sampled volume [L]": [100.0, 50.0, float("nan")],
    }
    if enriched_has_object_id:
        enriched["object_id"] = ["obj-1", "obj-2", "obj-3"]
    store_dataset(
        store,
        thread_id,
        pd.DataFrame(enriched),
        variable_name="df_ecotaxa_ecopart_campaign",
        meta=enriched_meta or {"source": "join:ecotaxa_campaign+ecopart"},
        set_active=False,
    )
    monkeypatch.setattr(source_module, "_store", store)

    join_tool = next(
        item for item in source_module.make_source_tools(thread_id)
        if item.name == "join_net_uvp_enriched"
    )
    return join_tool, store, thread_id


def test_join_net_uvp_enriched_persists_certified_object_rows(
    tmp_path, monkeypatch
):
    join_tool, store, thread_id = _net_uvp_enriched_tool(tmp_path, monkeypatch)

    join_tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign",
        }
    )

    stored = store.get(f"{thread_id}:dataset:df_net_uvp_ecopart")
    assert stored["df"]["object_id"].tolist() == ["obj-1", "obj-2"]
    assert stored["df"]["join_eligible"].all()
    assert "ecopart_Sampled volume [L]" in stored["df"]
    assert stored["meta"]["source"] == "net_uvp_ecopart_certified"
    assert stored["meta"]["net_variable_name"] == "df_file_baffin_2024"
    assert stored["meta"]["audit_variable_name"] == "df_net_uvp_matches"
    assert stored["meta"]["uvp_enriched_variable"] == "df_ecotaxa_ecopart_campaign"


def test_join_net_uvp_enriched_keeps_available_subset_of_certified_audit(
    tmp_path, monkeypatch
):
    """A density extract may cover only part of a certified metadata audit."""
    from tools.dataset_registry import store_dataset

    join_tool, store, thread_id = _net_uvp_enriched_tool(tmp_path, monkeypatch)
    net = store.get(f"{thread_id}:dataset:df_file_baffin_2024")["df"].iloc[[0]].copy()
    store_dataset(
        store,
        thread_id,
        net,
        variable_name="df_file_baffin_2024_abundance",
        meta={"source": "file:abundance"},
        set_active=False,
    )
    audit_entry = store.get(f"{thread_id}:dataset:df_net_uvp_matches")
    audit = audit_entry["df"].copy()
    audit["join_eligible"] = True
    audit["ctd_filename_join_eligible"] = True
    store_dataset(
        store,
        thread_id,
        audit,
        variable_name="df_net_uvp_matches",
        meta=audit_entry["meta"],
        set_active=False,
    )

    result = join_tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024_abundance",
            "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign",
        }
    )

    assert "df_net_uvp_strata" in result
    assert "1/2 prélèvement(s) certifié(s)" in result
    strata = store.get(f"{thread_id}:dataset:df_net_uvp_strata")["df"]
    assert strata["net_sample_id"].tolist() == [501]


def test_join_net_uvp_enriched_avoids_materializing_large_taxa_object_fanout(
    tmp_path, monkeypatch
):
    """The tool must persist strates, not a huge taxon×object inspection table."""
    import tools.copepod_sources as source_module

    join_tool, store, thread_id = _net_uvp_enriched_tool(tmp_path, monkeypatch)
    net_entry = store.get(f"{thread_id}:dataset:df_file_baffin_2024")
    net = pd.DataFrame(
        {
            "SAMPLE_ID": [501] * 401,
            "ANALYSIS_ID": [9001] * 401,
            "TAXON_ID": list(range(401)),
            "CLASS": ["Copepoda"] * 401,
            "MIN_SAMPLE_DEPTH": [0.0] * 401,
            "MAX_SAMPLE_DEPTH": [10.0] * 401,
            "ALL_STAGES_ABUND (ind./m3 depth vol.)": [1.0] * 401,
        }
    )
    store.set(f"{thread_id}:dataset:df_file_baffin_2024", net, net_entry["meta"])
    audit_entry = store.get(f"{thread_id}:dataset:df_net_uvp_matches")
    audit_meta = dict(audit_entry["meta"])
    audit_meta["net_dataframe_fingerprint"] = source_module._net_dataframe_fingerprint(net)
    store.set(
        f"{thread_id}:dataset:df_net_uvp_matches",
        audit_entry["df"],
        audit_meta,
    )
    enriched_entry = store.get(f"{thread_id}:dataset:df_ecotaxa_ecopart_campaign")
    enriched = pd.DataFrame(
        {
            "export_project_id": [10] * 251,
            "sample_profileid": ["uvp-101"] * 251,
            "object_id": [f"object-{index}" for index in range(251)],
            "depth_bin": [5.0] * 251,
            "object_annotation_hierarchy": ["living>Crustacea>Copepoda"] * 251,
            "ecopart_Sampled volume [L]": [100.0] * 251,
        }
    )
    store.set(
        f"{thread_id}:dataset:df_ecotaxa_ecopart_campaign",
        enriched,
        enriched_entry["meta"],
    )

    text = join_tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign",
        }
    )

    strata = store.get(f"{thread_id}:dataset:df_net_uvp_strata")["df"]
    assert store.get(f"{thread_id}:dataset:df_net_uvp_ecopart") is None
    assert "sans matérialiser" in text
    assert strata["net_abundance_ind_m3"].tolist() == pytest.approx([401.0])
    assert strata["uvp_target_count"].tolist() == [251]


def test_join_net_uvp_enriched_discards_irrelevant_profiles_before_sizing_fanout(
    tmp_path, monkeypatch
):
    """Unrelated enriched profiles must not turn a small certified join into a large one."""
    import tools.copepod_sources as source_module

    join_tool, store, thread_id = _net_uvp_enriched_tool(tmp_path, monkeypatch)
    net_entry = store.get(f"{thread_id}:dataset:df_file_baffin_2024")
    net = pd.DataFrame(
        {
            "SAMPLE_ID": [501] * 300,
            "ANALYSIS_ID": [9001] * 300,
            "TAXON_ID": list(range(300)),
            "CLASS": ["Copepoda"] * 300,
            "MIN_SAMPLE_DEPTH": [0.0] * 300,
            "MAX_SAMPLE_DEPTH": [10.0] * 300,
            "ALL_STAGES_ABUND (ind./m3 depth vol.)": [1.0] * 300,
        }
    )
    store.set(f"{thread_id}:dataset:df_file_baffin_2024", net, net_entry["meta"])
    audit_entry = store.get(f"{thread_id}:dataset:df_net_uvp_matches")
    audit_meta = dict(audit_entry["meta"])
    audit_meta["net_dataframe_fingerprint"] = source_module._net_dataframe_fingerprint(net)
    store.set(f"{thread_id}:dataset:df_net_uvp_matches", audit_entry["df"], audit_meta)
    enriched_entry = store.get(f"{thread_id}:dataset:df_ecotaxa_ecopart_campaign")
    enriched = pd.DataFrame(
        {
            "export_project_id": [10] * 600,
            "sample_profileid": ["uvp-101"] * 300 + ["unrelated"] * 300,
            "object_id": [f"object-{index}" for index in range(600)],
            "depth_bin": [5.0] * 600,
            "object_annotation_hierarchy": ["living>Crustacea>Copepoda"] * 600,
            "ecopart_Sampled volume [L]": [100.0] * 600,
        }
    )
    store.set(
        f"{thread_id}:dataset:df_ecotaxa_ecopart_campaign",
        enriched,
        enriched_entry["meta"],
    )

    join_tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign",
        }
    )

    assert store.get(f"{thread_id}:dataset:df_net_uvp_ecopart") is not None


def test_join_net_uvp_enriched_also_prepares_calculable_and_excluded_strata(
    tmp_path, monkeypatch
):
    join_tool, store, thread_id = _net_uvp_enriched_tool(tmp_path, monkeypatch)
    audit_entry = store.get(f"{thread_id}:dataset:df_net_uvp_matches")
    audit = audit_entry["df"].copy()
    audit["join_eligible"] = True
    audit["ctd_filename_join_eligible"] = True
    store.set(
        f"{thread_id}:dataset:df_net_uvp_matches",
        audit,
        audit_entry["meta"],
    )

    text = join_tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign",
        }
    )

    strata = store.get(f"{thread_id}:dataset:df_net_uvp_strata")["df"]
    calculable = store.get(f"{thread_id}:dataset:df_net_uvp_calculable")["df"]
    exclusions = store.get(f"{thread_id}:dataset:df_net_uvp_exclusions")["df"]
    assert len(strata) == 2
    assert len(calculable) == 1
    assert len(exclusions) == 1
    assert exclusions.iloc[0]["depth_match_status"] == "missing_volume"
    assert "1/2" in text
    assert "df_net_uvp_calculable" in text


def test_join_net_uvp_enriched_requires_opt_in_for_unavailable_ctd_audit(
    tmp_path, monkeypatch
):
    join_tool, store, thread_id = _net_uvp_enriched_tool(
        tmp_path,
        monkeypatch,
        exploratory_audit=True,
    )

    blocked_result = join_tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign",
        }
    )

    assert "refusée" in blocked_result
    assert store.get(f"{thread_id}:dataset:df_net_uvp_ecopart") is None

    join_tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign",
            "allow_unverified_ctd": True,
        }
    )

    stored = store.get(f"{thread_id}:dataset:df_net_uvp_ecopart")
    assert stored["df"]["ctd_verification"].eq("unavailable").all()
    assert stored["df"]["exploratory"].all()
    assert stored["meta"]["ctd_verification"] == "unavailable"
    assert stored["meta"]["exploratory"] is True


@pytest.mark.parametrize(
    ("join_eligible", "ctd_verification"),
    [
        (False, "verified"),
        (True, "no_match"),
        (True, "unavailable"),
    ],
)
def test_certified_join_wrapper_rejects_ctd_without_match_or_opt_in(
    tmp_path,
    monkeypatch,
    join_eligible,
    ctd_verification,
):
    from tools.dataset_registry import store_dataset

    join_tool, store, thread_id = _net_uvp_enriched_tool(tmp_path, monkeypatch)
    audit_entry = store.get(f"{thread_id}:dataset:df_net_uvp_matches")
    audit = audit_entry["df"].copy()
    audit["join_eligible"] = join_eligible
    audit["ctd_verification"] = ctd_verification
    audit["exploratory"] = False
    store_dataset(
        store,
        thread_id,
        audit,
        variable_name="df_net_uvp_matches",
        meta={
            **audit_entry["meta"],
            "ctd_verification": ctd_verification,
            "exploratory": False,
            "allow_unverified_ctd": False,
        },
        set_active=False,
    )

    result = join_tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign",
        }
    )

    assert "aucune table finale n'a été créée" in result.lower()
    assert store.get(f"{thread_id}:dataset:df_net_uvp_ecopart") is None


def test_join_net_uvp_enriched_rejects_same_name_net_replacement(
    tmp_path, monkeypatch
):
    from tools.dataset_registry import store_dataset

    join_tool, store, thread_id = _net_uvp_enriched_tool(tmp_path, monkeypatch)
    store_dataset(
        store,
        thread_id,
        pd.DataFrame(
            {
                "SAMPLE_ID": [501, 999],
                "net_density_ind_m3": [12.0, 15.0],
            }
        ),
        variable_name="df_file_baffin_2024",
        meta={"source": "file"},
        is_loaded_file=True,
    )

    result = join_tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign",
        }
    )

    assert "refusée" in result
    assert store.get(f"{thread_id}:dataset:df_net_uvp_ecopart") is None


def test_net_dataframe_fingerprint_preserves_ieee_float_distinctions():
    from tools.copepod_sources import _net_dataframe_fingerprint

    first = pd.DataFrame({"density": [12.00000000001]})
    second = pd.DataFrame({"density": [12.00000000002]})

    assert _net_dataframe_fingerprint(first) == _net_dataframe_fingerprint(
        first.copy()
    )
    assert _net_dataframe_fingerprint(first) != _net_dataframe_fingerprint(second)


def test_join_net_uvp_enriched_rejects_ieee_float_replacement_after_audit(
    tmp_path, monkeypatch
):
    from tools.dataset_registry import store_dataset
    join_tool, store, thread_id = _net_uvp_enriched_tool(
        tmp_path,
        monkeypatch,
        net_density_first=12.00000000001,
    )
    store_dataset(
        store,
        thread_id,
        pd.DataFrame(
            {
                "SAMPLE_ID": [501, 502],
                "net_density_ind_m3": [12.00000000002, 15.0],
            }
        ),
        variable_name="df_file_baffin_2024",
        meta={"source": "file"},
        is_loaded_file=True,
    )

    result = join_tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign",
        }
    )

    assert "refusée" in result
    assert store.get(f"{thread_id}:dataset:df_net_uvp_ecopart") is None


@pytest.mark.parametrize(
    "audit_meta",
    [
        {
            "source": "file",
            "net_variable_name": "df_file_baffin_2024",
            "ctd_filename_verified": 1,
        },
        {
            "source": "net_uvp_match",
            "net_variable_name": "df_file_other_campaign",
            "ctd_filename_verified": 1,
        },
    ],
    ids=["wrong-source", "wrong-net-variable"],
)
def test_join_net_uvp_enriched_rejects_untrusted_audit_provenance(
    tmp_path, monkeypatch, audit_meta
):
    join_tool, store, thread_id = _net_uvp_enriched_tool(
        tmp_path,
        monkeypatch,
        audit_meta=audit_meta,
    )

    result = join_tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign",
        }
    )

    assert "refusée" in result
    assert store.get(f"{thread_id}:dataset:df_net_uvp_ecopart") is None


def test_join_net_uvp_enriched_rejects_raw_file_masquerading_as_enriched(
    tmp_path, monkeypatch
):
    join_tool, store, thread_id = _net_uvp_enriched_tool(
        tmp_path,
        monkeypatch,
        enriched_meta={"source": "file"},
    )

    result = join_tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign",
        }
    )

    assert "refusée" in result
    assert store.get(f"{thread_id}:dataset:df_net_uvp_ecopart") is None


def test_join_net_uvp_enriched_rejects_enrichment_without_object_identifier(
    tmp_path, monkeypatch
):
    join_tool, store, thread_id = _net_uvp_enriched_tool(
        tmp_path,
        monkeypatch,
        enriched_has_object_id=False,
    )

    result = join_tool.invoke(
        {
            "net_variable_name": "df_file_baffin_2024",
            "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign",
        }
    )

    assert "refusée" in result
    assert store.get(f"{thread_id}:dataset:df_net_uvp_ecopart") is None


def test_ecotaxa_cache_map_is_complete_and_does_not_migrate_file(
    tmp_path, monkeypatch
):
    import sqlite3

    import tools.copepod_sources as source_module

    cache_db = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(cache_db)
    conn.executescript(
        """
        CREATE TABLE local_extension (
            extension_id INTEGER PRIMARY KEY,
            sample_id INTEGER,
            score REAL
        );
        CREATE INDEX idx_extension_sample ON local_extension(sample_id);
        INSERT INTO local_extension VALUES (1, 42000001, 0.75);
        """
    )
    conn.close()
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))

    tool = next(
        item for item in source_module.make_source_tools("cache-map-thread")
        if item.name == "list_ecotaxa_cache_tables"
    )
    result = tool.invoke({})

    assert "Carte du cache EcoTaxa" in result
    assert "local_extension" in result
    assert "extension_id" in result
    assert "Grain non documenté" in result
    assert "idx_extension_sample" in result

    conn = sqlite3.connect(cache_db)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    conn.close()
    assert tables == {"local_extension"}


def test_ecotaxa_cache_query_accepts_readonly_cte(tmp_path, monkeypatch):
    import sqlite3

    import tools.copepod_sources as source_module
    from tools.session_store import SessionStore

    cache_db = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(cache_db)
    conn.executescript(
        """
        CREATE TABLE samples_cache (
            sample_id INTEGER PRIMARY KEY,
            project_id INTEGER,
            last_synced TEXT
        );
        INSERT INTO samples_cache VALUES (1, 42, 'test'), (2, 42, 'test');
        """
    )
    conn.close()
    store = SessionStore(tmp_path / "sessions")
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))
    monkeypatch.setattr(source_module, "_store", store)

    tool = next(
        item for item in source_module.make_source_tools("cache-cte-thread")
        if item.name == "query_ecotaxa_cache"
    )
    result = tool.invoke(
        {
            "sql": (
                "WITH counts AS (SELECT project_id, COUNT(*) AS n "
                "FROM samples_cache GROUP BY project_id) "
                "SELECT * FROM counts"
            )
        }
    )

    assert "lignes retournées" in result
    assert store.get("cache-cte-thread")["df"].to_dict("records") == [
        {"project_id": 42, "n": 2}
    ]


def test_ecotaxa_cache_contract_exposes_sample_metadata_envelopes_and_coverage():
    from core.ecotaxa_browser.cache.sql_explorer import CACHE_TABLES
    from tools.copepod_sources import make_source_tools

    description = next(
        tool.description
        for tool in make_source_tools("sql-metadata-contract-thread")
        if tool.name == "query_ecotaxa_cache"
    )

    for column in (
        "datetime_min",
        "datetime_max",
        "time_min",
        "time_max",
        "temporal_precision",
        "missing_date_count",
        "missing_time_count",
        "missing_depth_min_count",
        "missing_depth_max_count",
        "depth_complete",
        "metadata_objects_scanned",
        "metadata_complete",
        "metadata_coverage_pct",
    ):
        assert column in description
    assert "(time_max >= '22:00:00' OR time_min <= '02:00:00')" in description
    assert "unknown, not non-matches" in description
    assert "positions au niveau sample, enveloppes date/heure et enveloppes de profondeur" in (
        CACHE_TABLES["samples_cache"]
    )


def test_query_ecotaxa_cache_keeps_complete_agent_result(tmp_path, monkeypatch):
    import sqlite3

    import tools.copepod_sources as source_module
    from core.ecotaxa_browser.cache.repo import init_schema
    from tools.session_store import SessionStore

    cache_db = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(cache_db)
    init_schema(conn)
    conn.executemany(
        "INSERT INTO samples_cache "
        "(sample_id, project_id, station_id, last_synced) VALUES (?, 10, 'ST-1', 'test')",
        ((sample_id,) for sample_id in range(1, 1002)),
    )
    conn.commit()
    conn.close()

    store = SessionStore(tmp_path / "sessions")
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))
    monkeypatch.setattr(source_module, "_store", store)
    tool = next(
        item for item in source_module.make_source_tools("sql-full-thread")
        if item.name == "query_ecotaxa_cache"
    )

    result = tool.invoke({"sql": "SELECT sample_id FROM samples_cache ORDER BY sample_id"})

    session = store.get("sql-full-thread")
    assert session["df"].shape == (1001, 1)
    assert "aperçu de 10 lignes sur 1001" in result


def test_query_ecotaxa_cache_memorizes_exportable_selection(tmp_path, monkeypatch):
    """A cache campaign returning sample_id registers an exportable 'latest'
    selection so export_ecotaxa_samples(selection_name='latest') exports exactly
    what the exploration selected — including across several projects."""
    import sqlite3
    from core.ecotaxa_browser.cache.repo import init_schema, upsert_sample

    cache_db = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(cache_db)
    init_schema(conn)
    upsert_sample(conn, sample_id=101, project_id=42, lat_avg=55.0, lon_avg=-55.0,
                  date_min="2014-06-01", date_max="2014-06-02", object_count=10,
                  instrument="UVP6", last_synced="ts", iho_zone="Mer du Labrador")
    upsert_sample(conn, sample_id=102, project_id=99, lat_avg=56.0, lon_avg=-56.0,
                  date_min="2014-07-01", date_max="2014-07-02", object_count=5,
                  instrument="UVP6", last_synced="ts", iho_zone="Mer du Labrador")
    conn.commit(); conn.close()
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))

    from tools.copepod_sources import make_source_tools
    thread_id = "thread-campaign"
    tools = make_source_tools(thread_id)
    cache_tool = next(t for t in tools if t.name == "query_ecotaxa_cache")

    # Campaign: all Labrador samples, only sample_id selected (project resolved
    # from the cache) — the common exploration shape.
    out = cache_tool.invoke(
        {"sql": "SELECT sample_id FROM samples_cache WHERE iho_zone LIKE '%Labrador%'"}
    )

    latest = _store.get(f"{thread_id}:ecotaxa_selection_latest")
    assert latest is not None
    assert set(latest["meta"]["sample_ids"]) == {101, 102}
    assert set(latest["meta"]["project_ids"]) == {42, 99}
    # Creating export metadata must not replace the exact result of the
    # campaign: it remains the active DataFrame for a subsequent analysis.
    active = _store.get(thread_id)
    assert active is not None
    assert active["meta"]["variable_name"].startswith(
        "df_ecotaxa_selection_samples_"
    )
    assert latest["meta"]["variable_name"] == active["meta"]["variable_name"]
    assert active["df"].to_dict("records") == [
        {"sample_id": 101},
        {"sample_id": 102},
    ]
    assert "sélection complète de 2 samples" in out.lower()

    # The export tool picks the selection up and plans both projects.
    export_tool = next(t for t in tools if t.name == "export_ecotaxa_samples")
    plan = export_tool.invoke({"selection_name": "latest"})
    assert "101" in plan and "102" in plan
    assert "42" in plan and "99" in plan


def test_query_ecotaxa_cache_aggregate_does_not_memorize_selection(tmp_path, monkeypatch):
    """An aggregate campaign with no per-sample sample_id must not register a
    selection (nothing exportable)."""
    import sqlite3
    from core.ecotaxa_browser.cache.repo import init_schema, upsert_sample

    cache_db = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(cache_db)
    init_schema(conn)
    upsert_sample(conn, sample_id=201, project_id=42, lat_avg=55.0, lon_avg=-55.0,
                  date_min="2014-06-01", date_max="2014-06-02", object_count=10,
                  instrument="UVP6", last_synced="ts", iho_zone="Mer du Labrador")
    conn.commit(); conn.close()
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))

    from tools.copepod_sources import make_source_tools
    thread_id = "thread-aggregate"
    cache_tool = next(
        t for t in make_source_tools(thread_id) if t.name == "query_ecotaxa_cache"
    )
    cache_tool.invoke(
        {"sql": "SELECT project_id, COUNT(*) AS n FROM samples_cache GROUP BY project_id"}
    )
    assert _store.get(f"{thread_id}:ecotaxa_selection_latest") is None
