"""
Dashboard batch endpoints for optimized data loading.

Instead of making 10+ separate API calls, the frontend can use these
batch endpoints to fetch all dashboard data in a single request.
"""

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Area,
    Block,
    BlockAssignment,
    Obstacle,
    Order,
    Reservation,
    ReservationTableDayConfig,
    Restaurant,
    Table,
    TableDayConfig,
    User,
)
from app.dependencies import get_current_user, get_session

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardDataResponse(BaseModel):
    """Response model for dashboard batch endpoint."""

    restaurant: dict | None
    areas: list[dict]
    tables: list[dict]
    obstacles: list[dict]
    reservations: list[dict]
    blocks: list[dict]
    block_assignments: list[dict]
    orders: list[dict]
    table_day_configs: list[dict]
    reservation_table_day_configs: list[dict]

    class Config:
        from_attributes = True


@router.get("/batch/{restaurant_id}", response_model=DashboardDataResponse)
async def get_dashboard_data(
    restaurant_id: int,
    date_str: str | None = Query(None, alias="date", description="Date in YYYY-MM-DD format"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch all dashboard data in a single request.

    This endpoint combines:
    - Restaurant info
    - Areas
    - Tables (with day configs applied)
    - Obstacles
    - Reservations for the selected date
    - Blocks for the selected date
    - Block assignments
    - Active orders
    - Table day configs
    - Reservation table day configs

    This reduces the number of API calls from 10+ to 1, significantly
    improving dashboard load time.
    """
    # Parse date or use today
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Use YYYY-MM-DD",
            )
    else:
        selected_date = date.today()

    # Calculate date range for queries
    start_of_day = datetime.combine(selected_date, datetime.min.time()).replace(tzinfo=UTC)
    end_of_day = datetime.combine(selected_date, datetime.max.time()).replace(tzinfo=UTC)

    # Fetch restaurant
    restaurant_result = await session.execute(
        select(Restaurant).where(Restaurant.id == restaurant_id)
    )
    restaurant = restaurant_result.scalar_one_or_none()

    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    # Fetch all data in parallel using asyncio.gather would be ideal,
    # but SQLAlchemy sessions aren't thread-safe. We'll batch the queries instead.

    # Areas
    areas_result = await session.execute(select(Area).where(Area.restaurant_id == restaurant_id))
    areas = areas_result.scalars().all()

    # Tables
    tables_result = await session.execute(
        select(Table).where(and_(Table.restaurant_id == restaurant_id, Table.is_active == True))
    )
    tables = tables_result.scalars().all()

    # Obstacles
    obstacles_result = await session.execute(
        select(Obstacle).where(Obstacle.restaurant_id == restaurant_id)
    )
    obstacles = obstacles_result.scalars().all()

    # Reservations for the selected date
    reservations_result = await session.execute(
        select(Reservation)
        .where(
            and_(
                Reservation.restaurant_id == restaurant_id,
                Reservation.start_at >= start_of_day,
                Reservation.start_at <= end_of_day,
            )
        )
        .order_by(Reservation.start_at)
    )
    reservations = reservations_result.scalars().all()

    # Blocks for the selected date
    blocks_result = await session.execute(
        select(Block).where(
            and_(
                Block.restaurant_id == restaurant_id,
                Block.start_at <= end_of_day,
                Block.end_at >= start_of_day,
            )
        )
    )
    blocks = blocks_result.scalars().all()

    # Block assignments
    block_ids = [b.id for b in blocks]
    if block_ids:
        block_assignments_result = await session.execute(
            select(BlockAssignment).where(BlockAssignment.block_id.in_(block_ids))
        )
        block_assignments = block_assignments_result.scalars().all()
    else:
        block_assignments = []

    # Active orders (not paid/canceled)
    orders_result = await session.execute(
        select(Order)
        .where(
            and_(
                Order.restaurant_id == restaurant_id,
                Order.status.not_in(["paid", "canceled"]),
            )
        )
        .order_by(Order.opened_at.desc())
    )
    orders = orders_result.scalars().all()

    # Table day configs for the selected date
    table_day_configs_result = await session.execute(
        select(TableDayConfig).where(
            and_(
                TableDayConfig.restaurant_id == restaurant_id,
                TableDayConfig.date == selected_date,
            )
        )
    )
    table_day_configs = table_day_configs_result.scalars().all()

    # Reservation table day configs
    reservation_ids = [r.id for r in reservations]
    if reservation_ids:
        rtdc_result = await session.execute(
            select(ReservationTableDayConfig).where(
                ReservationTableDayConfig.reservation_id.in_(reservation_ids)
            )
        )
        reservation_table_day_configs = rtdc_result.scalars().all()
    else:
        reservation_table_day_configs = []

    # Convert to dicts
    def model_to_dict(obj):
        """Convert SQLAlchemy model to dict."""
        if obj is None:
            return None
        result = {}
        for column in obj.__table__.columns:
            value = getattr(obj, column.name)
            # Convert datetime to ISO format
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, date):
                value = value.isoformat()
            result[column.name] = value
        return result

    return DashboardDataResponse(
        restaurant=model_to_dict(restaurant),
        areas=[model_to_dict(a) for a in areas],
        tables=[model_to_dict(t) for t in tables],
        obstacles=[model_to_dict(o) for o in obstacles],
        reservations=[model_to_dict(r) for r in reservations],
        blocks=[model_to_dict(b) for b in blocks],
        block_assignments=[model_to_dict(ba) for ba in block_assignments],
        orders=[model_to_dict(o) for o in orders],
        table_day_configs=[model_to_dict(tdc) for tdc in table_day_configs],
        reservation_table_day_configs=[
            model_to_dict(rtdc) for rtdc in reservation_table_day_configs
        ],
    )


class KitchenDataResponse(BaseModel):
    """Response model for kitchen batch endpoint."""

    orders: list[dict]
    order_items: list[dict]
    tables: list[dict]

    class Config:
        from_attributes = True


@router.get("/kitchen/{restaurant_id}", response_model=KitchenDataResponse)
async def get_kitchen_data(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch all kitchen view data in a single request.

    Optimized for the kitchen display showing:
    - Orders with active kitchen items
    - Kitchen-relevant order items (sent/in_preparation/ready)
    - Table info for context
    """
    from app.database.models import OrderItem

    # Verify restaurant exists
    restaurant_result = await session.execute(
        select(Restaurant).where(Restaurant.id == restaurant_id)
    )
    restaurant = restaurant_result.scalar_one_or_none()

    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    # Item-getriebene Kitchen Queue: nur bereits gesendete/aktive Küchen-Items.
    items_result = await session.execute(
        select(OrderItem, Order)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            and_(
                Order.restaurant_id == restaurant_id,
                Order.status.not_in(["paid", "canceled"]),
                OrderItem.status.in_(["sent", "in_preparation", "ready"]),
            )
        )
        .order_by(
            OrderItem.sent_to_kitchen_at,
            OrderItem.kitchen_ticket_no,
            OrderItem.sort_order,
            OrderItem.created_at,
        )
    )
    item_order_pairs = items_result.all()

    orders_map: dict[int, Order] = {}
    order_items: list[OrderItem] = []
    for item, order in item_order_pairs:
        if order.id not in orders_map:
            orders_map[order.id] = order
        order_items.append(item)

    orders = sorted(
        orders_map.values(),
        key=lambda order: order.opened_at or datetime.min.replace(tzinfo=UTC),
    )

    # Tables for context
    table_ids = list(set(o.table_id for o in orders if o.table_id))
    if table_ids:
        tables_result = await session.execute(select(Table).where(Table.id.in_(table_ids)))
        tables = tables_result.scalars().all()
    else:
        tables = []

    # Convert to dicts
    def model_to_dict(obj):
        if obj is None:
            return None
        result = {}
        for column in obj.__table__.columns:
            value = getattr(obj, column.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, date):
                value = value.isoformat()
            result[column.name] = value
        return result

    return KitchenDataResponse(
        orders=[model_to_dict(o) for o in orders],
        order_items=[model_to_dict(i) for i in order_items],
        tables=[model_to_dict(t) for t in tables],
    )


class InsightsDataResponse(BaseModel):
    """Response model for insights/analytics batch endpoint."""

    total_revenue: float
    orders_count: int
    avg_order_value: float
    reservations_count: int
    guests_served: int
    popular_items: list[dict]
    revenue_by_day: list[dict]
    orders_by_status: dict

    class Config:
        from_attributes = True


@router.get("/insights/{restaurant_id}", response_model=InsightsDataResponse)
async def get_insights_data(
    restaurant_id: int,
    from_date: str | None = Query(None, description="Start date YYYY-MM-DD"),
    to_date: str | None = Query(None, description="End date YYYY-MM-DD"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch analytics/insights data in a single request.

    Includes:
    - Total revenue
    - Order counts and averages
    - Reservation statistics
    - Popular items
    - Revenue trends
    """
    from sqlalchemy import func

    from app.database.models import OrderItem

    # Parse dates or use last 30 days
    if from_date:
        try:
            start_date = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid from_date format")
    else:
        start_date = datetime.now(UTC) - timedelta(days=30)

    if to_date:
        try:
            end_date = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=UTC) + timedelta(
                days=1
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid to_date format")
    else:
        end_date = datetime.now(UTC) + timedelta(days=1)

    # Total revenue and order count
    revenue_result = await session.execute(
        select(
            func.sum(Order.total).label("total_revenue"),
            func.count(Order.id).label("orders_count"),
            func.avg(Order.total).label("avg_order_value"),
            func.sum(Order.party_size).label("guests_served"),
        ).where(
            and_(
                Order.restaurant_id == restaurant_id,
                Order.status == "paid",
                Order.paid_at >= start_date,
                Order.paid_at < end_date,
            )
        )
    )
    stats = revenue_result.one()

    # Reservations count
    reservations_result = await session.execute(
        select(func.count(Reservation.id)).where(
            and_(
                Reservation.restaurant_id == restaurant_id,
                Reservation.start_at >= start_date,
                Reservation.start_at < end_date,
                Reservation.status.in_(["confirmed", "seated", "completed"]),
            )
        )
    )
    reservations_count = reservations_result.scalar() or 0

    # Popular items (top 10)
    popular_items_result = await session.execute(
        select(
            OrderItem.item_name,
            func.sum(OrderItem.quantity).label("total_quantity"),
            func.sum(OrderItem.total_price).label("total_revenue"),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .where(
            and_(
                Order.restaurant_id == restaurant_id,
                Order.status == "paid",
                Order.paid_at >= start_date,
                Order.paid_at < end_date,
            )
        )
        .group_by(OrderItem.item_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(10)
    )
    popular_items = [
        {"name": row[0], "quantity": row[1], "revenue": float(row[2] or 0)}
        for row in popular_items_result.all()
    ]

    # Orders by status
    status_result = await session.execute(
        select(
            Order.status,
            func.count(Order.id).label("count"),
        )
        .where(
            and_(
                Order.restaurant_id == restaurant_id,
                Order.opened_at >= start_date,
                Order.opened_at < end_date,
            )
        )
        .group_by(Order.status)
    )
    orders_by_status = {row[0]: row[1] for row in status_result.all()}

    # Revenue by day (last 7 days within range)
    revenue_by_day = []
    for i in range(7):
        day_start = end_date - timedelta(days=i + 1)
        day_end = end_date - timedelta(days=i)

        if day_start < start_date:
            break

        day_result = await session.execute(
            select(func.sum(Order.total)).where(
                and_(
                    Order.restaurant_id == restaurant_id,
                    Order.status == "paid",
                    Order.paid_at >= day_start,
                    Order.paid_at < day_end,
                )
            )
        )
        day_revenue = day_result.scalar() or 0
        revenue_by_day.append(
            {
                "date": day_start.date().isoformat(),
                "revenue": float(day_revenue),
            }
        )

    revenue_by_day.reverse()

    return InsightsDataResponse(
        total_revenue=float(stats.total_revenue or 0),
        orders_count=stats.orders_count or 0,
        avg_order_value=float(stats.avg_order_value or 0),
        reservations_count=reservations_count,
        guests_served=stats.guests_served or 0,
        popular_items=popular_items,
        revenue_by_day=revenue_by_day,
        orders_by_status=orders_by_status,
    )
