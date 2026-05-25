"""
Session mode routes — GET/POST /session/mode.

Used by the frontend to read and switch the session mode (plan → analyse).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.auth import get_auth_token, get_current_user
from core.session_store import session_store
from utils.session_utils import make_session_key, resolve_agent_type
from agents.registry import registered_types

router = APIRouter(prefix="/session", tags=["session"])

VALID_MODES = {"plan", "analyse"}


class SessionModeRequest(BaseModel):
    mode: str


@router.get("/mode")
async def get_mode(
    request: Request,
    token: str = Depends(get_auth_token),
):
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
    session_store.set_session_mode(session_key, body.mode)
    return {"mode": body.mode, "session_key": session_key}
