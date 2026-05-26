"""
Session mode routes — GET/POST /session/mode.

Used by the frontend to read and switch the session mode (plan → analyse).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.auth import get_auth_token, get_current_user
from core.copepod_observability import trace_copepod_event
from core.session_store import session_store
from utils.session_utils import make_session_key, resolve_agent_type
from agents.registry import registered_types

router = APIRouter(prefix="/session", tags=["session"])

VALID_MODES = {"plan", "analyse"}
ARTIFACT_ROUTE_TYPES = {
    "data-understanding": "data_understanding",
    "graph-context": "graph_context",
}


class SessionModeRequest(BaseModel):
    mode: str


def _authenticated_session_context(request: Request, token: str) -> tuple[str, str, str]:
    session_id = request.headers.get("x-session-id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Session ID required")

    user = get_current_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    agent_type = request.headers.get("x-agent-type", "generic")
    if agent_type not in registered_types():
        agent_type = "generic"

    session_key = make_session_key(user.id, session_id, agent_type)
    return agent_type, session_key, session_id


@router.get("/mode")
async def get_mode(
    request: Request,
    token: str = Depends(get_auth_token),
):
    _, session_key, _ = _authenticated_session_context(request, token)
    mode = session_store.get_session_mode(session_key)
    return {"mode": mode, "session_key": session_key}


@router.post("/mode")
async def set_mode(
    body: SessionModeRequest,
    request: Request,
    token: str = Depends(get_auth_token),
):
    if body.mode not in VALID_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{body.mode}'. Valid modes: {sorted(VALID_MODES)}",
        )

    agent_type, session_key, _ = _authenticated_session_context(request, token)
    current_mode = session_store.get_session_mode(session_key)
    if agent_type == "copepod" and current_mode == "analyse" and body.mode == "plan":
        raise HTTPException(
            status_code=409,
            detail="Copepod analyse mode is irreversible for this session",
        )
    if (
        agent_type == "copepod"
        and body.mode == "analyse"
        and not session_store.has_active_copepod_plan_artifacts(session_key)
    ):
        trace_copepod_event(
            "analyse_mode_blocked",
            session_key=session_key,
            output={
                "requested_mode": body.mode,
                "blocking_reason": (
                    "active Data Understanding and active Graph Context artifacts are required, "
                    "and the Graph Context must reference the active Data Understanding"
                ),
            },
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "Copepod analyse mode requires active Data Understanding and "
                "active Graph Context artifacts, with the Graph Context linked "
                "to the active Data Understanding"
            ),
        )

    session_store.set_session_mode(session_key, body.mode)
    if agent_type == "copepod" and body.mode == "analyse":
        trace_copepod_event(
            "analyse_mode_entered",
            session_key=session_key,
            output={"mode": body.mode},
        )
    return {"mode": body.mode, "session_key": session_key}


@router.get("/artifacts/{artifact_slug}")
async def get_artifact_versions(
    artifact_slug: str,
    request: Request,
    token: str = Depends(get_auth_token),
):
    artifact_type = ARTIFACT_ROUTE_TYPES.get(artifact_slug)
    if artifact_type is None:
        raise HTTPException(status_code=404, detail="Artifact type not found")

    agent_type, session_key, _ = _authenticated_session_context(request, token)
    if agent_type != "copepod":
        raise HTTPException(status_code=404, detail="Artifact route not found")

    return {
        "versions": session_store.get_artifact_versions(session_key, artifact_type),
        "active": session_store.get_active_artifact(session_key, artifact_type),
    }
