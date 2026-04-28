"""Public Guest-JWT-Endpunkte rund um Live Activities und Order-Detailansicht.

Diese Endpunkte sind unter ``/public/...`` registriert (Auth-Middleware
überspringt sie laut ``packages/shared/tenant.py`` daher anhand des Pfads),
prüfen aber selbst einen Guest-JWT mit ``role='guest'``.

Routen:

    PUT    /public/orders/{order_id}/live-activity-token              – upsert push token
    DELETE /public/orders/{order_id}/live-activity-token/{push_token} – soft-end activity
    GET    /public/me/orders/{order_id}                    – eigener Order-Detail
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.guest_deps import GuestIdentity, get_current_guest, get_guest_db
from app.models.live_activity_token import LiveActivityToken
from app.models.order import Order, OrderItem

router = APIRouter(prefix="/public", tags=["public-guest-orders"])


class LiveActivityTokenBody(BaseModel):
    push_token: str = Field(min_length=8, max_length=256)


async def _resolve_guest_owned_order(
    db: AsyncSession,
    guest: GuestIdentity,
    order_id: uuid.UUID,
) -> Order:
    """Lädt eine Order und stellt sicher, dass sie dem Guest gehört.

    "Eigene Order" wird über ``orders.guest_id`` gemappt:
    ``orders.guest_id`` zeigt auf ``guests.id``; ``guests.guest_profile_id``
    zeigt zurück auf das Guest-Profile aus dem JWT (``sub``).
    """
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Falls die Order keinen guest_id hat, kann der Guest sie nicht besitzen.
    if order.guest_id is None:
        raise HTTPException(status_code=404, detail="Order not found")

    # Auflösung guest_id -> guest_profile_id über die guests-Tabelle.
    own_guest = await db.execute(
        text(
            "SELECT 1 FROM guests " "WHERE id = :guest_id AND guest_profile_id = :guest_profile_id"
        ),
        {"guest_id": str(order.guest_id), "guest_profile_id": str(guest.id)},
    )
    if own_guest.first() is None:
        # Bewusst 404 statt 403, um die Existenz fremder Orders zu verschleiern.
        raise HTTPException(status_code=404, detail="Order not found")

    return order


@router.put(
    "/orders/{order_id}/live-activity-token",
    status_code=204,
    response_class=Response,
)
async def register_live_activity_token(
    order_id: uuid.UUID,
    body: LiveActivityTokenBody,
    guest: GuestIdentity = Depends(get_current_guest),
    db: AsyncSession = Depends(get_guest_db),
) -> Response:
    """Upsert eines Live-Activity-Push-Tokens für eine Order.

    Idempotent: Wird derselbe ``(order_id, push_token)`` erneut gesendet,
    bleibt die Zeile aktiv (``ended_at = NULL``) und ``started_at`` bleibt.
    """
    order = await _resolve_guest_owned_order(db, guest, order_id)

    stmt = (
        pg_insert(LiveActivityToken)
        .values(
            tenant_id=order.tenant_id,
            order_id=order.id,
            push_token=body.push_token,
        )
        .on_conflict_do_update(
            constraint="uq_lat_order_token",
            set_={"ended_at": None},
        )
    )
    await db.execute(stmt)
    await db.commit()
    return Response(status_code=204)


@router.delete(
    "/orders/{order_id}/live-activity-token/{push_token}",
    status_code=204,
    response_class=Response,
)
async def end_live_activity_token(
    order_id: uuid.UUID,
    push_token: str,
    guest: GuestIdentity = Depends(get_current_guest),
    db: AsyncSession = Depends(get_guest_db),
) -> Response:
    """Beendet die Live Activity (soft delete) für ein konkretes Token.

    Token wird als Pfad-Parameter erwartet, nicht im Body — DELETE-Bodies
    werden von einigen Reverse-Proxies (Cloudflare u.a.) verworfen, was
    zu stillen Token-Lecks führen würde.
    """
    order = await _resolve_guest_owned_order(db, guest, order_id)

    result = await db.execute(
        select(LiveActivityToken).where(
            LiveActivityToken.order_id == order.id,
            LiveActivityToken.push_token == push_token,
        )
    )
    token_row = result.scalar_one_or_none()
    if token_row is None:
        # Idempotent – auch ohne Treffer 204.
        return Response(status_code=204)

    if token_row.ended_at is None:
        token_row.ended_at = datetime.now(UTC)
        await db.commit()

    return Response(status_code=204)


@router.get("/me/orders/{order_id}")
async def get_my_order(
    order_id: uuid.UUID,
    guest: GuestIdentity = Depends(get_current_guest),
    db: AsyncSession = Depends(get_guest_db),
) -> dict:
    """Order-Detailansicht für den authentifizierten Guest."""
    order = await _resolve_guest_owned_order(db, guest, order_id)

    items_result = await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    items = items_result.scalars().all()

    restaurant_row = await db.execute(
        text("SELECT name FROM restaurants WHERE id = :tid"),
        {"tid": str(order.tenant_id)},
    )
    restaurant_name_row = restaurant_row.first()
    restaurant_name = restaurant_name_row[0] if restaurant_name_row else None

    eta_minutes: int | None = None
    if order.status in ("sent_to_kitchen", "in_preparation") and order.opened_at:
        # Sehr grobe Heuristik – die echte ETA-Logik kommt vom AI-Service.
        eta_minutes = 15

    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "status": order.status,
        "eta_minutes": eta_minutes,
        "restaurant_name": restaurant_name,
        "tenant_id": str(order.tenant_id),
        "subtotal": order.subtotal,
        "tax_amount": order.tax_amount,
        "tip_amount": order.tip_amount,
        "total": order.total,
        "payment_status": order.payment_status,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        "items": [
            {
                "id": str(item.id),
                "name": item.item_name,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total_price": item.total_price,
                "status": item.status,
                "notes": item.notes,
            }
            for item in items
        ],
    }
