from __future__ import annotations

import uuid
from typing import AsyncGenerator

from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session_factories
from .security import verify_token

security = HTTPBearer(auto_error=False)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Provides a DB session with RLS context set from request.state (set by TenantMiddleware).
    Uses gastropilot_admin pool for platform admins, gastropilot_app for all others.
    """
    session_factory_app, session_factory_admin = get_session_factories()

    is_admin = getattr(request.state, "is_admin", False)
    tenant_id = getattr(request.state, "tenant_id", None)
    role = getattr(request.state, "role", None)

    factory = session_factory_admin if is_admin else session_factory_app

    async with factory() as session:
        try:
            if tenant_id is not None and role is not None:
                await session.execute(
                    text("SELECT set_tenant_context(:tenant_id, :role)"),
                    {"tenant_id": str(tenant_id), "role": str(role)},
                )
            elif role is not None:
                await session.execute(
                    text("SELECT set_config('app.current_role', :role, true)"),
                    {"role": str(role)},
                )
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    access_token: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_db),
):
    from app.models.user import User

    header_token = credentials.credentials if credentials else None
    token = access_token or header_token

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing user_id")

    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is inactive")

    return user


async def require_owner_or_above(user=Depends(get_current_user)):
    if user.role not in ("owner", "manager", "platform_admin"):
        raise HTTPException(status_code=403, detail="Owner or above required")
    return user


async def require_manager_or_above(user=Depends(get_current_user)):
    if user.role not in ("owner", "manager", "platform_admin"):
        raise HTTPException(status_code=403, detail="Manager or above required")
    return user


async def require_platform_admin(user=Depends(get_current_user)):
    if user.role != "platform_admin":
        raise HTTPException(status_code=403, detail="Platform admin required")
    return user


async def require_staff_or_above(user=Depends(get_current_user)):
    if user.role not in ("staff", "kitchen", "owner", "manager", "platform_admin"):
        raise HTTPException(status_code=403, detail="Staff or above required")
    return user
