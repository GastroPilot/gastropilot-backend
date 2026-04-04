from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    verify_password,
    verify_pin,
    verify_token,
)
from app.models.restaurant import Restaurant
from app.models.user import RefreshToken, User

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    # PIN login (staff)
    operator_number: str | None = None
    pin: str | None = None
    # Tenant-Kontext für PIN-Login (verhindert Kollisionen bei gleicher Bedienernummer)
    tenant_slug: str | None = None
    # NFC login
    nfc_tag_id: str | None = None
    # Email/password login
    email: str | None = None
    password: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


def _refresh_expiry_or_500(refresh_token: str) -> datetime:
    payload = verify_token(refresh_token, token_type="refresh")
    exp = payload.get("exp") if payload else None
    if exp is None:
        raise HTTPException(status_code=500, detail="Could not issue refresh token")
    return datetime.fromtimestamp(exp, tz=UTC)


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
):
    user: User | None = None

    # PIN login
    if data.operator_number and data.pin:
        if not data.tenant_slug:
            raise HTTPException(status_code=400, detail="tenant_slug is required for PIN login")
        tenant_res = await session.execute(
            select(Restaurant).where(Restaurant.slug == data.tenant_slug)
        )
        tenant = tenant_res.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        result = await session.execute(
            select(User).where(
                User.operator_number == data.operator_number,
                User.tenant_id == tenant.id,
            )
        )
        candidate = result.scalar_one_or_none()
        if candidate and candidate.pin_hash and verify_pin(data.pin, candidate.pin_hash):
            user = candidate

    # NFC login
    elif data.nfc_tag_id:
        query = select(User).where(User.nfc_tag_id == data.nfc_tag_id)
        if data.tenant_slug:
            tenant_res = await session.execute(
                select(Restaurant).where(Restaurant.slug == data.tenant_slug)
            )
            tenant = tenant_res.scalar_one_or_none()
            if not tenant:
                raise HTTPException(status_code=401, detail="Invalid credentials")
            query = query.where(User.tenant_id == tenant.id)
        user = (await session.execute(query)).scalar_one_or_none()

    # Email/password login
    elif data.email and data.password:
        result = await session.execute(select(User).where(User.email == data.email))
        candidate = result.scalar_one_or_none()
        if (
            candidate
            and candidate.password_hash
            and verify_password(data.password, candidate.password_hash)
        ):
            user = candidate

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")

    auth_method = "pin" if data.operator_number else "password"

    token_data = {
        "sub": str(user.id),
        "role": user.role,
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "auth_method": auth_method,
    }
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(str(user.id))

    token_hash = hash_refresh_token(refresh_token)
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=_refresh_expiry_or_500(refresh_token),
    )
    session.add(rt)

    await session.execute(
        update(User).where(User.id == user.id).values(last_login_at=datetime.now(UTC))
    )
    await session.commit()

    user_data = {
        "id": str(user.id),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "operator_number": user.operator_number,
        "email": user.email,
    }

    if settings.USE_HTTPONLY_COOKIES:
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            path=settings.COOKIE_PATH,
        )
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            path=settings.COOKIE_PATH,
        )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user_data,
    )


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    refresh_token_cookie: str | None = Cookie(default=None, alias="refresh_token"),
):
    header_token = credentials.credentials if credentials else None
    token = header_token or refresh_token_cookie

    if not token:
        raise HTTPException(status_code=401, detail="Refresh token required")

    payload = verify_token(header_token, token_type="refresh") if header_token else None
    if payload:
        token = header_token
    elif refresh_token_cookie:
        payload = verify_token(refresh_token_cookie, token_type="refresh")
        if payload:
            token = refresh_token_cookie
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user_id = payload.get("user_id")
    token_hash = hash_refresh_token(token)

    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
        )
    )
    stored_token = result.scalar_one_or_none()

    if not stored_token:
        raise HTTPException(status_code=401, detail="Refresh token not found or revoked")

    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.id == stored_token.id)
        .values(revoked_at=datetime.now(UTC))
    )

    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    token_data = {
        "sub": str(user.id),
        "role": user.role,
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
    }
    new_access_token = create_access_token(token_data)
    new_refresh_token = create_refresh_token(str(user.id))

    new_hash = hash_refresh_token(new_refresh_token)
    rt = RefreshToken(
        user_id=user.id,
        token_hash=new_hash,
        expires_at=_refresh_expiry_or_500(new_refresh_token),
        rotated_from_id=stored_token.id,
    )
    session.add(rt)
    await session.commit()

    if settings.USE_HTTPONLY_COOKIES:
        response.set_cookie(
            key="access_token",
            value=new_access_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
        )
        response.set_cookie(
            key="refresh_token",
            value=new_refresh_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
        )

    return {"access_token": new_access_token, "refresh_token": new_refresh_token}


@router.post("/logout")
async def logout(
    response: Response,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    access_token_cookie: str | None = Cookie(default=None, alias="access_token"),
    session: AsyncSession = Depends(get_db),
):
    header_token = credentials.credentials if credentials else None
    token = header_token or access_token_cookie

    payload = verify_token(header_token) if header_token else None
    if payload:
        token = header_token
    elif access_token_cookie:
        payload = verify_token(access_token_cookie)
        if payload:
            token = access_token_cookie

    if token and payload:
        user_id = payload.get("sub") or payload.get("user_id")
        if user_id:
            await session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.user_id == uuid.UUID(user_id),
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
            await session.commit()

    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"message": "Logged out successfully"}


@router.get("/me")
async def get_me(request: Request, current_user: User = Depends(get_current_user)):
    # Bei Impersonation: effektiven Tenant aus der Middleware zurückgeben
    effective_tenant_id = getattr(request.state, "tenant_id", None)
    tenant_id = effective_tenant_id or current_user.tenant_id
    return {
        "id": str(current_user.id),
        "operator_number": current_user.operator_number,
        "nfc_tag_id": current_user.nfc_tag_id,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "role": current_user.role,
        "auth_method": current_user.auth_method,
        "email": getattr(current_user, "email", None),
        "tenant_id": str(tenant_id) if tenant_id else None,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "updated_at": current_user.updated_at.isoformat() if current_user.updated_at else None,
        "last_login_at": (
            current_user.last_login_at.isoformat() if current_user.last_login_at else None
        ),
    }
