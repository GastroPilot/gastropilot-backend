"""Order statistics and analytics endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_manager_or_above
from app.models.order import Order, OrderItem

router = APIRouter(prefix="/order-statistics", tags=["statistics"])


def _paid_orders_filters(
    start_date: datetime | None,
    end_date: datetime | None,
) -> list:
    filters: list = [Order.payment_status == "paid"]
    if start_date:
        filters.append(Order.paid_at >= start_date)
    if end_date:
        filters.append(Order.paid_at <= end_date)
    return filters


async def _load_revenue_statistics(
    db: AsyncSession,
    filters: list,
) -> dict[str, Any]:
    aggregate_result = await db.execute(
        select(
            func.coalesce(func.sum(Order.total), 0.0).label("total_revenue"),
            func.coalesce(func.sum(Order.tip_amount), 0.0).label("total_tips"),
            func.coalesce(func.sum(Order.discount_amount), 0.0).label("total_discounts"),
            func.count(Order.id).label("total_orders"),
        ).where(*filters)
    )
    aggregate = aggregate_result.one()
    total_revenue = float(aggregate.total_revenue or 0.0)
    total_tips = float(aggregate.total_tips or 0.0)
    total_discounts = float(aggregate.total_discounts or 0.0)
    total_orders = int(aggregate.total_orders or 0)

    average_order_value = round(total_revenue / total_orders, 2) if total_orders > 0 else 0.0

    day_expr = func.date(Order.paid_at)
    daily_result = await db.execute(
        select(
            day_expr.label("day"),
            func.coalesce(func.sum(Order.total), 0.0).label("revenue"),
        )
        .where(*filters, Order.paid_at.is_not(None))
        .group_by(day_expr)
        .order_by(day_expr)
    )
    daily_revenue = {
        str(row.day): float(row.revenue or 0.0) for row in daily_result
    }

    return {
        "total_revenue": round(total_revenue, 2),
        "total_orders": total_orders,
        "average_order_value": average_order_value,
        "total_tips": round(total_tips, 2),
        "total_discounts": round(total_discounts, 2),
        "daily_revenue": dict(daily_revenue),
    }


async def _load_top_items(
    db: AsyncSession,
    filters: list,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    quantity_sum = func.coalesce(func.sum(OrderItem.quantity), 0)
    revenue_sum = func.coalesce(func.sum(OrderItem.total_price), 0.0)

    result = await db.execute(
        select(
            OrderItem.item_name.label("item_name"),
            quantity_sum.label("quantity_sold"),
            revenue_sum.label("revenue"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(*filters)
        .group_by(OrderItem.item_name)
        .order_by(quantity_sum.desc())
        .limit(limit)
    )
    return [
        {
            "item_name": row.item_name,
            "quantity_sold": int(row.quantity_sold or 0),
            "revenue": float(row.revenue or 0.0),
        }
        for row in result
    ]


async def _load_category_statistics(
    db: AsyncSession,
    filters: list,
) -> dict[str, dict[str, float | int]]:
    category_expr = func.coalesce(func.nullif(OrderItem.category, ""), "Uncategorized")

    result = await db.execute(
        select(
            category_expr.label("category"),
            func.coalesce(func.sum(OrderItem.quantity), 0).label("quantity"),
            func.coalesce(func.sum(OrderItem.total_price), 0.0).label("revenue"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(*filters)
        .group_by(category_expr)
    )

    return {
        str(row.category): {
            "quantity": int(row.quantity or 0),
            "revenue": float(row.revenue or 0.0),
        }
        for row in result
    }


async def _load_hourly_statistics(
    db: AsyncSession,
    filters: list,
) -> dict[str, dict[str, float | int]]:
    hour_expr = func.extract("hour", Order.opened_at)

    hourly: dict[str, dict[str, float | int]] = {}
    for h in range(24):
        hourly[str(h)] = {"order_count": 0, "revenue": 0.0}

    result = await db.execute(
        select(
            hour_expr.label("hour"),
            func.count(Order.id).label("order_count"),
            func.coalesce(func.sum(Order.total), 0.0).label("revenue"),
        )
        .where(*filters, Order.opened_at.is_not(None))
        .group_by(hour_expr)
        .order_by(hour_expr)
    )
    for row in result:
        hour_key = str(int(row.hour))
        hourly[hour_key] = {
            "order_count": int(row.order_count or 0),
            "revenue": float(row.revenue or 0.0),
        }

    return hourly


@router.get("/revenue")
async def revenue_statistics(
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    filters = _paid_orders_filters(start_date, end_date)
    return await _load_revenue_statistics(db, filters)


@router.get("/top-items")
async def top_items(
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    filters = _paid_orders_filters(start_date, end_date)
    return await _load_top_items(db, filters, limit=limit)


@router.get("/category-statistics")
async def category_statistics(
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    filters = _paid_orders_filters(start_date, end_date)
    return await _load_category_statistics(db, filters)


@router.get("/hourly-statistics")
async def hourly_statistics(
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    filters = _paid_orders_filters(start_date, end_date)
    return await _load_hourly_statistics(db, filters)


@router.get("/overview")
async def order_statistics_overview(
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    filters = _paid_orders_filters(start_date, end_date)

    revenue = await _load_revenue_statistics(db, filters)
    top_items = await _load_top_items(db, filters, limit=limit)
    category_statistics = await _load_category_statistics(db, filters)
    hourly_statistics = await _load_hourly_statistics(db, filters)

    return {
        "revenue": revenue,
        "top_items": top_items,
        "category_statistics": category_statistics,
        "hourly_statistics": hourly_statistics,
    }
