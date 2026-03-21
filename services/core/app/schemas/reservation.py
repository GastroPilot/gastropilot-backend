from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, field_validator

ReservationStatus = Literal[
    "pending",
    "confirmed",
    "seated",
    "completed",
    "canceled",
    "no_show",
]


class ReservationBase(BaseModel):
    party_size: int
    starts_at: datetime = Field(validation_alias=AliasChoices("starts_at", "start_at"))
    ends_at: datetime | None = Field(
        default=None, validation_alias=AliasChoices("ends_at", "end_at")
    )
    notes: str | None = None
    source: str = Field(
        default="manual", validation_alias=AliasChoices("source", "channel")
    )


class ReservationCreate(ReservationBase):
    restaurant_id: UUID | None = None
    guest_id: UUID | None = None
    table_id: UUID | None = None
    status: ReservationStatus = "pending"
    # Wenn kein Gast-Account: Gastdaten direkt
    guest_name: str | None = None
    guest_email: str | None = None
    guest_phone: str | None = None
    special_requests: str | None = None
    tags: list[str] | None = None

    @field_validator("party_size")
    @classmethod
    def party_size_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Personenanzahl muss mindestens 1 sein")
        return v


class ReservationUpdate(BaseModel):
    party_size: int | None = None
    starts_at: datetime | None = Field(
        default=None, validation_alias=AliasChoices("starts_at", "start_at")
    )
    ends_at: datetime | None = Field(
        default=None, validation_alias=AliasChoices("ends_at", "end_at")
    )
    notes: str | None = None
    status: ReservationStatus | None = None
    table_id: UUID | None = None
    guest_id: UUID | None = None
    guest_name: str | None = None
    guest_email: str | None = None
    guest_phone: str | None = None
    special_requests: str | None = None
    tags: list[str] | None = None


class GuestResponse(BaseModel):
    id: UUID
    name: str
    email: str | None = None
    phone: str | None = None

    model_config = {"from_attributes": True}


class ReservationResponse(ReservationBase):
    id: UUID
    tenant_id: UUID
    status: str
    table_id: UUID | None = None
    guest_id: UUID | None = None
    guest: GuestResponse | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TimeSlotRequest(BaseModel):
    date: date
    party_size: int
    duration_minutes: int = 90


class TimeSlot(BaseModel):
    starts_at: datetime
    ends_at: datetime
    available: bool
    available_tables: int
