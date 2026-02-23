from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_current_user, get_db
from app.models.order import Order
from app.websocket.manager import manager

router = APIRouter(prefix="/kitchen", tags=["kitchen"])


@router.get("/queue")
async def get_kitchen_queue(
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await session.execute(
        select(Order)
        .where(Order.status.in_(["sent_to_kitchen", "in_preparation"]))
        .order_by(Order.opened_at.asc())
    )
    orders = result.scalars().all()
    return [
        {
            "id": str(o.id),
            "order_number": o.order_number,
            "status": o.status,
            "table_id": str(o.table_id) if o.table_id else None,
            "opened_at": o.opened_at.isoformat() if o.opened_at else None,
        }
        for o in orders
    ]


@router.patch("/{order_id}/ready")
async def mark_order_ready(
    order_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    order.status = "ready"
    await session.commit()

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        await manager.broadcast_to_tenant(
            str(tenant_id),
            {"type": "order_ready", "data": {"id": str(order_id), "status": "ready"}},
        )

    return {"id": str(order_id), "status": "ready"}
