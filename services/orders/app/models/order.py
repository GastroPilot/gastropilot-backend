from __future__ import annotations

import uuid

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    table_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    table_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    guest_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    order_number: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(
            "open",
            "sent_to_kitchen",
            "in_preparation",
            "ready",
            "served",
            "paid",
            "canceled",
            name="order_status",
            create_type=False,
        ),
        nullable=False,
        default="open",
    )
    party_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subtotal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tax_amount_7: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tax_amount_19: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tax_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    discount_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tip_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payment_status: Mapped[str] = mapped_column(
        Enum("unpaid", "partial", "paid", name="payment_status", create_type=False),
        nullable=False,
        default="unpaid",
    )
    split_payments: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    special_requests: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    sent_to_kitchen_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    in_preparation_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ready_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    served_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    discount_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    guest_allergens: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    kitchen_ticket_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    item_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    total_price: Mapped[float] = mapped_column(Float, nullable=False)
    tax_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.19)
    status: Mapped[str] = mapped_column(
        Enum(
            "pending",
            "sent",
            "in_preparation",
            "ready",
            "served",
            "canceled",
            name="order_item_status",
            create_type=False,
        ),
        nullable=False,
        default="pending",
    )
    kitchen_ticket_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_to_kitchen_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    course: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    allergens: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SumUpPayment(Base):
    __tablename__ = "sumup_payments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    checkout_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    client_transaction_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transaction_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reader_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    webhook_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    initiated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
