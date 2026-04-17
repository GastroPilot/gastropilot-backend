from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# ─── Response Schemas ────────────────────────────────────────────────


class InvitedGuestProfile(BaseModel):
    first_name: str
    last_name: str
    allergen_ids: list[str]


class GuestInviteResponse(BaseModel):
    id: UUID
    reservation_id: UUID
    invite_token: str
    status: str
    invited_guest: InvitedGuestProfile | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CreateInviteResponse(BaseModel):
    invite_token: str
    invite_url: str


class InviteReservationInfo(BaseModel):
    restaurant_name: str
    restaurant_slug: str
    date: str
    time: str
    party_size: int
    host_name: str


class InviteDetailsResponse(BaseModel):
    reservation: InviteReservationInfo
    invite_status: str


# ─── Request Schemas ─────────────────────────────────────────────────


class AcceptInviteRequest(BaseModel):
    first_name: str
    last_name: str
    allergen_ids: list[str] = []
