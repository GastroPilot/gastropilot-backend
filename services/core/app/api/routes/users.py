from __future__ import annotations
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_db, require_manager_or_above, require_owner_or_above
from app.models.user import User
from app.schemas.user import UserCreate, UserMeResponse, UserResponse, UserUpdate
from app.core.security import hash_password, hash_pin

router = APIRouter(prefix="/users", tags=["users"])

PLATFORM_ROLES = {"platform_admin", "platform_support"}


def _effective_tenant_id(request: Request, current_user: User) -> UUID | None:
    """Gibt die effektive tenant_id zurück.

    - Bei Impersonation: die impersonierte tenant_id aus request.state
    - Sonst: die tenant_id des Users
    - Platform-Admins ohne Impersonation: None (= kein Tenant-Filter)
    """
    state_tenant = getattr(request.state, "tenant_id", None)
    if state_tenant:
        return state_tenant
    return current_user.tenant_id


# ---------------------------------------------------------------------------
# User Settings (gespeichert in Redis, Key: user_settings:{user_id})
# ---------------------------------------------------------------------------

class UserSettingsResponse(BaseModel):
    id: int = 1
    user_id: str
    settings: dict
    created_at_utc: str = "2024-01-01T00:00:00Z"
    updated_at_utc: str = "2024-01-01T00:00:00Z"


class UserSettingsUpdate(BaseModel):
    settings: dict


async def _get_redis():
    import redis.asyncio as aioredis
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        yield r
    finally:
        await r.aclose()


@router.get("/me/settings/")
async def get_my_settings(
    current_user: User = Depends(get_current_user),
    redis=Depends(_get_redis),
) -> UserSettingsResponse:
    raw = await redis.get(f"user_settings:{current_user.id}")
    s = json.loads(raw) if raw else {}
    return UserSettingsResponse(user_id=str(current_user.id), settings=s)


@router.patch("/me/settings/")
async def update_my_settings(
    body: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    redis=Depends(_get_redis),
) -> UserSettingsResponse:
    raw = await redis.get(f"user_settings:{current_user.id}")
    s = json.loads(raw) if raw else {}
    s.update(body.settings)
    await redis.set(f"user_settings:{current_user.id}", json.dumps(s))
    return UserSettingsResponse(user_id=str(current_user.id), settings=s)


@router.delete("/me/settings/{key}")
async def delete_my_setting_key(
    key: str,
    current_user: User = Depends(get_current_user),
    redis=Depends(_get_redis),
) -> UserSettingsResponse:
    raw = await redis.get(f"user_settings:{current_user.id}")
    s = json.loads(raw) if raw else {}
    s.pop(key, None)
    await redis.set(f"user_settings:{current_user.id}", json.dumps(s))
    return UserSettingsResponse(user_id=str(current_user.id), settings=s)


@router.get("/me", response_model=UserMeResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserMeResponse)
async def update_me(
    body: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.first_name is not None:
        current_user.first_name = body.first_name
    if body.last_name is not None:
        current_user.last_name = body.last_name
    if body.email is not None:
        current_user.email = body.email
    if body.pin is not None:
        current_user.pin_hash = hash_pin(body.pin)
    if body.password is not None:
        current_user.password_hash = hash_password(body.password)
    if body.nfc_tag_id is not None:
        current_user.nfc_tag_id = body.nfc_tag_id

    await db.commit()
    await db.refresh(current_user)
    return current_user


# ---------------------------------------------------------------------------
# Restaurant-User-Verwaltung (Owner/Manager)
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[UserResponse])
async def list_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    tenant_id = _effective_tenant_id(request, current_user)
    query = select(User).where(User.is_active.is_(True))
    if tenant_id:
        query = query.where(User.tenant_id == tenant_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner_or_above),
):
    user = User(
        tenant_id=current_user.tenant_id,
        first_name=body.first_name,
        last_name=body.last_name,
        role=body.role,
        email=body.email,
        operator_number=body.operator_number,
        nfc_tag_id=body.nfc_tag_id,
        auth_method="pin" if body.pin else "password",
    )
    if body.pin:
        user.pin_hash = hash_pin(body.pin)
    if body.password:
        user.password_hash = hash_password(body.password)

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    tenant_id = _effective_tenant_id(request, current_user)
    query = select(User).where(User.id == user_id)
    if tenant_id:
        query = query.where(User.tenant_id == tenant_id)
    user = (await db.execute(query)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner_or_above),
):
    tenant_id = _effective_tenant_id(request, current_user)
    query = select(User).where(User.id == user_id)
    if tenant_id:
        query = query.where(User.tenant_id == tenant_id)
    user = (await db.execute(query)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    if body.first_name is not None:
        user.first_name = body.first_name
    if body.last_name is not None:
        user.last_name = body.last_name
    if body.email is not None:
        user.email = body.email
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.operator_number is not None:
        user.operator_number = body.operator_number
    if body.nfc_tag_id is not None:
        user.nfc_tag_id = body.nfc_tag_id
    if body.pin is not None:
        user.pin_hash = hash_pin(body.pin)
    if body.password is not None:
        user.password_hash = hash_password(body.password)

    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner_or_above),
):
    tenant_id = _effective_tenant_id(request, current_user)
    query = select(User).where(User.id == user_id)
    if tenant_id:
        query = query.where(User.tenant_id == tenant_id)
    user = (await db.execute(query)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Eigenen Account nicht löschbar")

    user.is_active = False
    await db.commit()
