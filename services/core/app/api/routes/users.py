from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_db, require_manager_or_above, require_owner_or_above
from app.core.security import hash_password, hash_pin
from app.models.user import User
from app.schemas.user import UserCreate, UserMeResponse, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])

PLATFORM_ROLES = {"platform_admin", "platform_support"}
_MEMORY_USER_SETTINGS: dict[str, str] = {}
PIN_ONLY_ROLES = {"manager", "staff", "kitchen", "guest"}
OWNER_ROLE = "owner"


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _derive_auth_method(
    *,
    has_pin: bool,
    has_password: bool,
    preferred: str | None,
    role: str,
) -> str:
    if preferred:
        if preferred == "pin" and not has_pin:
            raise HTTPException(status_code=400, detail="auth_method=pin benötigt eine PIN")
        if preferred == "password" and not has_password:
            raise HTTPException(
                status_code=400,
                detail="auth_method=password benötigt ein Passwort",
            )
        return preferred

    if role == "owner":
        if not has_password:
            raise HTTPException(status_code=400, detail="Owner benötigen Passwort-Login")
        return "password"

    if has_pin:
        return "pin"
    if has_password:
        return "password"

    raise HTTPException(
        status_code=400,
        detail="Mindestens PIN oder Passwort muss gesetzt sein",
    )


async def _ensure_email_unique(
    db: AsyncSession,
    email: str | None,
    *,
    exclude_user_id: UUID | None = None,
) -> None:
    if not email:
        return

    query = select(User).where(func.lower(User.email) == email.lower())
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    existing = (await db.execute(query)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="E-Mail ist bereits vergeben")


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
    class _MemoryRedis:
        async def get(self, key: str):
            return _MEMORY_USER_SETTINGS.get(key)

        async def set(self, key: str, value: str):
            _MEMORY_USER_SETTINGS[key] = value
            return True

        async def aclose(self):
            return None

    if not settings.REDIS_URL:
        yield _MemoryRedis()
        return

    import redis.asyncio as aioredis

    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        yield r
    except ValueError:
        # Invalid URL in local dev: gracefully fall back to in-memory storage.
        yield _MemoryRedis()
    finally:
        if "r" in locals():
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
    if current_user.role in PIN_ONLY_ROLES and (
        body.email is not None or body.password is not None or body.auth_method == "password"
    ):
        raise HTTPException(
            status_code=400,
            detail="Nur Owner dürfen E-Mail/Passwort nutzen",
        )

    next_email = _normalize_email(body.email) if body.email is not None else current_user.email

    if body.password is not None and not next_email:
        raise HTTPException(
            status_code=400, detail="Für Passwort-Login ist eine E-Mail erforderlich"
        )
    if (
        body.email is not None
        and next_email
        and body.password is None
        and not current_user.password_hash
    ):
        raise HTTPException(
            status_code=400,
            detail="E-Mail und Passwort müssen zusammen gesetzt werden",
        )

    if body.email is not None:
        await _ensure_email_unique(db, next_email, exclude_user_id=current_user.id)

    if body.first_name is not None:
        current_user.first_name = body.first_name
    if body.last_name is not None:
        current_user.last_name = body.last_name
    if body.email is not None:
        current_user.email = next_email
    if body.operator_number is not None:
        current_user.operator_number = body.operator_number
    if body.pin is not None:
        current_user.pin_hash = hash_pin(body.pin)
    if body.password is not None:
        current_user.password_hash = hash_password(body.password)
    if body.nfc_tag_id is not None:
        current_user.nfc_tag_id = body.nfc_tag_id
    if body.auth_method is not None:
        if current_user.role == OWNER_ROLE and body.auth_method != "password":
            raise HTTPException(
                status_code=400,
                detail="Owner verwenden immer Passwort als primäre Login-Art",
            )
        if body.auth_method == "pin" and not (body.pin is not None or current_user.pin_hash):
            raise HTTPException(status_code=400, detail="Für PIN-Login ist eine PIN erforderlich")
        if body.auth_method == "password" and not (
            body.password is not None or current_user.password_hash
        ):
            raise HTTPException(
                status_code=400,
                detail="Für Passwort-Login ist ein Passwort erforderlich",
            )
        if body.auth_method == "password" and not next_email:
            raise HTTPException(
                status_code=400,
                detail="Für Passwort-Login ist eine E-Mail erforderlich",
            )
        current_user.auth_method = body.auth_method
    elif current_user.role == OWNER_ROLE:
        current_user.auth_method = "password"
    elif current_user.role in PIN_ONLY_ROLES:
        current_user.auth_method = "pin"
    elif body.password is not None and body.pin is None:
        current_user.auth_method = "password"
    elif body.pin is not None and body.password is None:
        current_user.auth_method = "pin"

    await db.commit()
    await db.refresh(current_user)
    return current_user


# ---------------------------------------------------------------------------
# Restaurant-User-Verwaltung (Owner/Manager)
# ---------------------------------------------------------------------------


@router.get("", response_model=list[UserResponse])
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


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner_or_above),
):
    tenant_id = _effective_tenant_id(request, current_user)
    if tenant_id is None and current_user.role != "platform_admin":
        raise HTTPException(
            status_code=400,
            detail="Kein aktiver Tenant-Kontext. Bitte zuerst Tenant impersonieren.",
        )

    normalized_email = _normalize_email(body.email)
    has_email = bool(normalized_email)
    has_pin = bool(body.pin)
    has_password = bool(body.password)

    if body.role == OWNER_ROLE:
        if not has_email or not has_password:
            raise HTTPException(status_code=400, detail="Owner benötigen E-Mail und Passwort")
        if not has_pin or not body.operator_number:
            raise HTTPException(
                status_code=400,
                detail="Owner benötigen Bedienernummer und PIN für Dashboard/App",
            )
        auth_method = "password"
    elif body.role in PIN_ONLY_ROLES:
        if has_email or has_password or body.auth_method == "password":
            raise HTTPException(
                status_code=400,
                detail="Nur Owner dürfen E-Mail/Passwort nutzen",
            )
        if not has_pin or not body.operator_number:
            raise HTTPException(
                status_code=400,
                detail="Für diese Rolle sind Bedienernummer und PIN erforderlich",
            )
        auth_method = "pin"
    else:
        if has_password and not has_email:
            raise HTTPException(
                status_code=400,
                detail="Für Passwort-Login ist eine E-Mail erforderlich",
            )
        if has_email and not has_password:
            raise HTTPException(
                status_code=400,
                detail="E-Mail und Passwort müssen zusammen gesetzt werden",
            )
        if has_pin and not body.operator_number:
            raise HTTPException(
                status_code=400,
                detail="Für PIN-Login ist eine 4-stellige Bedienernummer erforderlich",
            )
        auth_method = _derive_auth_method(
            has_pin=has_pin,
            has_password=has_password,
            preferred=body.auth_method,
            role=body.role,
        )

    await _ensure_email_unique(db, normalized_email)

    user = User(
        tenant_id=tenant_id,
        first_name=body.first_name,
        last_name=body.last_name,
        role=body.role,
        email=normalized_email,
        operator_number=body.operator_number,
        nfc_tag_id=body.nfc_tag_id,
        auth_method=auth_method,
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

    previous_role = user.role
    next_email = _normalize_email(body.email) if body.email is not None else user.email
    next_role = body.role if body.role is not None else user.role
    next_operator_number = (
        body.operator_number if body.operator_number is not None else user.operator_number
    )
    will_have_pin = bool(body.pin) or bool(user.pin_hash)
    will_have_password = bool(body.password) or bool(user.password_hash)

    if body.email is not None:
        await _ensure_email_unique(db, next_email, exclude_user_id=user.id)

    if next_role == OWNER_ROLE:
        if not next_email:
            raise HTTPException(status_code=400, detail="Owner benötigen eine E-Mail")
        if not will_have_password:
            raise HTTPException(status_code=400, detail="Owner benötigen ein Passwort")
        if not next_operator_number or not will_have_pin:
            raise HTTPException(
                status_code=400,
                detail="Owner benötigen Bedienernummer und PIN für Dashboard/App",
            )
    elif next_role in PIN_ONLY_ROLES:
        if body.email is not None and next_email:
            raise HTTPException(
                status_code=400,
                detail="Nur Owner dürfen E-Mail/Passwort nutzen",
            )
        if body.password is not None or body.auth_method == "password":
            raise HTTPException(
                status_code=400,
                detail="Nur Owner dürfen E-Mail/Passwort nutzen",
            )
        if not next_operator_number or not will_have_pin:
            raise HTTPException(
                status_code=400,
                detail="Für diese Rolle sind Bedienernummer und PIN erforderlich",
            )
    else:
        if body.password is not None and not next_email:
            raise HTTPException(
                status_code=400,
                detail="Für Passwort-Login ist eine E-Mail erforderlich",
            )
        if (
            body.email is not None
            and next_email
            and body.password is None
            and not user.password_hash
        ):
            raise HTTPException(
                status_code=400,
                detail="E-Mail und Passwort müssen zusammen gesetzt werden",
            )
        if body.pin is not None and not next_operator_number:
            raise HTTPException(
                status_code=400,
                detail="Für PIN-Login ist eine 4-stellige Bedienernummer erforderlich",
            )

    if body.first_name is not None:
        user.first_name = body.first_name
    if body.last_name is not None:
        user.last_name = body.last_name
    if body.email is not None:
        user.email = next_email if next_role == OWNER_ROLE else None
    if body.role is not None:
        user.role = body.role
        if previous_role == OWNER_ROLE and body.role in PIN_ONLY_ROLES:
            user.email = None
            user.password_hash = None
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
    if next_role == OWNER_ROLE:
        user.auth_method = "password"
    elif next_role in PIN_ONLY_ROLES:
        user.auth_method = "pin"
    elif body.auth_method is not None:
        if body.auth_method == "password":
            if body.password is None and not user.password_hash:
                raise HTTPException(
                    status_code=400,
                    detail="Für Passwort-Login ist ein Passwort erforderlich",
                )
            if not next_email:
                raise HTTPException(
                    status_code=400,
                    detail="Für Passwort-Login ist eine E-Mail erforderlich",
                )
        if body.auth_method == "pin" and body.pin is None and not user.pin_hash:
            raise HTTPException(status_code=400, detail="Für PIN-Login ist eine PIN erforderlich")
        user.auth_method = body.auth_method
    elif body.password is not None and body.pin is None:
        user.auth_method = "password"
    elif body.pin is not None and body.password is None:
        user.auth_method = "pin"

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
