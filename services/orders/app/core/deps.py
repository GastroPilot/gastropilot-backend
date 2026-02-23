from __future__ import annotations
import uuid
import sys
from pathlib import Path
from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_session_factories
from .config import settings

_shared_path = Path(__file__).parent.parent.parent.parent.parent / "packages"
if str(_shared_path) not in sys.path:
    sys.path.insert(0, str(_shared_path))

from shared.auth import configure, verify_token

configure(
    jwt_secret=settings.JWT_SECRET,
    jwt_algorithm=settings.JWT_ALGORITHM,
    jwt_issuer=settings.JWT_ISSUER,
    jwt_audience=settings.JWT_AUDIENCE,
    jwt_leeway_seconds=settings.JWT_LEEWAY_SECONDS,
    access_token_expire_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    refresh_token_expire_days=settings.REFRESH_TOKEN_EXPIRE_DAYS,
    bcrypt_rounds=settings.BCRYPT_ROUNDS,
    refresh_token_pepper=settings.REFRESH_TOKEN_PEPPER,
)

security = HTTPBearer(auto_error=False)


async def get_db(request: Request):
    session_factory_app, session_factory_admin = get_session_factories()
    is_admin = getattr(request.state, "is_admin", False)
    tenant_id = getattr(request.state, "tenant_id", None)
    role = getattr(request.state, "role", None)
    factory = session_factory_admin if is_admin else session_factory_app
    async with factory() as session:
        try:
            if tenant_id and role:
                await session.execute(
                    text("SELECT set_tenant_context(:tenant_id, :role)"),
                    {"tenant_id": str(tenant_id), "role": str(role)},
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
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing user_id")
    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


STAFF_ROLES = {"owner", "manager", "staff", "kitchen", "platform_admin", "platform_support"}
MANAGER_ROLES = {"owner", "manager", "platform_admin", "platform_support"}
OWNER_ROLES = {"owner", "platform_admin"}


async def require_staff_or_above(user=Depends(get_current_user)):
    if user.role not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


async def require_manager_or_above(user=Depends(get_current_user)):
    if user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


async def require_owner_or_above(user=Depends(get_current_user)):
    if user.role not in OWNER_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user
