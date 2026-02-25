from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_platform_admin
from app.core.security import create_access_token, hash_pin
from app.models.audit import PlatformAuditLog
from app.models.restaurant import Restaurant
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])


# ─── Schemas ──────────────────────────────────────────────────────────────────


class TenantCreate(BaseModel):
    # Restaurant
    name: str
    slug: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    # Erster Owner-User
    owner_first_name: str
    owner_last_name: str
    owner_operator_number: str  # 4-stellige Bediener-Nr., z.B. "0001"
    owner_pin: str  # 6–8 Ziffern

    @field_validator("owner_operator_number")
    @classmethod
    def validate_operator_number(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}", v):
            raise ValueError("operator_number muss genau 4 Ziffern sein")
        return v

    @field_validator("owner_pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        if not re.fullmatch(r"\d{6,8}", v):
            raise ValueError("PIN muss 6–8 Ziffern enthalten")
        return v

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"[a-z0-9-]+", v):
            raise ValueError("slug darf nur Kleinbuchstaben, Ziffern und Bindestriche enthalten")
        return v


class TenantCreateResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    owner_id: str
    owner_operator_number: str


class TenantUpdate(BaseModel):
    name: str | None = None
    settings: dict | None = None


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/tenants")
async def list_tenants(
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Restaurant))
    tenants = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "slug": t.slug,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tenants
    ]


@router.post("/tenants", response_model=TenantCreateResponse, status_code=201)
async def create_tenant(
    data: TenantCreate,
    request: Request,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    # Slug-Konflikt prüfen
    if data.slug:
        existing = await session.execute(select(Restaurant).where(Restaurant.slug == data.slug))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Slug ist bereits vergeben")

    # 1. Restaurant anlegen
    restaurant = Restaurant(
        name=data.name,
        slug=data.slug,
        address=data.address,
        phone=data.phone,
        email=data.email,
    )
    session.add(restaurant)
    await session.flush()  # ID generieren, noch kein Commit

    # 2. Owner-User anlegen
    owner = User(
        tenant_id=restaurant.id,
        operator_number=data.owner_operator_number,
        pin_hash=hash_pin(data.owner_pin),
        first_name=data.owner_first_name,
        last_name=data.owner_last_name,
        role="owner",
        auth_method="pin",
        is_active=True,
    )
    session.add(owner)

    # 3. Audit-Log
    log = PlatformAuditLog(
        admin_user_id=current_user.id,
        target_tenant_id=restaurant.id,
        action="tenant.created",
        entity_type="restaurant",
        entity_id=restaurant.id,
        description=f"Tenant '{data.name}' mit Owner {data.owner_operator_number} angelegt",
        ip_address=request.client.host if request.client else None,
    )
    session.add(log)

    await session.commit()

    return TenantCreateResponse(
        tenant_id=str(restaurant.id),
        tenant_name=restaurant.name,
        owner_id=str(owner.id),
        owner_operator_number=owner.operator_number,
    )


@router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: uuid.UUID,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Restaurant).where(Restaurant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "address": tenant.address,
        "phone": tenant.phone,
        "email": tenant.email,
        "settings": tenant.settings,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
    }


@router.patch("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: uuid.UUID,
    data: TenantUpdate,
    request: Request,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Restaurant).where(Restaurant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if data.name is not None:
        tenant.name = data.name
    if data.settings is not None:
        current = dict(tenant.settings or {})
        current.update(data.settings)
        tenant.settings = current

    log = PlatformAuditLog(
        admin_user_id=current_user.id,
        target_tenant_id=tenant_id,
        action="tenant.updated",
        entity_type="restaurant",
        entity_id=tenant_id,
        ip_address=request.client.host if request.client else None,
    )
    session.add(log)
    await session.commit()
    return {"id": str(tenant.id), "name": tenant.name}


@router.delete("/tenants/{tenant_id}", status_code=200)
async def delete_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Restaurant).where(Restaurant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant_name = tenant.name

    # Audit-Log VOR dem Loeschen erstellen (target_tenant_id wird via CASCADE nicht geloescht,
    # da PlatformAuditLog.target_tenant_id nullable ist oder kein FK-Constraint hat)
    log = PlatformAuditLog(
        admin_user_id=current_user.id,
        target_tenant_id=tenant_id,
        action="tenant.deleted",
        entity_type="restaurant",
        entity_id=tenant_id,
        description=f"Tenant '{tenant_name}' und alle zugehoerigen Daten geloescht",
        ip_address=request.client.host if request.client else None,
    )
    session.add(log)
    await session.flush()

    # Tenant loeschen — CASCADE loescht Users, Areas, Tables, Obstacles etc.
    await session.delete(tenant)
    await session.commit()

    return {"deleted": True, "tenant_id": str(tenant_id), "tenant_name": tenant_name}


@router.get("/tenants/{tenant_id}/impersonate")
async def impersonate_tenant(
    tenant_id: uuid.UUID,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Restaurant).where(Restaurant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    token_data = {
        "sub": str(current_user.id),
        "role": "platform_admin",
        "tenant_id": None,
        "impersonating_tenant_id": str(tenant_id),
    }
    impersonation_token = create_access_token(token_data)
    return {
        "impersonation_token": impersonation_token,
        "tenant_id": str(tenant_id),
        "tenant_name": tenant.name,
    }


@router.get("/audit-log")
async def get_audit_log(
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(PlatformAuditLog).order_by(PlatformAuditLog.created_at.desc()).limit(200)
    )
    logs = result.scalars().all()
    return [
        {
            "id": str(log.id),
            "admin_user_id": str(log.admin_user_id) if log.admin_user_id else None,
            "target_tenant_id": str(log.target_tenant_id) if log.target_tenant_id else None,
            "action": log.action,
            "description": log.description,
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
