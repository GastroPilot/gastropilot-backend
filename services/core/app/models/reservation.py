from __future__ import annotations

import uuid

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Guest(Base):
    __tablename__ = "guests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    guest_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guest_profiles.id", ondelete="SET NULL"), nullable=True
    )
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guests.id", ondelete="SET NULL"), nullable=True
    )
    table_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tables.id", ondelete="SET NULL"), nullable=True
    )
    start_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(
            "pending",
            "confirmed",
            "seated",
            "completed",
            "canceled",
            "no_show",
            name="reservation_status",
            create_type=False,
        ),
        nullable=False,
        default="pending",
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    guest_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    guest_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guest_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confirmation_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    special_requests: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    confirmed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    no_show_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    voucher_discount_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    prepayment_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prepayment_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
