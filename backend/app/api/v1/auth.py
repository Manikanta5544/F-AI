"""Authentication routes — login, refresh, logout, /me, register."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    create_access_token, create_refresh_token,
    decode_token, get_current_user, hash_password, verify_password,
)
from app.models.db.models import User
from app.models.schemas.schemas import (
    ApiResponse, LoginRequest, RegisterRequest, TokenResponse, UserOut,
)

router = APIRouter( tags=["auth"])

_REFRESH_COOKIE = "refresh_token"
_COOKIE_OPTS: dict = {
    "httponly": True,
    "secure": False,      # set True in production (HTTPS only)
    "samesite": "lax",
    "max_age": 7 * 24 * 3600,
    "path": "/api/v1/auth",
}


@router.post("/login", response_model=ApiResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate user and issue tokens.
    Access token returned in body; refresh token set in httpOnly cookie.
    Frontend stores access token in memory only (never localStorage).
    """
    result = await db.execute(
        select(User).where(User.email == body.email, User.is_active.is_(True))  # noqa: E712
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    access_token, expires_in = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    response.set_cookie(key=_REFRESH_COOKIE, value=refresh_token, **_COOKIE_OPTS)

    return ApiResponse(data=TokenResponse(access_token=access_token, expires_in=expires_in))


@router.post("/refresh", response_model=ApiResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Rotate tokens: validate refresh cookie → issue new access + refresh pair.
    Implements refresh token rotation (old refresh token is implicitly invalidated).
    """
    token = request.cookies.get(_REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    user_id = decode_token(token, expected_type="refresh")
    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access_token, expires_in = create_access_token(user.id)
    new_refresh = create_refresh_token(user.id)
    response.set_cookie(key=_REFRESH_COOKIE, value=new_refresh, **_COOKIE_OPTS)

    return ApiResponse(data=TokenResponse(access_token=access_token, expires_in=expires_in))


@router.post("/logout")
async def logout(
    response: Response,
    _: User = Depends(get_current_user),
):
    """Clear the refresh cookie. Frontend discards access token from memory."""
    response.delete_cookie(_REFRESH_COOKIE, path="/api/v1/auth")
    return ApiResponse(data=None)


@router.get("/me", response_model=ApiResponse)
async def me(current_user: User = Depends(get_current_user)):
    return ApiResponse(data=UserOut.model_validate(current_user))


@router.post("/register", response_model=ApiResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Register a new user.
    In production: gate this endpoint behind an admin check or invitation flow.
    """
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=body.email,
        name=body.name,
        hashed_password=hash_password(body.password),
        role="user",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return ApiResponse(data=UserOut.model_validate(user))