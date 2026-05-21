"""
User-management routes (superuser only).

Covers: list_users, create_user_admin, update_user_admin, delete_user_admin.
"""
import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

import crud
from auth import get_auth_token, get_db, get_current_user
from models import GenericMessage, UserCreate, UserPublic, UserUpdate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _ensure_superuser(token: str):
    from models import User  # local import to avoid circular issues
    user = get_current_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/users", response_model=List[UserPublic])
async def list_users(
    token: str = Depends(get_auth_token), db: Session = Depends(get_db)
):
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
            raise HTTPException(
                status_code=400, detail="A user with this email already exists"
            )
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
            raise HTTPException(
                status_code=400, detail="A user with this email already exists"
            )
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
            raise HTTPException(
                status_code=400, detail="Superusers cannot delete their own account"
            )
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
