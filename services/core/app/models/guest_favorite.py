"""Guest favorite model for restaurant wishlists."""

from __future__ import annotations

import uuid

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GuestFavorite(Base):
    __tablename__ = "guest_favorites"
    __table_args__ = (
        UniqueConstraint("guest_profile_id", "restaurant_id", name="uq_guest_favorites"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guest_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("guest_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
