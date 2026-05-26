import json
import os
import secrets
from datetime import datetime, timedelta
from typing import Any
from fastapi import HTTPException, Header, Depends
from sqlmodel import Session

from core.db import engine
from core.security import create_access_token
from core import crud
from models import User

# Session timeout configuration
SESSION_TIMEOUT = 24 * 60 * 60  # 24 hours in seconds

_AUTH_PREFIX = "auth_session:"


def _redis():
    from core.session_store import session_store
    return session_store._r


def get_db():
    """Database dependency"""
    with Session(engine) as session:
        yield session


def generate_auth_token() -> str:
    """Generate a secure random token for authentication"""
    return create_access_token(subject=secrets.token_urlsafe(16), expires_delta=timedelta(seconds=SESSION_TIMEOUT))


def verify_password(email: str, password: str, session: Session) -> User | None:
    """Verify user credentials and return user if valid"""
    return crud.authenticate(session=session, email=email, password=password)


def is_authenticated(token: str) -> bool:
    """Check if authentication token is valid (session stored in Redis, survives restarts)"""
    raw = _redis().get(f"{_AUTH_PREFIX}{token}")
    return raw is not None


def get_current_user(token: str) -> User | None:
    """Get current user from token"""
    raw = _redis().get(f"{_AUTH_PREFIX}{token}")
    if raw is None:
        return None
    session_data = json.loads(raw)
    with Session(engine) as db_session:
        return crud.get_user_by_id(session=db_session, user_id=session_data["user_id"])


def get_auth_token(authorization: str = Header(None)) -> str:
    """Dependency to extract and validate auth token from headers"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.replace("Bearer ", "")
    if not is_authenticated(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return token


def add_auth_session(token: str, user_id: Any, expiry_time: datetime):
    """Add a new authentication session (persisted in Redis, survives container restarts)"""
    ttl = max(1, int((expiry_time - datetime.now()).total_seconds()))
    _redis().setex(f"{_AUTH_PREFIX}{token}", ttl, json.dumps({"user_id": str(user_id)}))


def remove_auth_session(token: str):
    """Remove an authentication session"""
    _redis().delete(f"{_AUTH_PREFIX}{token}")
