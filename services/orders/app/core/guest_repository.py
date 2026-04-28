"""Guest-scoped data access for the public guest endpoints.

The orders service uses ``session_factory_admin`` for guest endpoints
because guest JWTs do not carry a restaurant ``tenant_id`` — RLS would
hide every row otherwise. That means there is **no DB-level guard** that
prevents a future endpoint from reading another guest's data; the only
protection is the manual ``guest_profile_id`` filter we apply in code.

This repository is the only place that touches ``orders`` / ``order_items``
/ ``live_activity_tokens`` / ``restaurants`` for guest endpoints. All
public methods perform an ownership check up-front, so a new endpoint
can use the repo without re-deriving the filter (and without forgetting it).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.guest_deps import GuestIdentity
from app.models.live_activity_token import LiveActivityToken
from app.models.order import Order, OrderItem


class GuestOrdersRepository:
    """All DB access used by the public guest endpoints.

    Every public method that takes an ``order_id`` first calls the
    private ownership check, so callers cannot accidentally bypass it.
    """

    def __init__(self, db: AsyncSession, guest: GuestIdentity) -> None:
        self._db = db
        self._guest = guest
        # Per-request memoization of resolved ownership: each FastAPI
        # request constructs a fresh repository, so this dict can never
        # leak across guests. Saves a redundant pair of queries when the
        # same endpoint touches the same order multiple times (e.g. the
        # detail route calling list_order_items after get_owned_order).
        self._owned_cache: dict[uuid.UUID, Order] = {}

    async def get_owned_order(self, order_id: uuid.UUID) -> Order:
        """Return ``Order`` if the authenticated guest owns it, else 404.

        "Owns" = there is a row in ``guests`` whose ``id`` matches
        ``order.guest_id`` and whose ``guest_profile_id`` matches the JWT
        ``sub`` claim. We deliberately raise 404 on a mismatch (not 403)
        so the existence of foreign orders is not leaked.
        """
        return await self._resolve_owned(order_id)

    async def upsert_live_activity_token(
        self,
        order_id: uuid.UUID,
        push_token: str,
    ) -> None:
        """Upsert a Live-Activity push token for an owned order.

        Idempotent: re-sending the same ``(order_id, push_token)`` keeps
        the row active (``ended_at = NULL``) and preserves ``started_at``.
        """
        order = await self._resolve_owned(order_id)

        stmt = (
            pg_insert(LiveActivityToken)
            .values(
                tenant_id=order.tenant_id,
                order_id=order.id,
                push_token=push_token,
            )
            .on_conflict_do_update(
                constraint="uq_lat_order_token",
                set_={"ended_at": None},
            )
        )
        await self._db.execute(stmt)
        await self._db.commit()

    async def end_live_activity_token(
        self,
        order_id: uuid.UUID,
        push_token: str,
    ) -> None:
        """Soft-delete a token; idempotent (no-op if missing or already ended)."""
        order = await self._resolve_owned(order_id)

        result = await self._db.execute(
            select(LiveActivityToken).where(
                LiveActivityToken.order_id == order.id,
                LiveActivityToken.push_token == push_token,
            )
        )
        token_row = result.scalar_one_or_none()
        if token_row is None or token_row.ended_at is not None:
            return

        token_row.ended_at = datetime.now(UTC)
        await self._db.commit()

    async def list_order_items(self, order_id: uuid.UUID) -> Sequence[OrderItem]:
        """List items of an owned order."""
        await self._resolve_owned(order_id)
        result = await self._db.execute(select(OrderItem).where(OrderItem.order_id == order_id))
        return result.scalars().all()

    async def get_restaurant_name(self, tenant_id: uuid.UUID) -> str | None:
        """Lookup the restaurant display name. No ownership check needed —
        the caller has already proved ownership of the order whose
        ``tenant_id`` we are looking up.
        """
        row = await self._db.execute(
            text("SELECT name FROM restaurants WHERE id = :tid"),
            {"tid": str(tenant_id)},
        )
        result = row.first()
        return result[0] if result else None

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    async def _resolve_owned(self, order_id: uuid.UUID) -> Order:
        if order_id in self._owned_cache:
            return self._owned_cache[order_id]

        result = await self._db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if order is None or order.guest_id is None:
            raise HTTPException(status_code=404, detail="Order not found")

        check = await self._db.execute(
            text("""
                SELECT 1 FROM guests
                WHERE id = :guest_id
                  AND guest_profile_id = :guest_profile_id
                """),
            {
                "guest_id": str(order.guest_id),
                "guest_profile_id": str(self._guest.id),
            },
        )
        if check.first() is None:
            # 404 (not 403) hides the existence of foreign orders.
            raise HTTPException(status_code=404, detail="Order not found")

        self._owned_cache[order_id] = order
        return order
