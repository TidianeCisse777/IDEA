import logging
import secrets
from time import time
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import Session

from backend import crud
from backend.auth import remove_auth_sessions_for_user
from backend.state import (
    redis_client,
    GUEST_USER_EXPIRY_ZSET,
    GUEST_EMAIL_DOMAIN,
    STATIC_DIR,
    interpreter_instances,
    LAST_ACTIVE_PREFIX,
)
from core.db import engine
from backend.models import UserCreate

logger = logging.getLogger(__name__)


def generate_guest_email(session: Session) -> str:
    """Create a unique temporary guest email address."""
    for _ in range(20):
        email = f"guest-{secrets.token_hex(3)}@{GUEST_EMAIL_DOMAIN}"
        if crud.get_user_by_email(session=session, email=email) is None:
            return email
    raise HTTPException(status_code=500, detail="Failed to generate a guest account")


def revoke_user_runtime_state(user_id: UUID) -> None:
    """Remove auth sessions and in-memory runtime state for a user."""
    from backend.interpreter_manager import clear_session

    user_prefix = f"{user_id}:"
    matching_session_keys = [
        session_key for session_key in list(interpreter_instances.keys())
        if session_key.startswith(user_prefix)
    ]
    for session_key in matching_session_keys:
        try:
            clear_session(session_key)
        except Exception as error:
            logger.error(f"Failed to clear expired guest session {session_key}: {error}")

    for redis_pattern in (f"{LAST_ACTIVE_PREFIX}{user_id}:*", f"messages:{user_id}:*"):
        for redis_key in redis_client.scan_iter(match=redis_pattern):
            redis_client.delete(redis_key)

    import shutil
    user_static_dir = STATIC_DIR / str(user_id)
    if user_static_dir.exists():
        shutil.rmtree(user_static_dir, ignore_errors=True)

    remove_auth_sessions_for_user(user_id)


def expire_guest_user(user_id_value: str) -> None:
    """Deactivate a guest user and revoke any live sessions."""
    try:
        user_id = UUID(user_id_value)
    except ValueError:
        logger.warning(f"Skipping invalid guest user id in expiry queue: {user_id_value}")
        redis_client.zrem(GUEST_USER_EXPIRY_ZSET, user_id_value)
        return

    with Session(engine) as db_session:
        db_user = crud.get_user_by_id(session=db_session, user_id=user_id)
        if db_user and db_user.is_active:
            db_user.is_active = False
            db_session.add(db_user)
            db_session.commit()

    revoke_user_runtime_state(user_id)
    redis_client.zrem(GUEST_USER_EXPIRY_ZSET, user_id_value)
    logger.info(f"Expired guest user {user_id_value}")


async def cleanup_expired_guest_users() -> None:
    """Deactivate guest users whose temporary access window has ended."""
    expired_user_ids = redis_client.zrangebyscore(
        GUEST_USER_EXPIRY_ZSET,
        0,
        time(),
    )
    for raw_user_id in expired_user_ids:
        user_id_value = raw_user_id.decode("utf-8") if isinstance(raw_user_id, bytes) else str(raw_user_id)
        try:
            expire_guest_user(user_id_value)
        except Exception as error:
            logger.error(f"Failed to expire guest user {user_id_value}: {error}")
