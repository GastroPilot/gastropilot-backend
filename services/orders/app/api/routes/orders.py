from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models.order import Order, OrderItem
from app.services.table_group_service import normalize_order_table_ids, resolve_group_table_ids
from app.services.tax_service import calculate_totals
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
TABLE_ID_UNSET = object()
RESERVATION_ID_UNSET = object()


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


class OrderItemCreate(BaseModel):
    menu_item_id: uuid.UUID | None = None
    item_name: str
    item_description: str | None = None
    category: str | None = None
    quantity: int = 1
    unit_price: float
    tax_rate: float = 0.19
    notes: str | None = None
    sort_order: int | None = None


class OrderItemUpdate(BaseModel):
    item_name: str | None = None
    item_description: str | None = None
    category: str | None = None
    quantity: int | None = None
    unit_price: float | None = None
    tax_rate: float | None = None
    status: str | None = None
    notes: str | None = None
    sort_order: int | None = None


async def _recalculate_order_totals(order: Order, session: AsyncSession) -> None:
    item_result = await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    items = item_result.scalars().all()
    totals = calculate_totals(
        [{"total_price": i.total_price, "tax_rate": i.tax_rate} for i in items],
        discount_amount=order.discount_amount or 0.0,
        discount_percentage=order.discount_percentage,
        tip_amount=order.tip_amount or 0.0,
    )
    order.subtotal = totals["subtotal"]
    order.tax_amount_7 = totals["tax_amount_7"]
    order.tax_amount_19 = totals["tax_amount_19"]
    order.tax_amount = totals["tax_amount"]
    order.discount_amount = totals["discount_amount"]
    order.tip_amount = totals["tip_amount"]
    order.total = totals["total"]


def _deduplicate_uuid_values(values: list[uuid.UUID]) -> list[uuid.UUID]:
    deduped: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _reference_date_from_datetime(value: datetime | None) -> datetime.date:
    if value and value.tzinfo is not None:
        return value.astimezone(UTC).date()
    if value:
        return value.date()
    return datetime.now(UTC).date()


async def _resolve_order_table_assignment_from_reservation(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    reservation_id: uuid.UUID,
) -> tuple[uuid.UUID | None, list[uuid.UUID]]:
    reservation_result = await session.execute(
        text(
            """
            SELECT id, table_id, start_at
            FROM reservations
            WHERE id = :reservation_id
              AND tenant_id = :tenant_id
            LIMIT 1
            """
        ),
        {"reservation_id": str(reservation_id), "tenant_id": str(tenant_id)},
    )
    reservation_row = reservation_result.first()
    if reservation_row is None:
        raise HTTPException(status_code=404, detail="Reservation not found")

    reservation_table_id = (
        uuid.UUID(str(reservation_row.table_id)) if reservation_row.table_id is not None else None
    )
    reservation_start_at: datetime | None = reservation_row.start_at
    resolved_table_ids: list[uuid.UUID] = []

    if reservation_table_id is not None:
        reference_date = _reference_date_from_datetime(reservation_start_at)
        try:
            resolved_table_ids = await resolve_group_table_ids(
                session,
                tenant_id,
                reservation_table_id,
                reference_date,
            )
        except ValueError:
            resolved_table_ids = [reservation_table_id]
    else:
        reservation_tables_result = await session.execute(
            text(
                """
                SELECT table_id
                FROM reservation_tables
                WHERE tenant_id = :tenant_id
                  AND reservation_id = :reservation_id
                """
            ),
            {"tenant_id": str(tenant_id), "reservation_id": str(reservation_id)},
        )
        resolved_table_ids = [
            uuid.UUID(str(row.table_id))
            for row in reservation_tables_result
            if row.table_id is not None
        ]

    deduped_table_ids = _deduplicate_uuid_values(resolved_table_ids)
    primary_table_id = deduped_table_ids[0] if deduped_table_ids else reservation_table_id
    return primary_table_id, deduped_table_ids


def _serialize_item(item: OrderItem) -> dict:
    return {
        "id": str(item.id),
        "order_id": str(item.order_id),
        "menu_item_id": str(item.menu_item_id) if item.menu_item_id else None,
        "item_name": item.item_name,
        "item_description": item.item_description,
        "category": item.category,
        "quantity": item.quantity,
        "unit_price": item.unit_price,
        "total_price": item.total_price,
        "tax_rate": item.tax_rate,
        "status": item.status,
        "notes": item.notes,
        "sort_order": item.sort_order,
        "created_at_utc": item.created_at.isoformat() if item.created_at else None,
        "updated_at_utc": item.updated_at.isoformat() if item.updated_at else None,
    }


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
            "table_ids": normalize_order_table_ids(o.table_ids, o.table_id),
            "reservation_id": str(o.reservation_id) if o.reservation_id else None,
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

    if data.reservation_id is None:
        raise HTTPException(
            status_code=400,
            detail="Reservation is required for every order",
        )

    resolved_table_id, resolved_table_ids = await _resolve_order_table_assignment_from_reservation(
        session,
        tenant_id,
        data.reservation_id,
    )
    allowed_table_ids = {str(table_id) for table_id in resolved_table_ids}
    if data.table_id is not None and allowed_table_ids and str(data.table_id) not in allowed_table_ids:
        raise HTTPException(
            status_code=400,
            detail="Table does not match reservation assignment",
        )

    order_number = f"ORD-{secrets.token_hex(4).upper()}"
    order = Order(
        tenant_id=tenant_id,
        table_id=resolved_table_id,
        table_ids=(
            [str(table_id) for table_id in resolved_table_ids] if resolved_table_ids else None
        ),
        guest_id=data.guest_id,
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
        item_data.get("menu_item_id") for item_data in data.items if item_data.get("menu_item_id")
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

    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "status": order.status,
        "table_id": str(order.table_id) if order.table_id else None,
        "table_ids": normalize_order_table_ids(order.table_ids, order.table_id),
        "reservation_id": str(order.reservation_id) if order.reservation_id else None,
    }


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
        "table_ids": normalize_order_table_ids(order.table_ids, order.table_id),
        "reservation_id": str(order.reservation_id) if order.reservation_id else None,
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
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
        "opened_at",
    }
    update_data = data.model_dump(exclude_unset=True)
    table_id_update = (
        update_data.pop("table_id", None) if "table_id" in update_data else TABLE_ID_UNSET
    )
    reservation_id_update: Any = (
        update_data.pop("reservation_id", None)
        if "reservation_id" in update_data
        else RESERVATION_ID_UNSET
    )
    update_data.pop("table_ids", None)

    if "status" in update_data and update_data["status"]:
        if update_data["status"] not in ORDER_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {update_data['status']}")

    # Parse datetime strings to datetime objects
    for date_field in ("paid_at", "closed_at"):
        if date_field in update_data and isinstance(update_data[date_field], str):
            update_data[date_field] = dt.fromisoformat(
                update_data[date_field].replace("Z", "+00:00")
            )

    if reservation_id_update is not RESERVATION_ID_UNSET:
        if reservation_id_update is None:
            raise HTTPException(status_code=400, detail="Reservation is required for every order")

        resolved_table_id, resolved_table_ids = (
            await _resolve_order_table_assignment_from_reservation(
                session,
                order.tenant_id,
                reservation_id_update,
            )
        )
        order.reservation_id = reservation_id_update
        order.table_id = resolved_table_id
        order.table_ids = [str(table_id) for table_id in resolved_table_ids] or None

    if table_id_update is not TABLE_ID_UNSET:
        if order.reservation_id is not None:
            raise HTTPException(
                status_code=400,
                detail="Table assignment is derived from reservation. Update reservation instead.",
            )
        if table_id_update is None:
            order.table_id = None
            order.table_ids = None
        else:
            reference_date = (
                order.opened_at.astimezone(UTC).date()
                if order.opened_at and order.opened_at.tzinfo is not None
                else (order.opened_at or datetime.now(UTC)).date()
            )
            try:
                resolved_table_ids = await resolve_group_table_ids(
                    session,
                    order.tenant_id,
                    table_id_update,
                    reference_date,
                )
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc))
            order.table_id = resolved_table_ids[0] if resolved_table_ids else table_id_update
            order.table_ids = [str(table_id) for table_id in resolved_table_ids]

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
        "table_id": str(order.table_id) if order.table_id else None,
        "table_ids": normalize_order_table_ids(order.table_ids, order.table_id),
        "reservation_id": str(order.reservation_id) if order.reservation_id else None,
        "total": order.total,
        "payment_status": order.payment_status,
    }


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    await session.delete(order)
    await session.commit()

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        await manager.broadcast_to_tenant(
            str(tenant_id),
            {"type": "order_deleted", "data": {"id": str(order_id)}},
        )

    return None


@router.post("/{order_id}/items", status_code=201)
async def add_order_item(
    order_id: uuid.UUID,
    data: OrderItemCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    item = OrderItem(
        order_id=order.id,
        menu_item_id=data.menu_item_id,
        item_name=data.item_name,
        item_description=data.item_description,
        category=data.category,
        quantity=max(1, data.quantity),
        unit_price=data.unit_price,
        total_price=max(1, data.quantity) * data.unit_price,
        tax_rate=data.tax_rate,
        notes=data.notes,
        sort_order=data.sort_order or 0,
    )
    session.add(item)
    await session.flush()

    await _recalculate_order_totals(order, session)
    await session.commit()
    await session.refresh(item)

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        await manager.broadcast_to_tenant(
            str(tenant_id),
            {"type": "order_updated", "data": {"id": str(order_id)}},
        )

    return _serialize_item(item)


@router.patch("/{order_id}/items/{item_id}")
async def update_order_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    data: OrderItemUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    item_result = await session.execute(
        select(OrderItem).where(OrderItem.id == item_id, OrderItem.order_id == order_id)
    )
    item = item_result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Order item not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)

    if "quantity" in update_data or "unit_price" in update_data:
        item.quantity = max(1, item.quantity)
        item.total_price = item.quantity * item.unit_price

    await _recalculate_order_totals(order, session)
    await session.commit()
    await session.refresh(item)

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        await manager.broadcast_to_tenant(
            str(tenant_id),
            {"type": "order_updated", "data": {"id": str(order_id)}},
        )

    return _serialize_item(item)


@router.delete("/{order_id}/items/{item_id}", status_code=204)
async def delete_order_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    item_result = await session.execute(
        select(OrderItem).where(OrderItem.id == item_id, OrderItem.order_id == order_id)
    )
    item = item_result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Order item not found")

    await session.delete(item)
    await _recalculate_order_totals(order, session)
    await session.commit()

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        await manager.broadcast_to_tenant(
            str(tenant_id),
            {"type": "order_updated", "data": {"id": str(order_id)}},
        )
