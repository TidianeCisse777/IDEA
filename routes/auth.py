import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from backend import crud
from backend.auth import (
    generate_auth_token,
    verify_password,
    get_auth_token,
    add_auth_session,
    remove_auth_session,
    SESSION_TIMEOUT,
    GUEST_SESSION_TIMEOUT,
    GUEST_SESSION_TIMEOUT_MINUTES,
    get_db,
)
from backend.guest_manager import generate_guest_email
from backend.state import redis_client, GUEST_USER_EXPIRY_ZSET
from backend.models import LoginRequest, LoginResponse, UserCreate

router = APIRouter(tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(login_request: LoginRequest, session: Session = Depends(get_db)):
    """Login endpoint to authenticate users"""
    user = verify_password(login_request.username, login_request.password, session)
    if user:
        token = generate_auth_token()
        expiry_time = datetime.now() + timedelta(seconds=SESSION_TIMEOUT)
        add_auth_session(token, user.id, expiry_time)
        return LoginResponse(success=True, token=token, message="Login successful")
    else:
        raise HTTPException(status_code=401, detail="Invalid email or password")


@router.post("/guest-login", response_model=LoginResponse)
async def guest_login(session: Session = Depends(get_db)):
    """Create a temporary guest account and return an authenticated session."""
    guest_email = generate_guest_email(session)
    guest_user = crud.create_user(
        session=session,
        user_create=UserCreate(
            email=guest_email,
            password=secrets.token_urlsafe(24),
            full_name="Guest User",
            is_superuser=False,
            is_active=True,
        ),
    )

    token = generate_auth_token()
    expiry_time = datetime.now() + timedelta(seconds=GUEST_SESSION_TIMEOUT)
    add_auth_session(token, guest_user.id, expiry_time)
    redis_client.zadd(GUEST_USER_EXPIRY_ZSET, {str(guest_user.id): expiry_time.timestamp()})

    return LoginResponse(
        success=True,
        token=token,
        message="Guest login successful",
        is_guest=True,
        guest_expires_in_minutes=GUEST_SESSION_TIMEOUT_MINUTES,
        guest_expires_at=expiry_time.isoformat(),
        show_guest_notice=True,
    )


@router.post("/logout")
async def logout(token: str = Depends(get_auth_token)):
    """Logout endpoint to invalidate authentication token"""
    remove_auth_session(token)
    return {"message": "Logged out successfully"}


@router.get("/auth/verify")
async def verify_auth(token: str = Depends(get_auth_token)):
    """Verify if current authentication token is valid"""
    return {"authenticated": True, "message": "Token is valid"}
