from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UpsellPackage(Base):
    __tablename__ = "upsell_packages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    available_from_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    available_until_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    min_party_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_party_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_times: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    available_weekdays: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReservationUpsellPackage(Base):
    __tablename__ = "reservation_upsell_packages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reservations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    upsell_package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("upsell_packages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    price_at_time: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "reservation_id", "upsell_package_id", name="uq_reservation_upsell_package"
        ),
    )
