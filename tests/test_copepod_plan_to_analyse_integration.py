from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import importlib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agents.copepod_profile  # noqa: F401
from core.auth import get_auth_token
from core.chat_stream_events import chat_stream_events
from core.session_store import InMemorySessionStore
from routers.session_routes import router

pytestmark = pytest.mark.workflow


FIXTURES = Path(
    "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv"
)
ECOTAXA = FIXTURES / "ecotaxa_sample_50.tsv"
ECOPART = FIXTURES / "uvp_amundsen_105_ecopart_particles_reduced.tsv"


@pytest.fixture(autouse=True)
def ensure_copepod_registered():
    importlib.reload(agents.copepod_profile)


@pytest.fixture()
def app_client():
    store = InMemorySessionStore()
    app = FastAPI()
    app.include_router(router)

    fake_user = MagicMock()
    fake_user.id = "u1"
    app.dependency_overrides[get_auth_token] = lambda: "test-token"

    with (
        patch("routers.session_routes.get_current_user", return_value=fake_user),
        patch("routers.session_routes.session_store", store),
        patch("core.session_store.session_store", store),
    ):
        yield TestClient(app), store


@pytest.fixture()
def copepod_tools():
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_columns  # noqa: F401
    from core.tool_registry.tools import copepod_data  # noqa: F401
    from core.tool_registry.tools import copepod_session_artifacts  # noqa: F401

    code = registry.render({"copepod_data", "copepod_columns", "copepod_artifacts"})
    ns = {}
    exec(code, ns)
    return ns


def _file_artifact_entry(path: Path, inspect_report: dict) -> dict:
    return {
        "file_path": str(path),
        "original_filename": path.name,
        "size_bytes": path.stat().st_size,
        "content_hash": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
        "uploaded_at": "2026-05-26T12:00:00+00:00",
        "inspection_tool_version": "inspect_file:v1",
        "source_type_guess": inspect_report["source_type_guess"],
    }


def _build_data_understanding_artifact(tools: dict, path: Path) -> dict:
    inspected = tools["inspect_file"](str(path), sample_rows=10)
    roles = tools["infer_column_roles"](inspected["columns"], inspected["metadata"])
    summary = tools["summarize_understanding"](inspected, roles)

    return {
        "files": [
            {
                **_file_artifact_entry(path, inspected),
                "columns": inspected["columns"],
                "roles": roles["roles"],
                "taxonomic_validation_status": summary["taxonomic_validation_status"],
                "quality_limits": summary["quality_limits"],
            }
        ],
        "global": {
            "possible_joins_or_couplings": summary["possible_joins_or_couplings"],
            "missing_or_ambiguous_data": summary["missing_or_ambiguous_data"],
        },
        "overrides": [],
    }


def _post_analyse(client: TestClient, session_id: str):
    return client.post(
        "/session/mode",
        json={"mode": "analyse"},
        headers={"x-session-id": session_id, "x-agent-type": "copepod"},
    )


def test_full_plan_to_analyse_flow_without_llm(app_client, copepod_tools):
    client, store = app_client
    session_key = "u1:flow:copepod"

    data_artifact = _build_data_understanding_artifact(copepod_tools, ECOTAXA)
    du_draft = copepod_tools["create_data_understanding_draft"](
        session_key, data_artifact
    )

    assert du_draft["status"] == "draft"
    assert _post_analyse(client, "flow").status_code == 409

    du_active = copepod_tools["activate_data_understanding"](
        session_key, du_draft["version_id"]
    )
    graph_context = {
        "data_understanding_version_id": du_active["version_id"],
        "objective": "Distribution verticale EcoTaxa",
        "columns": ["object_depth_min", "object_depth_max"],
        "filters": [],
        "units": {"depth": "m"},
        "chart_type": "static vertical distribution",
        "language": "Python",
        "output_artifacts": ["png", "metadata"],
        "feasibility": "exploratory",
        "blockers": [],
    }
    gc_draft = copepod_tools["create_graph_context_draft"](
        session_key, graph_context
    )

    assert gc_draft["status"] == "draft"
    assert _post_analyse(client, "flow").status_code == 409

    gc_active = copepod_tools["activate_graph_context"](
        session_key, gc_draft["version_id"]
    )
    stream_events = list(
        chat_stream_events(
            [
                {
                    "start": True,
                    "end": True,
                    "role": "assistant",
                    "type": "message",
                    "content": "Contexte scientifique validé. [PLAN_READY]",
                }
            ],
            user_turns=3,
            session_mode="plan",
        )
    )
    assert stream_events[-1] == {
        "start": True,
        "end": True,
        "role": "computer",
        "type": "action_button",
        "action": "validate_plan",
        "label": "Passer en Mode Analyse",
    }

    analyse_response = _post_analyse(client, "flow")

    assert analyse_response.status_code == 200
    assert analyse_response.json()["mode"] == "analyse"
    assert store.get_session_mode(session_key) == "analyse"

    du_debug = client.get(
        "/session/artifacts/data-understanding",
        headers={"x-session-id": "flow", "x-agent-type": "copepod"},
    )
    gc_debug = client.get(
        "/session/artifacts/graph-context",
        headers={"x-session-id": "flow", "x-agent-type": "copepod"},
    )

    assert du_debug.status_code == 200
    assert gc_debug.status_code == 200
    assert du_debug.json()["active"]["version_id"] == du_active["version_id"]
    assert gc_debug.json()["active"]["version_id"] == gc_active["version_id"]
    assert (
        gc_debug.json()["active"]["payload"]["data_understanding_version_id"]
        == du_active["version_id"]
    )


def test_analyse_upload_creates_new_data_understanding_draft_without_replanning(
    app_client, copepod_tools
):
    client, store = app_client
    session_key = "u1:analyse-upload:copepod"

    initial_du_draft = copepod_tools["create_data_understanding_draft"](
        session_key, _build_data_understanding_artifact(copepod_tools, ECOTAXA)
    )
    initial_du_active = copepod_tools["activate_data_understanding"](
        session_key, initial_du_draft["version_id"]
    )
    gc_draft = copepod_tools["create_graph_context_draft"](
        session_key,
        {
            "data_understanding_version_id": initial_du_active["version_id"],
            "objective": "Graphique verrouillé",
            "columns": ["object_depth_min"],
            "language": "Python",
            "feasibility": "exploratory",
        },
    )
    gc_active = copepod_tools["activate_graph_context"](
        session_key, gc_draft["version_id"]
    )
    assert _post_analyse(client, "analyse-upload").status_code == 200

    new_du_draft = copepod_tools["create_data_understanding_draft"](
        session_key, _build_data_understanding_artifact(copepod_tools, ECOPART)
    )

    assert new_du_draft["status"] == "draft"
    assert store.get_session_mode(session_key) == "analyse"
    assert (
        store.get_active_artifact(session_key, "data_understanding")["version_id"]
        == initial_du_active["version_id"]
    )
    assert (
        store.get_active_artifact(session_key, "graph_context")["version_id"]
        == gc_active["version_id"]
    )

    du_versions = client.get(
        "/session/artifacts/data-understanding",
        headers={"x-session-id": "analyse-upload", "x-agent-type": "copepod"},
    ).json()["versions"]
    statuses = {version["version_id"]: version["status"] for version in du_versions}

    assert statuses[initial_du_active["version_id"]] == "active"
    assert statuses[new_du_draft["version_id"]] == "draft"
