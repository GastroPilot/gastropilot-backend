"""Order statistics and analytics endpoints."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_manager_or_above
from app.models.order import Order, OrderItem

router = APIRouter(prefix="/order-statistics", tags=["statistics"])


@router.get("/revenue")
async def revenue_statistics(
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    query = select(Order).where(Order.payment_status == "paid")
    if start_date:
        query = query.where(Order.paid_at >= start_date)
    if end_date:
        query = query.where(Order.paid_at <= end_date)

    result = await db.execute(query)
    orders = result.scalars().all()

    total_revenue = sum(o.total for o in orders)
    total_tips = sum(o.tip_amount for o in orders)
    total_discounts = sum(o.discount_amount for o in orders)
    total_orders = len(orders)
    avg = round(total_revenue / total_orders, 2) if total_orders > 0 else 0.0

    daily_revenue: dict[str, float] = defaultdict(float)
    for o in orders:
        if o.paid_at:
            day = o.paid_at.date().isoformat()
            daily_revenue[day] += o.total

    return {
        "total_revenue": round(total_revenue, 2),
        "total_orders": total_orders,
        "average_order_value": avg,
        "total_tips": round(total_tips, 2),
        "total_discounts": round(total_discounts, 2),
        "daily_revenue": dict(daily_revenue),
    }


@router.get("/top-items")
async def top_items(
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    order_query = select(Order.id).where(Order.payment_status == "paid")
    if start_date:
        order_query = order_query.where(Order.paid_at >= start_date)
    if end_date:
        order_query = order_query.where(Order.paid_at <= end_date)

    order_result = await db.execute(order_query)
    order_ids = [row[0] for row in order_result.all()]

    if not order_ids:
        return []

    items_result = await db.execute(select(OrderItem).where(OrderItem.order_id.in_(order_ids)))
    items = items_result.scalars().all()

    item_stats: dict[str, dict] = {}
    for item in items:
        name = item.item_name
        if name not in item_stats:
            item_stats[name] = {"item_name": name, "quantity_sold": 0, "revenue": 0.0}
        item_stats[name]["quantity_sold"] += item.quantity
        item_stats[name]["revenue"] += item.total_price

    sorted_items = sorted(item_stats.values(), key=lambda x: x["quantity_sold"], reverse=True)
    return sorted_items[:limit]


@router.get("/category-statistics")
async def category_statistics(
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    order_query = select(Order.id).where(Order.payment_status == "paid")
    if start_date:
        order_query = order_query.where(Order.paid_at >= start_date)
    if end_date:
        order_query = order_query.where(Order.paid_at <= end_date)

    order_result = await db.execute(order_query)
    order_ids = [row[0] for row in order_result.all()]

    if not order_ids:
        return {}

    items_result = await db.execute(select(OrderItem).where(OrderItem.order_id.in_(order_ids)))
    items = items_result.scalars().all()

    cat_stats: dict[str, dict] = {}
    for item in items:
        cat = item.category or "Uncategorized"
        if cat not in cat_stats:
            cat_stats[cat] = {"quantity": 0, "revenue": 0.0}
        cat_stats[cat]["quantity"] += item.quantity
        cat_stats[cat]["revenue"] += item.total_price

    return cat_stats


@router.get("/hourly-statistics")
async def hourly_statistics(
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    query = select(Order).where(Order.payment_status == "paid")
    if start_date:
        query = query.where(Order.paid_at >= start_date)
    if end_date:
        query = query.where(Order.paid_at <= end_date)

    result = await db.execute(query)
    orders = result.scalars().all()

    hourly: dict[str, dict] = {}
    for h in range(24):
        hourly[str(h)] = {"order_count": 0, "revenue": 0.0}

    for o in orders:
        if o.opened_at:
            h = str(o.opened_at.hour)
            hourly[h]["order_count"] += 1
            hourly[h]["revenue"] += o.total

    return hourly
