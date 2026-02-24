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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TableDayConfig(Base):
    __tablename__ = "table_day_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tables.id", ondelete="CASCADE"), nullable=True, index=True
    )
    date: Mapped[Date] = mapped_column(Date, nullable=False, index=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_temporary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shape: Mapped[str | None] = mapped_column(String(20), nullable=True)
    position_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[float | None] = mapped_column(Float, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    join_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_joinable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rotation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "table_id", "date", name="uq_table_day_config"),
    )


class ReservationTable(Base):
    __tablename__ = "reservation_tables"

    reservation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="CASCADE"), primary_key=True
    )
    table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tables.id", ondelete="RESTRICT"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReservationTableDayConfig(Base):
    __tablename__ = "reservation_table_day_configs"

    reservation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="CASCADE"), primary_key=True
    )
    table_day_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("table_day_configs.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
