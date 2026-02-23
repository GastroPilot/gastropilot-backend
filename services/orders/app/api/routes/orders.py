from __future__ import annotations
import secrets
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_current_user, get_db
from app.models.order import Order, OrderItem
from app.websocket.manager import manager

router = APIRouter(prefix="/orders", tags=["orders"])

ORDER_STATUSES = ["open", "sent_to_kitchen", "in_preparation", "ready", "served", "paid", "canceled"]


class OrderCreate(BaseModel):
    table_id: uuid.UUID | None = None
    reservation_id: uuid.UUID | None = None
    party_size: int | None = None
    notes: str | None = None
    items: list[dict] = []


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

    for item_data in data.items:
        qty = item_data.get("quantity", 1)
        price = item_data.get("unit_price", 0.0)
        item = OrderItem(
            order_id=order.id,
            item_name=item_data.get("item_name", "Unknown"),
            quantity=qty,
            unit_price=price,
            total_price=qty * price,
            tax_rate=item_data.get("tax_rate", 0.19),
            notes=item_data.get("notes"),
            menu_item_id=item_data.get("menu_item_id"),
        )
        session.add(item)

    await session.commit()
    await session.refresh(order)

    await manager.broadcast_to_tenant(
        str(tenant_id),
        {"type": "order_created", "data": {"id": str(order.id), "order_number": order.order_number}},
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
