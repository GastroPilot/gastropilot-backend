"""ORM-Modell für iOS-Live-Activity-Push-Token einer Order.

Pro (order_id, push_token) speichern wir maximal eine Zeile. Beendet wird die
Live Activity, indem ``ended_at`` gesetzt wird – wir löschen nicht physisch,
damit ein Audit-Trail existiert.

Tenant-Isolation:
    - ``tenant_id`` ist Pflicht.
    - RLS-Policy lebt in der zugehörigen Alembic-Migration (``services/core``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LiveActivityToken(Base):
    __tablename__ = "live_activity_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    push_token: Mapped[str] = mapped_column(String(256), nullable=False)
    started_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    ended_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (UniqueConstraint("order_id", "push_token", name="uq_lat_order_token"),)
