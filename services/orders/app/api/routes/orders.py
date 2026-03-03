from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models.order import Order, OrderItem
from app.websocket.manager import manager

router = APIRouter(prefix="/orders", tags=["orders"])

ORDER_STATUSES = [
    "open",
    "sent_to_kitchen",
    "in_preparation",
    "ready",
    "served",
    "paid",
    "canceled",
]


class OrderCreate(BaseModel):
    table_id: uuid.UUID | None = None
    guest_id: uuid.UUID | None = None
    reservation_id: uuid.UUID | None = None
    party_size: int | None = None
    notes: str | None = None
    items: list[dict] = []


class OrderUpdate(BaseModel):
    status: str | None = None
    table_id: uuid.UUID | None = None
    guest_id: uuid.UUID | None = None
    reservation_id: uuid.UUID | None = None
    party_size: int | None = None
    discount_amount: float | None = None
    discount_percentage: float | None = None
    tip_amount: float | None = None
    payment_method: str | None = None
    payment_status: str | None = None
    split_payments: dict | list | None = None
    notes: str | None = None
    special_requests: str | None = None
    closed_at: str | None = None
    paid_at: str | None = None


class OrderStatusUpdate(BaseModel):
    status: str


@router.get("/")
async def list_orders(
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    status: str | None = None,
):
    query = select(Order)
    if status:
        query = query.where(Order.status == status)
    result = await session.execute(query.order_by(Order.opened_at.desc()))
    orders = result.scalars().all()
    return [
        {
            "id": str(o.id),
            "order_number": o.order_number,
            "status": o.status,
            "table_id": str(o.table_id) if o.table_id else None,
            "total": o.total,
            "payment_status": o.payment_status,
            "opened_at": o.opened_at.isoformat() if o.opened_at else None,
        }
        for o in orders
    ]


@router.post("/", status_code=201)
async def create_order(
    data: OrderCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")

    order_number = f"ORD-{secrets.token_hex(4).upper()}"
    order = Order(
        tenant_id=tenant_id,
        table_id=data.table_id,
        reservation_id=data.reservation_id,
        party_size=data.party_size,
        notes=data.notes,
        order_number=order_number,
        created_by_user_id=current_user.id,
    )
    session.add(order)
    await session.flush()

    # Resolve menu item allergens in bulk
    menu_item_ids = [
        item_data.get("menu_item_id")
        for item_data in data.items
        if item_data.get("menu_item_id")
    ]
    allergens_map: dict[str, list] = {}
    if menu_item_ids:
        rows = await session.execute(
            text("SELECT id, allergens FROM menu_items WHERE id = ANY(:ids)"),
            {"ids": menu_item_ids},
        )
        for row in rows:
            allergens_map[str(row.id)] = row.allergens or []

    # Resolve guest allergen profile if guest_id is set
    guest_allergens: list[str] = []
    if data.guest_id:
        gp_row = await session.execute(
            text(
                "SELECT gp.allergen_profile FROM guest_profiles gp "
                "JOIN guests g ON g.guest_profile_id = gp.id "
                "WHERE g.id = :guest_id"
            ),
            {"guest_id": data.guest_id},
        )
        gp = gp_row.first()
        if gp and gp.allergen_profile:
            guest_allergens = gp.allergen_profile
    if guest_allergens:
        order.guest_allergens = guest_allergens

    for item_data in data.items:
        qty = item_data.get("quantity", 1)
        price = item_data.get("unit_price", 0.0)
        mid = item_data.get("menu_item_id")
        item_allergens = allergens_map.get(str(mid), []) if mid else []
        item = OrderItem(
            order_id=order.id,
            item_name=item_data.get("item_name", "Unknown"),
            quantity=qty,
            unit_price=price,
            total_price=qty * price,
            tax_rate=item_data.get("tax_rate", 0.19),
            notes=item_data.get("notes"),
            menu_item_id=mid,
            allergens=item_allergens,
        )
        session.add(item)

    await session.commit()
    await session.refresh(order)

    await manager.broadcast_to_tenant(
        str(tenant_id),
        {
            "type": "order_created",
            "data": {"id": str(order.id), "order_number": order.order_number},
        },
    )

    return {"id": str(order.id), "order_number": order.order_number, "status": order.status}


@router.get("/{order_id}")
async def get_order(
    order_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    items_result = await session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
    items = items_result.scalars().all()

    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "status": order.status,
        "table_id": str(order.table_id) if order.table_id else None,
        "subtotal": order.subtotal,
        "tax_amount": order.tax_amount,
        "total": order.total,
        "payment_status": order.payment_status,
        "opened_at": order.opened_at.isoformat() if order.opened_at else None,
        "items": [
            {
                "id": str(i.id),
                "item_name": i.item_name,
                "quantity": i.quantity,
                "unit_price": i.unit_price,
                "total_price": i.total_price,
                "status": i.status,
                "notes": i.notes,
            }
            for i in items
        ],
    }


@router.patch("/{order_id}/status")
async def update_order_status(
    order_id: uuid.UUID,
    data: OrderStatusUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if data.status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {data.status}")

    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    order.status = data.status
    await session.commit()

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        await manager.broadcast_to_tenant(
            str(tenant_id),
            {"type": "order_updated", "data": {"id": str(order_id), "status": data.status}},
        )

    return {"id": str(order_id), "status": data.status}


@router.patch("/{order_id}")
async def update_order(
    order_id: uuid.UUID,
    data: OrderUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    from datetime import datetime as dt

    valid_fields = {c.key for c in Order.__table__.columns} - {
        "id", "tenant_id", "created_at", "updated_at", "opened_at",
    }
    update_data = data.model_dump(exclude_unset=True)

    if "status" in update_data and update_data["status"]:
        if update_data["status"] not in ORDER_STATUSES:
            raise HTTPException(
                status_code=400, detail=f"Invalid status: {update_data['status']}"
            )

    # Parse datetime strings to datetime objects
    for date_field in ("paid_at", "closed_at"):
        if date_field in update_data and isinstance(update_data[date_field], str):
            update_data[date_field] = dt.fromisoformat(
                update_data[date_field].replace("Z", "+00:00")
            )

    for key, value in update_data.items():
        if key in valid_fields:
            setattr(order, key, value)

    # Recalculate total
    subtotal = order.subtotal or 0.0
    discount = order.discount_amount or 0.0
    tip = order.tip_amount or 0.0
    order.total = subtotal - discount + tip

    await session.commit()
    await session.refresh(order)

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        await manager.broadcast_to_tenant(
            str(tenant_id),
            {"type": "order_updated", "data": {"id": str(order_id)}},
        )

    return {
        "id": str(order.id),
        "status": order.status,
        "total": order.total,
        "payment_status": order.payment_status,
    }
