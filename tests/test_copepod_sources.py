"""Tests TDD — tools/copepod_sources.py"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tools.session_store import default_store as _store


@pytest.fixture(autouse=True)
def clear_sessions():
    _store._store.clear()
    yield
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

def test_query_ecotaxa_returns_download_link():
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
        with pytest.raises(RuntimeError, match="failed with state=E"):
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
        tools = make_source_tools("thread-err")
        query = next(t for t in tools if t.name == "query_ecotaxa")
        result = query.invoke({"project_id": 1165})

    assert "Erreur" in result
    assert not _store.has("thread-err")


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
        {"project_id": 2331, "name": "LOKI ArcticNet"},
        {"project_id": 1165, "name": "UVP5 Amundsen 2018"},
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


def test_ecotaxa_skill_uses_live_project_listing():
    skill = Path("agents/skills/ecotaxa_query.md").read_text(encoding="utf-8")

    assert "list_ecotaxa_projects" in skill
    assert "UVP5 Amundsen 2018" not in skill
    assert "LOKI ArcticNet" not in skill
    assert "Green Edge 2015 IceCamp" not in skill


def test_ecotaxa_skill_routes_preview_without_export():
    skill = Path("agents/skills/ecotaxa_query.md").read_text(encoding="utf-8")

    assert "preview_ecotaxa_project" in skill
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
