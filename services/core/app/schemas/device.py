from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DeviceCreate(BaseModel):
    restaurant_id: UUID | None = None
    name: str
    station: str = "alle"


class DeviceResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    station: str
    last_seen_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeviceWithTokenResponse(DeviceResponse):
    """Response that includes the device_token (only shown on create/regenerate)."""

    device_token: str


class DeviceRegenerateResponse(BaseModel):
    id: UUID
    device_token: str
    message: str
