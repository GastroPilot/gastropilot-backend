from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem, OrderStatus
from app.services.cache_service import cache_order_status, invalidate_order_cache
from app.services.event_publisher import order_status_changed

logger = logging.getLogger(__name__)

# Erlaubte Status-Übergänge
VALID_TRANSITIONS: dict[str, list[str]] = {
    OrderStatus.PENDING: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
    OrderStatus.CONFIRMED: [OrderStatus.SENT_TO_KITCHEN, OrderStatus.CANCELLED],
    OrderStatus.SENT_TO_KITCHEN: [OrderStatus.IN_PREPARATION, OrderStatus.CANCELLED],
    OrderStatus.IN_PREPARATION: [OrderStatus.READY, OrderStatus.CANCELLED],
    OrderStatus.READY: [OrderStatus.SERVED, OrderStatus.CANCELLED],
    OrderStatus.SERVED: [OrderStatus.COMPLETED],
    OrderStatus.COMPLETED: [],
    OrderStatus.CANCELLED: [],
}


async def transition_order_status(
    session: AsyncSession,
    order: Order,
    new_status: str,
    tenant_id: UUID,
) -> Order:
    """
    Führt einen Status-Übergang durch und validiert dabei die erlaubten Übergänge.
    Publiziert ein Redis-Event und aktualisiert den Cache.
    """
    allowed = VALID_TRANSITIONS.get(order.status, [])
    if new_status not in allowed:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=f"Übergang von '{order.status}' nach '{new_status}' nicht erlaubt. "
            f"Erlaubt: {allowed}",
        )

    old_status = order.status
    order.status = new_status
    await session.flush()

    # Cache aktualisieren
    await cache_order_status(order.id, tenant_id, new_status)

    # Event publizieren (fire-and-forget)
    try:
        await order_status_changed(order.id, tenant_id, old_status, new_status)
    except Exception as exc:
        logger.warning("Event-Publizierung fehlgeschlagen: %s", exc)

    return order


async def calculate_order_total(items: list[OrderItem]) -> float:
    """Berechnet die Gesamtsumme einer Bestellung."""
    return sum(item.price * item.quantity for item in items)
