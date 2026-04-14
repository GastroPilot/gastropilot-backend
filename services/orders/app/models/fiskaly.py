"""fiskaly KassenSichV TSE models for TSS configuration and transaction signing."""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FiskalyTssConfig(Base):
    """One TSS configuration per tenant (restaurant)."""

    __tablename__ = "fiskaly_tss_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, index=True
    )
    tss_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    client_serial_number: Mapped[str] = mapped_column(String(128), nullable=False)
    tss_serial_number: Mapped[str | None] = mapped_column(String(256), nullable=True)
    admin_pin: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    fiskaly_org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    fiskaly_api_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    fiskaly_api_secret: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FiskalyTransaction(Base):
    """One row per signed TSE transaction."""

    __tablename__ = "fiskaly_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tss_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tx_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tx_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tx_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    receipt_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    time_start: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    time_end: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    signature_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature_algorithm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signature_counter: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    qr_code_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    tss_serial_number: Mapped[str | None] = mapped_column(String(256), nullable=True)
    client_serial_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    receipt_public_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FiskalyCashPointClosing(Base):
    """One row per DSFinV-K cash point closing (Tagesabschluss)."""

    __tablename__ = "fiskaly_cash_point_closings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    closing_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    business_date: Mapped[str] = mapped_column(String(10), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    cash_register_export_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    total_amount: Mapped[float | None] = mapped_column(nullable=True)
    total_cash: Mapped[float | None] = mapped_column(nullable=True)
    total_non_cash: Mapped[float | None] = mapped_column(nullable=True)
    transaction_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_training: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_automatic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_request: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dsfinvk_export_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    dsfinvk_export_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
