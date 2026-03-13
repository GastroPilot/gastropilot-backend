"""Guest CRM schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class GuestListResponse(BaseModel):
    id: UUID
    name: str
    email: str | None = None
    phone: str | None = None
    visit_count: int = 0
    last_visit: datetime | None = None
    is_regular: bool = False
    tags: list[str] = []

    model_config = {"from_attributes": True}


class GuestDetailResponse(GuestListResponse):
    allergen_profile: list | None = None
    notes: str | None = None
    reservation_history: list[dict] = []
    order_history: list[dict] = []


class GuestUpdateRequest(BaseModel):
    notes: str | None = None
    tags: list[str] | None = None
    type: str | None = None


class GuestStatsResponse(BaseModel):
    total: int
    regulars: int
    new_this_month: int
