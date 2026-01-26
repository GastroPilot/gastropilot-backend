"""
Order Statistics Router
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_
from sqlalchemy.orm import selectinload

from app.dependencies import get_session, get_current_user, require_schichtleiter_role, require_orders_module, User
from app.database.models import Order, OrderItem, MenuItem, Restaurant
from app.schemas import OrderRead

router = APIRouter(prefix="/restaurants/{restaurant_id}/order-statistics", tags=["order-statistics"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    """Holt ein Restaurant oder wirft 404."""
    from app.database.models import Restaurant
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


@router.get("/revenue")
async def get_revenue_statistics(
    restaurant_id: int,
    start_date: Optional[datetime] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date (ISO format)"),
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Holt Umsatzstatistiken für ein Restaurant."""
    await _get_restaurant_or_404(restaurant_id, session)

    query = select(Order).where(
        and_(
            Order.restaurant_id == restaurant_id,
            Order.payment_status == "paid",
        )
    )

    if start_date:
        query = query.where(Order.paid_at >= start_date)
    if end_date:
        query = query.where(Order.paid_at <= end_date)

    result = await session.execute(query)
    orders = result.scalars().all()

    total_revenue = sum(order.total for order in orders)
    total_orders = len(orders)
    average_order_value = total_revenue / total_orders if total_orders > 0 else 0
    total_tips = sum(order.tip_amount for order in orders)
    total_discounts = sum(order.discount_amount for order in orders)

    # Tagesumsatz
    daily_revenue = {}
    for order in orders:
        if order.paid_at:
            day = order.paid_at.date()
            daily_revenue[day] = daily_revenue.get(day, 0) + order.total

    return {
        "total_revenue": round(total_revenue, 2),
        "total_orders": total_orders,
        "average_order_value": round(average_order_value, 2),
        "total_tips": round(total_tips, 2),
        "total_discounts": round(total_discounts, 2),
        "daily_revenue": {str(k): round(v, 2) for k, v in sorted(daily_revenue.items())},
    }


@router.get("/top-items")
async def get_top_items(
    restaurant_id: int,
    start_date: Optional[datetime] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date (ISO format)"),
    limit: int = Query(10, ge=1, le=50, description="Number of top items to return"),
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Holt die meistverkauften Artikel."""
    await _get_restaurant_or_404(restaurant_id, session)

    query = select(Order).where(
        and_(
            Order.restaurant_id == restaurant_id,
            Order.payment_status == "paid",
        )
    )

    if start_date:
        query = query.where(Order.paid_at >= start_date)
    if end_date:
        query = query.where(Order.paid_at <= end_date)

    result = await session.execute(query)
    orders = result.scalars().all()

    order_ids = [order.id for order in orders]

    if not order_ids:
        return []

    # Hole alle OrderItems für diese Bestellungen
    items_query = select(OrderItem).where(OrderItem.order_id.in_(order_ids))
    items_result = await session.execute(items_query)
    items = items_result.scalars().all()

    # Aggregiere nach item_name
    item_stats = {}
    for item in items:
        name = item.item_name
        if name not in item_stats:
            item_stats[name] = {"quantity": 0, "revenue": 0.0}
        item_stats[name]["quantity"] += item.quantity
        item_stats[name]["revenue"] += item.total_price

    # Sortiere nach Anzahl oder Umsatz
    top_items = sorted(
        item_stats.items(),
        key=lambda x: x[1]["quantity"],
        reverse=True
    )[:limit]

    return [
        {
            "item_name": name,
            "quantity_sold": stats["quantity"],
            "revenue": round(stats["revenue"], 2),
        }
        for name, stats in top_items
    ]


@router.get("/category-statistics")
async def get_category_statistics(
    restaurant_id: int,
    start_date: Optional[datetime] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date (ISO format)"),
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Holt Umsatzstatistiken nach Kategorien."""
    await _get_restaurant_or_404(restaurant_id, session)

    query = select(Order).where(
        and_(
            Order.restaurant_id == restaurant_id,
            Order.payment_status == "paid",
        )
    )

    if start_date:
        query = query.where(Order.paid_at >= start_date)
    if end_date:
        query = query.where(Order.paid_at <= end_date)

    result = await session.execute(query)
    orders = result.scalars().all()

    order_ids = [order.id for order in orders]

    if not order_ids:
        return {}

    items_query = select(OrderItem).where(OrderItem.order_id.in_(order_ids))
    items_result = await session.execute(items_query)
    items = items_result.scalars().all()

    category_stats = {}
    for item in items:
        category = item.category or "Unbekannt"
        if category not in category_stats:
            category_stats[category] = {"quantity": 0, "revenue": 0.0}
        category_stats[category]["quantity"] += item.quantity
        category_stats[category]["revenue"] += item.total_price

    return {
        cat: {
            "quantity": stats["quantity"],
            "revenue": round(stats["revenue"], 2),
        }
        for cat, stats in category_stats.items()
    }


@router.get("/hourly-statistics")
async def get_hourly_statistics(
    restaurant_id: int,
    start_date: Optional[datetime] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date (ISO format)"),
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Holt Statistiken nach Stunden."""
    await _get_restaurant_or_404(restaurant_id, session)

    query = select(Order).where(
        and_(
            Order.restaurant_id == restaurant_id,
            Order.payment_status == "paid",
        )
    )

    if start_date:
        query = query.where(Order.paid_at >= start_date)
    if end_date:
        query = query.where(Order.paid_at <= end_date)

    result = await session.execute(query)
    orders = result.scalars().all()

    hourly_stats = {hour: {"count": 0, "revenue": 0.0} for hour in range(24)}

    for order in orders:
        if order.paid_at:
            hour = order.paid_at.hour
            hourly_stats[hour]["count"] += 1
            hourly_stats[hour]["revenue"] += order.total

    return {
        str(hour): {
            "order_count": stats["count"],
            "revenue": round(stats["revenue"], 2),
        }
        for hour, stats in hourly_stats.items()
    }

