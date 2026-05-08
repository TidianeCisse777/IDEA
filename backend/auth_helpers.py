from uuid import UUID

from fastapi import HTTPException

from backend.auth import get_current_user
from backend.state import redis_client, GUEST_USER_EXPIRY_ZSET
from backend.models import User


def _ensure_superuser(token: str) -> User:
    user = get_current_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


def _get_current_user_or_401(token: str) -> User:
    user = get_current_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def _is_guest_user(user_id: UUID) -> bool:
    return redis_client.zscore(GUEST_USER_EXPIRY_ZSET, str(user_id)) is not None


def _ensure_non_guest_user(user: User, action: str) -> None:
    if _is_guest_user(user.id):
        raise HTTPException(status_code=403, detail=f"Guest users cannot {action}")


def _get_user_first_name(user: User | None) -> str:
    if user is None:
        return "User"
    if _is_guest_user(user.id):
        return "Guest"

    full_name = (user.full_name or "").strip()
    if not full_name:
        return "User"

    return full_name.split()[0]
