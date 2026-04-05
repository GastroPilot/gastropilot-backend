"""Kitchen course management endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_or_device, get_db
from app.models.order import Order, OrderItem
from app.services.order_item_status import (
    ORDER_ITEM_STATUSES,
    can_transition_order_item_status,
    get_allowed_next_order_item_statuses,
    normalize_order_item_status,
)
from app.services.order_progress import sync_order_status_with_items
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kitchen", tags=["kitchen-courses"])


class ItemStatusUpdate(BaseModel):
    status: str


@router.get("/{order_id}/courses")
async def get_order_courses(
    order_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_or_device),
):
    """Get course breakdown for an order."""
    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    items_result = await session.execute(
        select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.sort_order)
    )
    items = items_result.scalars().all()

    # Group items by course
    courses: dict[int, list] = {}
    for item in items:
        course_num = getattr(item, "course", 1) or 1
        if course_num not in courses:
            courses[course_num] = []
        courses[course_num].append(
            {
                "id": str(item.id),
                "name": item.item_name,
                "quantity": item.quantity,
                "status": item.status,
            }
        )

    return {
        "order_id": str(order_id),
        "order_status": order.status,
        "courses": [
            {"course_number": num, "items": course_items}
            for num, course_items in sorted(courses.items())
        ],
    }


@router.patch("/{order_id}/release-course/{course_number}")
async def release_course(
    order_id: uuid.UUID,
    course_number: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_or_device),
):
    """Release next course for an order.

    Sets all items in the specified course to
    'sent' status.
    """
    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    items_result = await session.execute(
        select(OrderItem).where(
            and_(
                OrderItem.order_id == order_id,
            )
        )
    )
    items = items_result.scalars().all()

    # Filter items for the specified course
    course_items = [i for i in items if (getattr(i, "course", 1) or 1) == course_number]

    if not course_items:
        raise HTTPException(
            status_code=404,
            detail=(f"No items found for course {course_number}"),
        )

    updated = []
    previous_order_status = order.status
    for item in course_items:
        if can_transition_order_item_status(item.status, "sent"):
            item.status = "sent"
            if item.sent_to_kitchen_at is None:
                item.sent_to_kitchen_at = datetime.now(UTC)
            updated.append(str(item.id))

    sync_order_status_with_items(order, items)

    await session.commit()

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        await manager.broadcast_to_tenant(
            str(tenant_id),
            {
                "type": "course_released",
                "data": {
                    "order_id": str(order_id),
                    "course_number": course_number,
                    "items_updated": updated,
                },
            },
        )
        if order.status != previous_order_status:
            await manager.broadcast_to_tenant(
                str(tenant_id),
                {"type": "order_updated", "data": {"id": str(order_id)}},
            )

    return {
        "order_id": str(order_id),
        "order_status": order.status,
        "course_number": course_number,
        "items_updated": len(updated),
    }


@router.patch("/orders/{order_id}/items/{item_id}/status")
async def update_item_status(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ItemStatusUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_or_device),
):
    """Update individual item status."""
    normalized_next_status = normalize_order_item_status(body.status)
    if normalized_next_status not in ORDER_ITEM_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: {body.status}",
        )

    order_result = await session.execute(
        select(Order).where(Order.id == order_id).with_for_update()
    )
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    result = await session.execute(
        select(OrderItem).where(
            and_(
                OrderItem.id == item_id,
                OrderItem.order_id == order_id,
            )
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Order item not found")

    if not can_transition_order_item_status(item.status, normalized_next_status):
        allowed = get_allowed_next_order_item_statuses(item.status)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid item status transition: {item.status} -> {normalized_next_status}. "
                f"Allowed next statuses: {allowed}"
            ),
        )

    item.status = normalized_next_status
    if normalized_next_status == "sent" and item.sent_to_kitchen_at is None:
        item.sent_to_kitchen_at = datetime.now(UTC)

    previous_order_status = order.status
    items_result = await session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
    order_items = items_result.scalars().all()
    sync_order_status_with_items(order, order_items)

    await session.commit()

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        await manager.broadcast_to_tenant(
            str(tenant_id),
            {
                "type": "item_status_updated",
                "data": {
                    "order_id": str(order_id),
                    "item_id": str(item_id),
                    "status": normalized_next_status,
                },
            },
        )
        if order.status != previous_order_status:
            await manager.broadcast_to_tenant(
                str(tenant_id),
                {"type": "order_updated", "data": {"id": str(order_id)}},
            )

    return {
        "order_id": str(order_id),
        "order_status": order.status,
        "item_id": str(item_id),
        "status": normalized_next_status,
    }
