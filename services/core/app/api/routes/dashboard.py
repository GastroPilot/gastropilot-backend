"""Dashboard batch endpoints – aggregieren mehrere Ressourcen in einem Request."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_staff_or_above
from app.models.block import Block, BlockAssignment
from app.models.reservation import Guest, Reservation
from app.models.restaurant import Area, Obstacle, Restaurant, Table
from app.models.table_config import ReservationTableDayConfig, TableDayConfig

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _serialize(obj: Any) -> dict:
    """Konvertiert ein SQLAlchemy-Modell-Objekt in ein JSON-serialisierbares Dict."""
    result: dict[str, Any] = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, uuid.UUID):
            val = str(val)
        elif isinstance(val, datetime):
            val = val.isoformat()
        result[col.name] = val
    return result


async def _get_restaurant_or_404(
    restaurant_id: str,
    session: AsyncSession,
) -> Restaurant:
    try:
        rid = uuid.UUID(restaurant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant nicht gefunden"
        )

    row = await session.get(Restaurant, rid)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant nicht gefunden"
        )
    return row


# ---------------------------------------------------------------------------
# GET /dashboard/batch/{restaurant_id}
# ---------------------------------------------------------------------------


@router.get("/batch/{restaurant_id}")
async def get_dashboard_batch(
    restaurant_id: str,
    date: date | None = Query(default=None, description="Datum für Reservierungen (YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_db),
    _current_user=Depends(require_staff_or_above),
) -> dict:
    """
    Liefert alle benötigten Dashboard-Daten in einem einzigen Request:
    restaurant, areas, tables, obstacles, reservations, orders.

    Ersetzt ~10 einzelne API-Calls im Frontend.
    """
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    rid = restaurant.id

    # Areas
    areas_result = await session.execute(select(Area).where(Area.tenant_id == rid))
    areas = [_serialize(r) for r in areas_result.scalars().all()]

    # Tables
    tables_result = await session.execute(
        select(Table).where(Table.tenant_id == rid, Table.is_active == True)
    )
    tables = [_serialize(r) for r in tables_result.scalars().all()]

    # Obstacles
    obstacles_result = await session.execute(select(Obstacle).where(Obstacle.tenant_id == rid))
    obstacles = [_serialize(r) for r in obstacles_result.scalars().all()]

    # Reservations – gefiltert nach Datum wenn angegeben, sonst heutiger Tag
    target_date = date or datetime.now(UTC).date()
    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)

    reservations_result = await session.execute(
        select(Reservation).where(
            Reservation.tenant_id == rid,
            Reservation.start_at >= day_start,
            Reservation.start_at < day_end,
        )
    )
    reservations = [_serialize(r) for r in reservations_result.scalars().all()]

    # Blocks (inkl. Überlappung mit dem Tag)
    blocks_result = await session.execute(
        select(Block).where(
            Block.tenant_id == rid,
            Block.start_at < day_end,
            Block.end_at > day_start,
        )
    )
    block_rows = blocks_result.scalars().all()
    blocks = [_serialize(b) for b in block_rows]

    block_assignments: list[dict[str, Any]] = []
    if block_rows:
        block_ids = [b.id for b in block_rows]
        assignments_result = await session.execute(
            select(BlockAssignment).where(BlockAssignment.block_id.in_(block_ids))
        )
        block_assignments = [_serialize(a) for a in assignments_result.scalars().all()]

    # Orders – aktive Orders für heute (status != closed/cancelled)
    try:
        orders_result = await session.execute(
            text("""
                SELECT id, tenant_id, table_id, order_number, status,
                       subtotal, tax_amount, total, payment_status,
                       notes, opened_at, closed_at, created_at, updated_at
                FROM orders
                WHERE tenant_id = :tid
                  AND opened_at >= :day_start
                  AND opened_at < :day_end
                ORDER BY opened_at DESC
                LIMIT 500
                """),
            {"tid": str(rid), "day_start": day_start, "day_end": day_end},
        )
        orders = [dict(row._mapping) for row in orders_result]
        # UUID / datetime serialisieren
        for o in orders:
            for k, v in o.items():
                if isinstance(v, uuid.UUID):
                    o[k] = str(v)
                elif isinstance(v, datetime):
                    o[k] = v.isoformat()
    except Exception:
        orders = []

    # Table day configs (inkl. temporäre Tische) für den gewählten Tag
    tdc_result = await session.execute(
        select(TableDayConfig).where(
            TableDayConfig.tenant_id == rid,
            TableDayConfig.date == target_date,
        )
    )
    table_day_config_rows = tdc_result.scalars().all()
    table_day_configs = [_serialize(cfg) for cfg in table_day_config_rows]

    # Zuordnungen Reservierung <-> temporäre Tisch-Configs (tagesüberlappend)
    reservation_table_day_configs: list[dict[str, Any]] = []
    if table_day_config_rows:
        tdc_ids = [cfg.id for cfg in table_day_config_rows]
        rtdc_result = await session.execute(
            select(ReservationTableDayConfig).where(
                ReservationTableDayConfig.tenant_id == rid,
                ReservationTableDayConfig.table_day_config_id.in_(tdc_ids),
                ReservationTableDayConfig.start_at < day_end,
                ReservationTableDayConfig.end_at > day_start,
            )
        )
        reservation_table_day_configs = [
            _serialize(mapping) for mapping in rtdc_result.scalars().all()
        ]

    return {
        "restaurant": _serialize(restaurant),
        "areas": areas,
        "tables": tables,
        "obstacles": obstacles,
        "reservations": reservations,
        "blocks": blocks,
        "block_assignments": block_assignments,
        "orders": orders,
        "table_day_configs": table_day_configs,
        "reservation_table_day_configs": reservation_table_day_configs,
    }


# ---------------------------------------------------------------------------
# GET /dashboard/kitchen/{restaurant_id}
# ---------------------------------------------------------------------------


@router.get("/kitchen/{restaurant_id}")
async def get_kitchen_data(
    restaurant_id: str,
    session: AsyncSession = Depends(get_db),
    _current_user=Depends(require_staff_or_above),
) -> dict:
    """
    Küchen-Ansicht: aktive Orders mit allen OrderItems und Tischen.
    Gibt nur Orders mit Status open/in_preparation/ready zurück.
    """
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    rid = restaurant.id

    # Tabellen für Tischnamen
    tables_result = await session.execute(select(Table).where(Table.tenant_id == rid))
    tables = [_serialize(r) for r in tables_result.scalars().all()]

    # Aktive Orders
    try:
        orders_result = await session.execute(
            text("""
                SELECT id, tenant_id, table_id, order_number, status,
                       subtotal, tax_amount, total, payment_status,
                       notes, opened_at, closed_at, created_at, updated_at
                FROM orders
                WHERE tenant_id = :tid
                  AND status IN ('open', 'in_preparation', 'ready', 'confirmed', 'sent_to_kitchen')
                ORDER BY opened_at ASC
                LIMIT 200
                """),
            {"tid": str(rid)},
        )
        orders = [dict(row._mapping) for row in orders_result]

        order_ids = [o["id"] for o in orders]

        order_items: list[dict] = []
        if order_ids:
            ids_literal = ", ".join(f"'{oid}'" for oid in order_ids)
            items_result = await session.execute(text(f"""
                    SELECT id, order_id, menu_item_id, item_name, item_description,
                           category, quantity, unit_price, total_price,
                           tax_rate, status, notes, sort_order, created_at, updated_at
                    FROM order_items
                    WHERE order_id IN ({ids_literal})
                    ORDER BY sort_order ASC
                    """))
            order_items = [dict(row._mapping) for row in items_result]

        # Serialisieren
        for collection in (orders, order_items):
            for row in collection:
                for k, v in row.items():
                    if isinstance(v, uuid.UUID):
                        row[k] = str(v)
                    elif isinstance(v, datetime):
                        row[k] = v.isoformat()

    except Exception:
        orders = []
        order_items = []

    return {
        "orders": orders,
        "order_items": order_items,
        "tables": tables,
    }


# ---------------------------------------------------------------------------
# GET /dashboard/insights/{restaurant_id}
# ---------------------------------------------------------------------------


@router.get("/insights/{restaurant_id}")
async def get_insights_data(
    restaurant_id: str,
    from_date: date | None = Query(default=None, alias="from_date"),
    to_date: date | None = Query(default=None, alias="to_date"),
    session: AsyncSession = Depends(get_db),
    _current_user=Depends(require_staff_or_above),
) -> dict:
    """
    Analytics/Insights: Umsatz, Bestellungen, Reservierungen für einen Zeitraum.
    Standard: letzte 30 Tage.
    """
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    rid = restaurant.id

    # Zeitraum bestimmen
    today = datetime.now(UTC).date()
    _to = to_date or today
    _from = from_date or (_to - timedelta(days=30))

    period_start = datetime(_from.year, _from.month, _from.day, tzinfo=UTC)
    period_end = datetime(_to.year, _to.month, _to.day, tzinfo=UTC) + timedelta(days=1)

    # Reservierungen im Zeitraum
    reservations_result = await session.execute(
        select(
            func.count(Reservation.id), func.coalesce(func.sum(Reservation.party_size), 0)
        ).where(
            Reservation.tenant_id == rid,
            Reservation.start_at >= period_start,
            Reservation.start_at < period_end,
            Reservation.status.notin_(["cancelled", "no_show"]),
        )
    )
    res_count, guests_served = reservations_result.one()

    # Orders-Aggregat
    try:
        agg_result = await session.execute(
            text("""
                SELECT
                    COUNT(*) AS orders_count,
                    COALESCE(SUM(total), 0) AS total_revenue,
                    COALESCE(AVG(total), 0) AS avg_order_value
                FROM orders
                WHERE tenant_id = :tid
                  AND opened_at >= :from_dt
                  AND opened_at < :to_dt
                  AND status NOT IN ('cancelled')
                """),
            {"tid": str(rid), "from_dt": period_start, "to_dt": period_end},
        )
        agg = dict(agg_result.one()._mapping)
        orders_count = int(agg.get("orders_count", 0))
        total_revenue = float(agg.get("total_revenue", 0.0))
        avg_order_value = float(agg.get("avg_order_value", 0.0))

        # Umsatz pro Tag
        revenue_by_day_result = await session.execute(
            text("""
                SELECT
                    DATE(opened_at AT TIME ZONE 'UTC') AS day,
                    COALESCE(SUM(total), 0) AS revenue
                FROM orders
                WHERE tenant_id = :tid
                  AND opened_at >= :from_dt
                  AND opened_at < :to_dt
                  AND status NOT IN ('cancelled')
                GROUP BY day
                ORDER BY day ASC
                """),
            {"tid": str(rid), "from_dt": period_start, "to_dt": period_end},
        )
        revenue_by_day = [
            {"date": str(row.day), "revenue": float(row.revenue)} for row in revenue_by_day_result
        ]

        # Bestellungen nach Status
        status_result = await session.execute(
            text("""
                SELECT status, COUNT(*) AS cnt
                FROM orders
                WHERE tenant_id = :tid
                  AND opened_at >= :from_dt
                  AND opened_at < :to_dt
                GROUP BY status
                """),
            {"tid": str(rid), "from_dt": period_start, "to_dt": period_end},
        )
        orders_by_status = {row.status: int(row.cnt) for row in status_result}

        # Beliebteste Artikel
        popular_result = await session.execute(
            text("""
                SELECT
                    oi.item_name AS name,
                    SUM(oi.quantity) AS quantity,
                    SUM(oi.total_price) AS revenue
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE o.tenant_id = :tid
                  AND o.opened_at >= :from_dt
                  AND o.opened_at < :to_dt
                  AND o.status NOT IN ('cancelled')
                GROUP BY oi.item_name
                ORDER BY quantity DESC
                LIMIT 10
                """),
            {"tid": str(rid), "from_dt": period_start, "to_dt": period_end},
        )
        popular_items = [
            {"name": row.name, "quantity": int(row.quantity), "revenue": float(row.revenue)}
            for row in popular_result
        ]

    except Exception:
        orders_count = 0
        total_revenue = 0.0
        avg_order_value = 0.0
        revenue_by_day = []
        orders_by_status = {}
        popular_items = []

    return {
        "total_revenue": total_revenue,
        "orders_count": orders_count,
        "avg_order_value": avg_order_value,
        "reservations_count": int(res_count),
        "guests_served": int(guests_served),
        "popular_items": popular_items,
        "revenue_by_day": revenue_by_day,
        "orders_by_status": orders_by_status,
    }
