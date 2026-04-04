from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_or_device, get_db
from app.models.order import Order, OrderItem
from app.services.order_timing import apply_order_status_timestamps
from app.websocket.manager import manager

router = APIRouter(prefix="/kitchen", tags=["kitchen"])


@router.get("/queue")
async def get_kitchen_queue(
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_or_device),
):
    result = await session.execute(
        select(Order)
        .where(Order.status.in_(["sent_to_kitchen", "in_preparation"]))
        .order_by(Order.opened_at.asc())
    )
    orders = result.scalars().all()

    # Resolve table numbers
    table_ids = [o.table_id for o in orders if o.table_id]
    table_numbers: dict[str, str] = {}
    if table_ids:
        from sqlalchemy import text

        rows = await session.execute(
            text("SELECT id, number FROM tables WHERE id = ANY(:ids)"),
            {"ids": table_ids},
        )
        for row in rows:
            table_numbers[str(row.id)] = row.number or str(row.id)

    # Load items for all orders
    order_ids = [o.id for o in orders]
    items_by_order: dict[str, list[dict]] = {str(oid): [] for oid in order_ids}
    if order_ids:
        item_result = await session.execute(
            select(OrderItem)
            .where(OrderItem.order_id.in_(order_ids))
            .order_by(OrderItem.sort_order.asc())
        )
        for item in item_result.scalars().all():
            items_by_order[str(item.order_id)].append(
                {
                    "id": str(item.id),
                    "item_name": item.item_name,
                    "quantity": item.quantity,
                    "status": item.status,
                    "course": item.course or 1,
                    "notes": item.notes,
                    "category": item.category,
                    "allergens": item.allergens or [],
                }
            )

    return [
        {
            "id": str(o.id),
            "order_number": o.order_number,
            "status": o.status,
            "table_id": str(o.table_id) if o.table_id else None,
            "table_number": table_numbers.get(str(o.table_id), None) if o.table_id else None,
            "items": items_by_order.get(str(o.id), []),
            "guest_allergens": o.guest_allergens or [],
            "source": "qr" if (o.order_number or "").startswith("PUB-") else "service",
            "notes": o.notes if not (o.notes or "").startswith("Public order,") else None,
            "opened_at": o.opened_at.isoformat() if o.opened_at else None,
            "sent_to_kitchen_at": (
                o.sent_to_kitchen_at.isoformat() if o.sent_to_kitchen_at else None
            ),
            "in_preparation_at": (o.in_preparation_at.isoformat() if o.in_preparation_at else None),
            "ready_at": o.ready_at.isoformat() if o.ready_at else None,
            "served_at": o.served_at.isoformat() if o.served_at else None,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]


@router.patch("/{order_id}/ready")
async def mark_order_ready(
    order_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_or_device),
):
    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    order.status = "ready"
    apply_order_status_timestamps(order, "ready")
    await session.commit()
    await session.refresh(order)

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        await manager.broadcast_to_tenant(
            str(tenant_id),
            {"type": "order_ready", "data": {"id": str(order_id), "status": "ready"}},
        )

    return {
        "id": str(order.id),
        "status": order.status,
        "ready_at": order.ready_at.isoformat() if order.ready_at else None,
        "served_at": order.served_at.isoformat() if order.served_at else None,
    }
