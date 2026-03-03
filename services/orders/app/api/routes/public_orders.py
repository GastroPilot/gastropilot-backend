"""Public order endpoints for guest self-ordering via QR codes."""

from __future__ import annotations

import asyncio
import logging
import secrets
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.order import Order, OrderItem
from app.schemas.public_order import (
    PublicMenuCategoryResponse,
    PublicMenuItemResponse,
    PublicMenuResponse,
    PublicOrderCreateRequest,
    PublicOrderItemResponse,
    PublicOrderResponse,
    PublicOrderStatusResponse,
    PublicPaymentRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/public/order", tags=["public-orders"]
)

# Map internal order statuses to guest-facing statuses
_ORDER_STATUS_MAP = {
    "open": "ordered",
    "sent_to_kitchen": "preparing",
    "in_preparation": "preparing",
    "ready": "ready",
    "served": "served",
    "paid": "served",
    "canceled": "cancelled",
}

_ITEM_STATUS_MAP = {
    "pending": "ordered",
    "sent": "preparing",
    "in_preparation": "preparing",
    "ready": "ready",
    "served": "served",
    "canceled": "cancelled",
}


def _public_order_status(status: str) -> str:
    return _ORDER_STATUS_MAP.get(status, status)


def _public_item_status(status: str) -> str:
    return _ITEM_STATUS_MAP.get(status, status)


async def _validate_table_token(
    slug: str, token: str, db: AsyncSession
) -> tuple:
    """Validate table token and return restaurant + table info.

    Since the orders service does not have direct access to
    the core service models, we query the shared database
    tables directly.
    """
    from sqlalchemy import text

    # Query restaurant by slug
    result = await db.execute(
        text(
            "SELECT id, name FROM restaurants "
            "WHERE slug = :slug "
            "AND public_booking_enabled = true"
        ),
        {"slug": slug},
    )
    restaurant = result.first()
    if not restaurant:
        raise HTTPException(
            status_code=404,
            detail="Restaurant not found",
        )

    # Query table by token
    table_result = await db.execute(
        text(
            "SELECT id, number, tenant_id FROM tables "
            "WHERE table_token = :token "
            "AND tenant_id = :tenant_id"
        ),
        {
            "token": token,
            "tenant_id": str(restaurant[0]),
        },
    )
    table = table_result.first()
    if not table:
        raise HTTPException(
            status_code=404,
            detail="Invalid table token",
        )

    return restaurant, table


@router.get("/{slug}/table/{token}/menu")
async def get_table_menu(
    slug: str,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Get menu for a table (validates token).

    Returns restaurant menu with allergen information.
    """
    from sqlalchemy import text

    restaurant, table = await _validate_table_token(
        slug, token, db
    )

    # Get menu categories and items
    cats = await db.execute(
        text(
            "SELECT id, name, description "
            "FROM menu_categories "
            "WHERE tenant_id = :tid AND is_active = true "
            "ORDER BY sort_order"
        ),
        {"tid": str(restaurant[0])},
    )
    categories = cats.fetchall()

    menu_categories = []
    for cat in categories:
        items_result = await db.execute(
            text(
                "SELECT id, name, description, price, "
                "allergens, modifiers "
                "FROM menu_items "
                "WHERE category_id = :cid "
                "AND is_available = true "
                "ORDER BY sort_order"
            ),
            {"cid": str(cat[0])},
        )
        items = items_result.fetchall()

        menu_categories.append(
            {
                "id": str(cat[0]),
                "name": cat[1],
                "description": cat[2],
                "items": [
                    {
                        "id": str(item[0]),
                        "name": item[1],
                        "description": item[2],
                        "price": item[3],
                        "allergens": item[4] or [],
                        "modifiers": item[5],
                    }
                    for item in items
                ],
            }
        )

    return {
        "restaurant": restaurant[1],
        "table_number": table[1],
        "categories": menu_categories,
    }


@router.post(
    "/{slug}/table/{token}/orders",
    status_code=201,
)
async def create_public_order(
    slug: str,
    token: str,
    body: PublicOrderCreateRequest,
    response: Response,
    session_id: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Create an order from the public menu.

    Generates a session_id cookie for tracking.
    """
    from sqlalchemy import text

    restaurant, table = await _validate_table_token(
        slug, token, db
    )

    # Generate or reuse session ID
    if not session_id:
        session_id = secrets.token_urlsafe(16)

    order_number = (
        f"PUB-{secrets.token_hex(4).upper()}"
    )

    order = Order(
        tenant_id=restaurant[0],
        table_id=table[0],
        order_number=order_number,
        status="open",
        special_requests=session_id,
    )
    db.add(order)
    await db.flush()

    total = 0.0
    order_items = []

    for item_req in body.items:
        # Look up menu item for price
        mi_result = await db.execute(
            text(
                "SELECT name, price, tax_rate "
                "FROM menu_items WHERE id = :id"
            ),
            {"id": str(item_req.menu_item_id)},
        )
        mi = mi_result.first()
        if not mi:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Menu item {item_req.menu_item_id}"
                    f" not found"
                ),
            )

        item_total = mi[1] * item_req.quantity
        total += item_total

        oi = OrderItem(
            order_id=order.id,
            menu_item_id=item_req.menu_item_id,
            item_name=mi[0],
            quantity=item_req.quantity,
            unit_price=mi[1],
            total_price=item_total,
            tax_rate=mi[2] if mi[2] else 0.19,
            notes=item_req.special_instructions,
        )
        db.add(oi)
        order_items.append(oi)

    order.subtotal = total
    order.total = total
    await db.commit()
    await db.refresh(order)

    # Set session cookie
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=86400,
    )

    return {
        "id": str(order.id),
        "session_id": session_id,
        "order_number": order.order_number,
        "status": _public_order_status(order.status),
        "total": order.total,
        "created_at": (
            order.created_at.isoformat() if order.created_at else None
        ),
        "items": [
            {
                "id": str(oi.id),
                "name": oi.item_name,
                "quantity": oi.quantity,
                "unit_price": oi.unit_price,
                "total_price": oi.total_price,
                "status": _public_item_status(oi.status),
            }
            for oi in order_items
        ],
    }


@router.get(
    "/{slug}/table/{token}/orders/{session}",
)
async def get_public_order_status(
    slug: str,
    token: str,
    session: str,
    db: AsyncSession = Depends(get_db),
):
    """Get order status for a session."""
    restaurant, table = await _validate_table_token(
        slug, token, db
    )

    result = await db.execute(
        select(Order).where(
            and_(
                Order.tenant_id == restaurant[0],
                Order.table_id == table[0],
                Order.special_requests == session,
            )
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=404, detail="Order not found"
        )

    items_result = await db.execute(
        select(OrderItem).where(
            OrderItem.order_id == order.id
        )
    )
    items = items_result.scalars().all()

    return {
        "id": str(order.id),
        "session_id": session,
        "status": _public_order_status(order.status),
        "items": [
            {
                "id": str(i.id),
                "name": i.item_name,
                "quantity": i.quantity,
                "unit_price": i.unit_price,
                "total_price": i.total_price,
                "status": _public_item_status(i.status),
            }
            for i in items
        ],
        "total": order.total,
        "created_at": (
            order.created_at.isoformat()
            if order.created_at
            else None
        ),
        "updated_at": (
            order.updated_at.isoformat()
            if order.updated_at
            else None
        ),
    }


@router.post(
    "/{slug}/table/{token}/orders/{session}/pay",
)
async def initiate_payment(
    slug: str,
    token: str,
    session: str,
    body: PublicPaymentRequest,
    db: AsyncSession = Depends(get_db),
):
    """Initiate payment for a public order."""
    restaurant, table = await _validate_table_token(
        slug, token, db
    )

    result = await db.execute(
        select(Order).where(
            and_(
                Order.tenant_id == restaurant[0],
                Order.table_id == table[0],
                Order.special_requests == session,
            )
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=404, detail="Order not found"
        )

    if order.payment_status == "paid":
        raise HTTPException(
            status_code=400,
            detail="Order already paid",
        )

    order.payment_method = body.method
    order.tip_amount = body.tip_amount
    order.total = order.subtotal + body.tip_amount

    from app.core.config import settings

    if settings.STRIPE_SECRET_KEY and body.method == "card":
        import stripe

        stripe.api_key = settings.STRIPE_SECRET_KEY
        amount_cents = int(round(order.total * 100))
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="eur",
            metadata={
                "order_id": str(order.id),
                "tenant_id": str(order.tenant_id),
            },
        )
        order.payment_status = "pending"
        await db.commit()
        return {
            "id": str(order.id),
            "payment_status": order.payment_status,
            "total": order.total,
            "tip_amount": order.tip_amount,
            "client_secret": intent.client_secret,
            "message": "Payment intent created",
        }

    order.payment_status = "partial"
    await db.commit()

    return {
        "id": str(order.id),
        "payment_status": order.payment_status,
        "total": order.total,
        "tip_amount": order.tip_amount,
        "message": "Payment initiated",
    }


@router.get(
    "/{slug}/table/{token}/orders/{session}/stream",
)
async def order_status_stream(
    slug: str,
    token: str,
    session: str,
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint for live order status updates."""
    restaurant, table = await _validate_table_token(
        slug, token, db
    )

    async def event_generator():
        """Generate SSE events for order status."""
        while True:
            try:
                from app.core.database import (
                    get_session_factories,
                )

                factory, _ = get_session_factories()
                async with factory() as sess:
                    result = await sess.execute(
                        select(Order).where(
                            and_(
                                Order.tenant_id
                                == restaurant[0],
                                Order.table_id == table[0],
                                Order.special_requests
                                == session,
                            )
                        )
                    )
                    order = result.scalar_one_or_none()

                    if not order:
                        yield (
                            "data: "
                            '{"status": "not_found"}\n\n'
                        )
                        break

                    items_res = await sess.execute(
                        select(OrderItem).where(
                            OrderItem.order_id == order.id
                        )
                    )
                    items = items_res.scalars().all()

                    yield (
                        f'data: {{"status":'
                        f' "{order.status}",'
                        f' "payment_status":'
                        f' "{order.payment_status}",'
                        f' "items": ['
                        + ",".join(
                            f'{{"name":'
                            f' "{i.item_name}",'
                            f' "status":'
                            f' "{i.status}"}}'
                            for i in items
                        )
                        + "]}}\n\n"
                    )

                    if order.status in (
                        "paid",
                        "canceled",
                    ):
                        break

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(
                    "Error in order SSE stream"
                )
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
