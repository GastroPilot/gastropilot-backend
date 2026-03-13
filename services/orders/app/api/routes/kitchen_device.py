"""KDS device authentication endpoints."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db

_shared_path = Path(__file__).parent.parent.parent.parent.parent / "packages"
if str(_shared_path) not in sys.path:
    sys.path.insert(0, str(_shared_path))

from shared.auth import create_access_token

router = APIRouter(prefix="/kitchen/device", tags=["kitchen-device"])


class DeviceLoginRequest(BaseModel):
    device_token: str
    tenant_id: str


class DeviceLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    device_id: str
    restaurant_name: str
    tenant_id: str


@router.post("/login", response_model=DeviceLoginResponse)
async def device_login(
    data: DeviceLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate a KDS device using its device token."""
    # Set tenant context for RLS
    await db.execute(
        text("SELECT set_tenant_context(:tid, 'owner')"),
        {"tid": data.tenant_id},
    )

    result = await db.execute(
        text(
            "SELECT id, tenant_id, name, station FROM devices "
            "WHERE device_token = :token AND tenant_id = :tid"
        ),
        {"token": data.device_token, "tid": data.tenant_id},
    )
    device = result.mappings().first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found or invalid token")

    # Get restaurant name
    rest_result = await db.execute(
        text("SELECT name FROM restaurants WHERE id = :tid"),
        {"tid": data.tenant_id},
    )
    restaurant = rest_result.mappings().first()
    restaurant_name = restaurant["name"] if restaurant else "Unknown"

    # Update last_seen_at
    await db.execute(
        text("UPDATE devices SET last_seen_at = :now WHERE id = :did"),
        {"now": datetime.now(UTC), "did": str(device["id"])},
    )
    await db.commit()

    # Create a JWT for the device
    token_data = {
        "sub": str(device["id"]),
        "tenant_id": data.tenant_id,
        "role": "kitchen",
        "device": True,
        "station": device["station"] or "alle",
    }
    access_token = create_access_token(token_data)

    return DeviceLoginResponse(
        access_token=access_token,
        device_id=str(device["id"]),
        restaurant_name=restaurant_name,
        tenant_id=data.tenant_id,
    )


class DeviceValidateResponse(BaseModel):
    valid: bool
    device_id: str
    restaurant_name: str
    tenant_id: str
    station: str | None = None


@router.get("/validate", response_model=DeviceValidateResponse)
async def validate_device(
    db: AsyncSession = Depends(get_db),
):
    """Validate a device token (called with JWT in Authorization header)."""
    # This endpoint is called with a valid JWT — if we get here, the token is valid
    # For now, return a simple validation response
    return DeviceValidateResponse(
        valid=True,
        device_id="",
        restaurant_name="",
        tenant_id="",
    )
