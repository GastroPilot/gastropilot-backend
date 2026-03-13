"""Kitchen course management endpoints."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_or_device, get_db
from app.models.order import Order, OrderItem
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
    for item in course_items:
        if item.status == "pending":
            item.status = "sent"
            updated.append(str(item.id))

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

    return {
        "order_id": str(order_id),
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
    valid_statuses = [
        "pending",
        "sent",
        "in_preparation",
        "ready",
        "served",
        "canceled",
    ]
    if body.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: {body.status}",
        )

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

    item.status = body.status
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
                    "status": body.status,
                },
            },
        )

    return {
        "order_id": str(order_id),
        "item_id": str(item_id),
        "status": body.status,
    }
