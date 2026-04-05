from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_or_device, get_db
from app.models.order import Order, OrderItem
from app.services.order_timing import apply_order_status_timestamps
from app.websocket.manager import manager

router = APIRouter(prefix="/kitchen", tags=["kitchen"])
KITCHEN_ACTIVE_ITEM_STATUSES = ("sent", "in_preparation", "ready")


@router.get("/queue")
async def get_kitchen_queue(
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_or_device),
):
    # Kitchen queue is item-driven: only already sent/active kitchen items are relevant.
    item_result = await session.execute(
        select(OrderItem)
        .where(OrderItem.status.in_(KITCHEN_ACTIVE_ITEM_STATUSES))
        .order_by(
            OrderItem.sent_to_kitchen_at.asc(),
            OrderItem.kitchen_ticket_no.asc(),
            OrderItem.sort_order.asc(),
            OrderItem.created_at.asc(),
        )
    )
    active_items = item_result.scalars().all()

    if not active_items:
        return []

    order_ids = sorted({item.order_id for item in active_items}, key=str)
    result = await session.execute(
        select(Order)
        .where(Order.id.in_(order_ids), Order.status.notin_(["paid", "canceled"]))
        .order_by(Order.opened_at.asc())
    )
    orders = result.scalars().all()

    if not orders:
        return []

    order_ids_set = {order.id for order in orders}

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

    items_by_order: dict[str, list[dict]] = defaultdict(list)
    tickets_by_order: dict[str, dict[int | None, list[dict]]] = defaultdict(dict)
    for item in active_items:
        if item.order_id not in order_ids_set:
            continue
        item_payload = {
            "id": str(item.id),
            "item_name": item.item_name,
            "quantity": item.quantity,
            "status": item.status,
            "kitchen_ticket_no": item.kitchen_ticket_no,
            "sent_to_kitchen_at": (
                item.sent_to_kitchen_at.isoformat() if item.sent_to_kitchen_at else None
            ),
            "course": item.course or 1,
            "notes": item.notes,
            "category": item.category,
            "allergens": item.allergens or [],
        }
        order_key = str(item.order_id)
        items_by_order[order_key].append(item_payload)

        ticket_key = item.kitchen_ticket_no
        ticket_map = tickets_by_order[order_key]
        if ticket_key not in ticket_map:
            ticket_map[ticket_key] = []
        ticket_map[ticket_key].append(item_payload)

    return [
        {
            "id": str(o.id),
            "order_number": o.order_number,
            "status": o.status,
            "table_id": str(o.table_id) if o.table_id else None,
            "table_number": table_numbers.get(str(o.table_id), None) if o.table_id else None,
            "items": items_by_order.get(str(o.id), []),
            "tickets": [
                {
                    "kitchen_ticket_no": ticket_no,
                    "sent_to_kitchen_at": (
                        min(valid_sent_times) if valid_sent_times else None
                    ),
                    "items_count": sum(max(item.get("quantity", 1), 1) for item in ticket_items),
                    "items": ticket_items,
                }
                for ticket_no, ticket_items in sorted(
                    tickets_by_order.get(str(o.id), {}).items(),
                    key=lambda entry: (entry[0] is None, entry[0] or 0),
                )
                for valid_sent_times in [
                    sorted(
                        [
                            item.get("sent_to_kitchen_at")
                            for item in ticket_items
                            if item.get("sent_to_kitchen_at")
                        ]
                    )
                ]
            ],
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
