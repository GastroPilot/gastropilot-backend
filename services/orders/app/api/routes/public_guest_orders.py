"""Public Guest-JWT-Endpunkte rund um Live Activities und Order-Detailansicht.

Auth-Pfad
---------
Diese Endpunkte sind unter ``/public/...`` registriert. Die Tenant-Middleware
in ``packages/shared/tenant.py`` läuft trotzdem über sie hinweg, gibt aber
keine ``tenant_id`` zwingend vor; sie setzt ``request.state.tenant_id = None``,
wenn weder ein Tenant-JWT noch ein Subdomain-Hint gefunden wird. Der
Guest-JWT mit ``role='guest'`` wird hier in der Route selbst per
``get_current_guest`` validiert.

Daten-Zugriff
-------------
Der DB-Pool, den der Guest-Service nutzt (``session_factory_admin``), umgeht
RLS — Guests haben keine ``tenant_id`` und würden sonst nichts sehen. Damit
ist die einzige Schutzschicht der manuelle Filter auf ``guest_profile_id``.
Der Filter ist in ``GuestOrdersRepository`` zentralisiert; jede Route
arbeitet ausschließlich gegen das Repo, nicht direkt gegen die Session.

Routen:

    PUT    /public/orders/{order_id}/live-activity-token              – upsert push token
    DELETE /public/orders/{order_id}/live-activity-token/{push_token} – soft-end activity
    GET    /public/me/orders/{order_id}                               – eigener Order-Detail
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.guest_deps import GuestIdentity, get_current_guest, get_guest_db
from app.core.guest_repository import GuestOrdersRepository

router = APIRouter(prefix="/public", tags=["public-guest-orders"])


class LiveActivityTokenBody(BaseModel):
    push_token: str = Field(min_length=8, max_length=256)


def get_guest_orders_repo(
    guest: GuestIdentity = Depends(get_current_guest),
    db: AsyncSession = Depends(get_guest_db),
) -> GuestOrdersRepository:
    """FastAPI dependency that constructs the repository per request."""
    return GuestOrdersRepository(db=db, guest=guest)


@router.put(
    "/orders/{order_id}/live-activity-token",
    status_code=204,
    response_class=Response,
)
async def register_live_activity_token(
    order_id: uuid.UUID,
    body: LiveActivityTokenBody,
    repo: GuestOrdersRepository = Depends(get_guest_orders_repo),
) -> Response:
    """Upsert eines Live-Activity-Push-Tokens für eine Order."""
    await repo.upsert_live_activity_token(order_id, body.push_token)
    return Response(status_code=204)


@router.delete(
    "/orders/{order_id}/live-activity-token/{push_token}",
    status_code=204,
    response_class=Response,
)
async def end_live_activity_token(
    order_id: uuid.UUID,
    push_token: str,
    repo: GuestOrdersRepository = Depends(get_guest_orders_repo),
) -> Response:
    """Beendet die Live Activity (soft delete) für ein konkretes Token.

    Token wird als Pfad-Parameter erwartet, nicht im Body — DELETE-Bodies
    werden von einigen Reverse-Proxies (Cloudflare u.a.) verworfen, was
    zu stillen Token-Lecks führen würde.
    """
    await repo.end_live_activity_token(order_id, push_token)
    return Response(status_code=204)


@router.get("/me/orders/{order_id}")
async def get_my_order(
    order_id: uuid.UUID,
    repo: GuestOrdersRepository = Depends(get_guest_orders_repo),
) -> dict:
    """Order-Detailansicht für den authentifizierten Guest."""
    order = await repo.get_owned_order(order_id)
    items = await repo.list_order_items(order_id)
    restaurant_name = await repo.get_restaurant_name(order.tenant_id)

    eta_minutes: int | None = None
    if order.status in ("sent_to_kitchen", "in_preparation") and order.opened_at:
        # Sehr grobe Heuristik – die echte ETA-Logik kommt vom AI-Service.
        # Tracked als BE-4 in #40.
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
