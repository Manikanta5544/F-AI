from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Tuple

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

# Password hashing (bcrypt via passlib)
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,  # production-safe cost factor
)

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    if not plain or len(plain) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long",
        )
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# JWT utilities
def _build_payload(user_id: str, token_type: str, expire_delta: timedelta) -> dict:
    now = datetime.now(timezone.utc)
    expire = now + expire_delta

    return {
        "sub": user_id,
        "type": token_type,
        "iat": now,
        "exp": expire,
    }


def create_access_token(user_id: str) -> Tuple[str, int]:
    expire_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES

    payload = _build_payload(
        user_id=user_id,
        token_type="access",
        expire_delta=timedelta(minutes=expire_minutes),
    )

    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, expire_minutes * 60


def create_refresh_token(user_id: str) -> str:
    payload = _build_payload(
        user_id=user_id,
        token_type="refresh",
        expire_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> str:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )

        user_id: str | None = payload.get("sub")
        token_type: str | None = payload.get("type")

        if not user_id or token_type != expected_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

        return user_id

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired or invalid",
        )


# Auth dependencies
async def get_current_user(
    request: Request, 
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    from app.models.db.models import User  # local import (avoid circular)

    token = None

    if credentials is not None and credentials.credentials:
        token = credentials.credentials

    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user_id = decode_token(token)

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user

# # Optional version for endpoints that allow anonymous access but can use auth if provided
# async def get_current_user_optional(
#     request: Request,
#     credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
#     db: AsyncSession = Depends(get_db),
# ):
#     from app.models.db.models import User

#     token = None

#     # 1. Header
#     if credentials and credentials.credentials:
#         token = credentials.credentials

#     # 2. Query param fallback
#     if not token:
#         token = request.query_params.get("token")

#     if not token:
#         raise HTTPException(401, "Not authenticated")

#     user_id = decode_token(token)

#     result = await db.execute(
#         select(User).where(User.id == user_id, User.is_active.is_(True))
#     )
#     user = result.scalar_one_or_none()

#     if not user:
#         raise HTTPException(401, "User not found")

#     return user


async def get_current_admin(current_user=Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return current_user