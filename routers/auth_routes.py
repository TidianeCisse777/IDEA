"""
Authentication and account-management routes.

Covers: login, logout, verify_auth, get_current_user_profile,
        shared_conversation_page, change_password.
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session

from core import crud
from core.auth import (
    generate_auth_token,
    verify_password,
    get_auth_token,
    add_auth_session,
    remove_auth_session,
    SESSION_TIMEOUT,
    get_db,
    get_current_user,
)
from core.security import verify_password as verify_password_hash
from models import LoginRequest, LoginResponse, UpdatePassword, UserUpdate
from models.db import UserCreate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(login_request: LoginRequest, session: Session = Depends(get_db)):
    """Login endpoint to authenticate users"""
    user = verify_password(login_request.username, login_request.password, session)
    if user:
        token = generate_auth_token()
        expiry_time = datetime.now() + timedelta(seconds=SESSION_TIMEOUT)
        add_auth_session(token, user.id, expiry_time)

        return LoginResponse(
            success=True,
            token=token,
            message="Login successful",
        )
    else:
        raise HTTPException(status_code=401, detail="Invalid email or password")


@router.post("/register", status_code=201)
async def register(user_in: UserCreate, session: Session = Depends(get_db)):
    """Public registration — no email confirmation required."""
    existing = crud.get_user_by_email(session=session, email=user_in.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    crud.create_user(session=session, user_create=user_in)
    return {"success": True, "message": "Account created. You can now sign in."}


@router.post("/logout")
async def logout(token: str = Depends(get_auth_token)):
    """Logout endpoint to invalidate authentication token"""
    remove_auth_session(token)
    return {"message": "Logged out successfully"}


@router.get("/auth/verify")
async def verify_auth(token: str = Depends(get_auth_token)):
    """Verify if current authentication token is valid"""
    return {"authenticated": True, "message": "Token is valid"}


@router.get("/users/me")
async def get_current_user_profile(
    token: str = Depends(get_auth_token), db: Session = Depends(get_db)
):
    """Get current authenticated user's profile information"""
    try:
        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        db_user = crud.get_user_by_id(session=db, user_id=user.id)
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        return {
            "id": str(db_user.id),
            "email": db_user.email,
            "full_name": db_user.full_name,
            "is_active": db_user.is_active,
            "is_superuser": db_user.is_superuser,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user profile: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user profile")


@router.get("/share/{share_token}")
async def shared_conversation_page(share_token: str):
    """Serve the shared conversation page"""
    frontend_dir = Path(__file__).parent.parent / "frontend"
    share_html_path = frontend_dir / "share.html"

    if not share_html_path.exists():
        raise HTTPException(status_code=404, detail="Share page not found")

    return FileResponse(share_html_path, media_type="text/html")


@router.post("/users/change-password")
async def change_password(
    payload: UpdatePassword,
    token: str = Depends(get_auth_token),
    db: Session = Depends(get_db),
):
    """Change password for the current authenticated user"""
    try:
        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        db_user = crud.get_user_by_id(session=db, user_id=user.id)
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        if not verify_password_hash(payload.current_password, db_user.hashed_password):
            raise HTTPException(
                status_code=400, detail="Current password is incorrect"
            )

        crud.update_user(
            session=db, db_user=db_user, user_in=UserUpdate(password=payload.new_password)
        )
        return {"message": "Password updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error changing password: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to change password")
