"""KDS device management endpoints."""

from __future__ import annotations

import logging
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_owner_or_above
from app.models.device import Device
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.device import (
    DeviceCreate,
    DeviceRegenerateResponse,
    DeviceResponse,
    DeviceWithTokenResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/devices", tags=["devices"])


async def _resolve_tenant_context_for_device(
    request: Request,
    current_user: User,
    db: AsyncSession,
    requested_tenant_id: UUID | None,
) -> UUID:
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
    if effective_tenant_id:
        if requested_tenant_id and requested_tenant_id != effective_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Requested restaurant_id does not match tenant context",
            )
        return effective_tenant_id

    if current_user.role != "platform_admin":
        raise HTTPException(status_code=403, detail="User has no tenant context")

    if requested_tenant_id:
        restaurant_result = await db.execute(
            select(Restaurant.id).where(Restaurant.id == requested_tenant_id)
        )
        if restaurant_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Restaurant not found")
        return requested_tenant_id

    raise HTTPException(
        status_code=400,
        detail=(
            "Tenant context required (token has no tenant and no restaurant tenant "
            "could be resolved)"
        ),
    )


@router.get("/", response_model=list[DeviceResponse])
async def list_devices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner_or_above),
):
    """List all KDS devices for the current tenant."""
    result = await db.execute(select(Device).order_by(Device.created_at.desc()))
    return result.scalars().all()


@router.post(
    "/",
    response_model=DeviceWithTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_device(
    request: Request,
    body: DeviceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner_or_above),
):
    """Create a new KDS device and return its token."""
    effective_tenant_id = await _resolve_tenant_context_for_device(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=body.restaurant_id,
    )

    device = Device(
        tenant_id=effective_tenant_id,
        name=body.name.strip(),
        station=body.station.strip() or "alle",
        device_token=secrets.token_urlsafe(64),
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


@router.delete("/{device_id}")
async def delete_device(
    device_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner_or_above),
):
    """Delete / revoke a KDS device."""
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    await db.delete(device)
    await db.commit()
    return {"message": "deleted"}


@router.post(
    "/{device_id}/regenerate-token",
    response_model=DeviceRegenerateResponse,
)
async def regenerate_device_token(
    device_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner_or_above),
):
    """Regenerate the token for a KDS device (invalidates old token)."""
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device.device_token = secrets.token_urlsafe(64)
    await db.commit()
    await db.refresh(device)

    return DeviceRegenerateResponse(
        id=device.id,
        device_token=device.device_token,
        message="Token regenerated successfully",
    )
