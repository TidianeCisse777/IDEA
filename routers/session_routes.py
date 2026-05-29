"""
Session routes — online-mode toggle for the copepod profile.

The previous plan/analyse mode switch and artifact debug routes were removed
along with the Plan Mode workflow.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.auth import get_auth_token, get_current_user
from core.session_store import session_store
from utils.session_utils import make_session_key, resolve_agent_type
from agents.registry import registered_types

router = APIRouter(prefix="/session", tags=["session"])

ONLINE_MODE_ALLOWED_SOURCES = ["ogsl", "bio_oracle"]


class OnlineModeRequest(BaseModel):
    enabled: bool


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
async def get_mode_stub():
    return {"mode": "analyse"}


@router.get("/online-mode")
async def get_online_mode(
    request: Request,
    token: str = Depends(get_auth_token),
):
    agent_type, session_key, _ = _authenticated_session_context(request, token)
    if agent_type != "copepod":
        raise HTTPException(status_code=404, detail="Online mode route not found")
    return {
        "enabled": session_store.get_online_mode(session_key),
        "session_key": session_key,
        "allowed_sources": ONLINE_MODE_ALLOWED_SOURCES,
    }


@router.put("/online-mode")
async def set_online_mode(
    body: OnlineModeRequest,
    request: Request,
    token: str = Depends(get_auth_token),
):
    agent_type, session_key, _ = _authenticated_session_context(request, token)
    if agent_type != "copepod":
        raise HTTPException(status_code=404, detail="Online mode route not found")

    session_store.set_online_mode(session_key, body.enabled)
    return {
        "enabled": session_store.get_online_mode(session_key),
        "session_key": session_key,
        "allowed_sources": ONLINE_MODE_ALLOWED_SOURCES,
    }
