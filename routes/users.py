import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from backend import crud
from backend.auth import get_auth_token, get_db, GUEST_SESSION_TIMEOUT_MINUTES
from backend.auth_helpers import _ensure_superuser, _get_current_user_or_401, _is_guest_user
from backend.state import redis_client, GUEST_USER_EXPIRY_ZSET
from core.security import verify_password as verify_password_hash
from backend.models import (
    GenericMessage,
    UpdatePassword,
    UserCreate,
    UserPublic,
    UserUpdate,
)

router = APIRouter(tags=["users"])
logger = logging.getLogger(__name__)


@router.get("/users/me")
async def get_current_user_profile(token: str = Depends(get_auth_token), db: Session = Depends(get_db)):
    """Get current authenticated user's profile information"""
    try:
        from backend.auth import get_current_user
        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        db_user = crud.get_user_by_id(session=db, user_id=user.id)
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        guest_expiry_score = redis_client.zscore(GUEST_USER_EXPIRY_ZSET, str(db_user.id))
        from datetime import datetime
        guest_expires_at = (
            datetime.fromtimestamp(float(guest_expiry_score)).isoformat()
            if guest_expiry_score is not None
            else None
        )

        return {
            "id": str(db_user.id),
            "email": db_user.email,
            "full_name": db_user.full_name,
            "is_active": db_user.is_active,
            "is_superuser": db_user.is_superuser,
            "is_guest": guest_expiry_score is not None,
            "guest_expires_at": guest_expires_at,
            "guest_expires_in_minutes": GUEST_SESSION_TIMEOUT_MINUTES if guest_expiry_score is not None else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user profile: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user profile")


@router.post("/users/change-password")
async def change_password(
    payload: UpdatePassword,
    token: str = Depends(get_auth_token),
    db: Session = Depends(get_db),
):
    """Change password for the current authenticated user"""
    try:
        user = _get_current_user_or_401(token)
        from backend.auth_helpers import _ensure_non_guest_user
        _ensure_non_guest_user(user, "change passwords")

        db_user = crud.get_user_by_id(session=db, user_id=user.id)
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        if not verify_password_hash(payload.current_password, db_user.hashed_password):
            raise HTTPException(status_code=400, detail="Current password is incorrect")

        crud.update_user(session=db, db_user=db_user, user_in=UserUpdate(password=payload.new_password))
        return {"message": "Password updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error changing password: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to change password")


@router.get("/users", response_model=List[UserPublic])
async def list_users(token: str = Depends(get_auth_token), db: Session = Depends(get_db)):
    """List all users (superuser only)"""
    try:
        _ensure_superuser(token)
        users = crud.list_users(session=db)
        return [UserPublic.model_validate(user, from_attributes=True) for user in users]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing users: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list users")


@router.post("/users", response_model=UserPublic, status_code=201)
async def create_user_admin(
    user_in: UserCreate,
    token: str = Depends(get_auth_token),
    db: Session = Depends(get_db),
):
    """Create a new user (superuser only)"""
    try:
        _ensure_superuser(token)
        try:
            db_user = crud.create_user(session=db, user_create=user_in)
        except IntegrityError:
            raise HTTPException(status_code=400, detail="A user with this email already exists")
        return UserPublic.model_validate(db_user, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create user")


@router.put("/users/{user_id}", response_model=UserPublic)
async def update_user_admin(
    user_id: UUID,
    user_in: UserUpdate,
    token: str = Depends(get_auth_token),
    db: Session = Depends(get_db),
):
    """Update an existing user (superuser only)"""
    try:
        _ensure_superuser(token)
        db_user = crud.get_user_by_id(session=db, user_id=user_id)
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        try:
            updated_user = crud.update_user(session=db, db_user=db_user, user_in=user_in)
        except IntegrityError:
            raise HTTPException(status_code=400, detail="A user with this email already exists")
        return UserPublic.model_validate(updated_user, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update user")


@router.delete("/users/{user_id}", response_model=GenericMessage)
async def delete_user_admin(
    user_id: UUID,
    token: str = Depends(get_auth_token),
    db: Session = Depends(get_db),
):
    """Delete a user (superuser only)"""
    try:
        admin = _ensure_superuser(token)
        if admin.id == user_id:
            raise HTTPException(status_code=400, detail="Superusers cannot delete their own account")
        db_user = crud.get_user_by_id(session=db, user_id=user_id)
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        crud.delete_user(session=db, db_user=db_user)
        return GenericMessage(message="User deleted successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete user")
