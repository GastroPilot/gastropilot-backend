"""Dashboard batch endpoints – aggregieren mehrere Ressourcen in einem Request."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_staff_or_above
from app.models.block import Block, BlockAssignment
from app.models.reservation import Reservation
from app.models.restaurant import Area, Obstacle, Restaurant, Table
from app.models.table_config import ReservationTableDayConfig, TableDayConfig
from app.models.user import User
from app.services.table_group_service import fetch_reservation_table_ids_map

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)
DEFAULT_RESTAURANT_TIMEZONE = "Europe/Berlin"

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


async def _get_scoped_restaurant_or_404(
    request: Request,
    current_user: User,
    restaurant_id: str,
    session: AsyncSession,
) -> Restaurant:
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    restaurant_id_str = str(restaurant.id)

    is_impersonating = getattr(request.state, "is_impersonating", False)
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id

    # Echter Platform-Admin (ohne Impersonation) darf tenant-übergreifend sehen.
    if current_user.role == "platform_admin" and not is_impersonating:
        return restaurant

    if not effective_tenant_id:
        raise HTTPException(status_code=403, detail="Tenant context required")

    if restaurant_id_str != str(effective_tenant_id):
        raise HTTPException(status_code=403, detail="Restaurant not in tenant scope")

    return restaurant


def _resolve_restaurant_timezone(restaurant: Restaurant) -> ZoneInfo:
    settings = restaurant.settings if isinstance(restaurant.settings, dict) else {}
    timezone_name = settings.get("timezone")

    if isinstance(timezone_name, str) and timezone_name.strip():
        try:
            return ZoneInfo(timezone_name.strip())
        except ZoneInfoNotFoundError:
            logger.warning(
                "Unbekannte Restaurant-Zeitzone, fallback auf Default",
                extra={
                    "restaurant_id": str(restaurant.id),
                    "timezone": timezone_name,
                    "fallback_timezone": DEFAULT_RESTAURANT_TIMEZONE,
                },
            )

    return ZoneInfo(DEFAULT_RESTAURANT_TIMEZONE)


def _build_utc_day_window(target_date: date, restaurant_tz: ZoneInfo) -> tuple[datetime, datetime]:
    local_day_start = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        tzinfo=restaurant_tz,
    )
    next_day = target_date + timedelta(days=1)
    local_day_end = datetime(
        next_day.year,
        next_day.month,
        next_day.day,
        tzinfo=restaurant_tz,
    )
    return local_day_start.astimezone(UTC), local_day_end.astimezone(UTC)


# ---------------------------------------------------------------------------
# GET /dashboard/batch/{restaurant_id}
# ---------------------------------------------------------------------------


@router.get("/batch/{restaurant_id}")
async def get_dashboard_batch(
    request: Request,
    restaurant_id: str,
    date: date | None = Query(default=None, description="Datum für Reservierungen (YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
) -> dict:
    """
    Liefert alle benötigten Dashboard-Daten in einem einzigen Request:
    restaurant, areas, tables, obstacles, reservations, orders.

    Ersetzt ~10 einzelne API-Calls im Frontend.
    """
    restaurant = await _get_scoped_restaurant_or_404(
        request=request,
        current_user=current_user,
        restaurant_id=restaurant_id,
        session=session,
    )
    rid = restaurant.id
    restaurant_tz = _resolve_restaurant_timezone(restaurant)

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

    # Tagesfenster in Restaurant-Zeitzone bestimmen und als UTC queryen.
    target_date = date or datetime.now(restaurant_tz).date()
    day_start, day_end = _build_utc_day_window(target_date, restaurant_tz)

    reservations_result = await session.execute(
        select(Reservation).where(
            Reservation.tenant_id == rid,
            Reservation.start_at >= day_start,
            Reservation.start_at < day_end,
        )
    )
    reservation_rows = reservations_result.scalars().all()
    reservation_table_ids_map = await fetch_reservation_table_ids_map(
        session,
        rid,
        [reservation.id for reservation in reservation_rows],
    )
    reservations: list[dict[str, Any]] = []
    for reservation in reservation_rows:
        payload = _serialize(reservation)
        table_ids = reservation_table_ids_map.get(str(reservation.id))
        if not table_ids:
            table_ids = [str(reservation.table_id)] if reservation.table_id else []
        payload["table_ids"] = table_ids
        if payload.get("table_id") is None and table_ids:
            payload["table_id"] = table_ids[0]
        reservations.append(payload)

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

    # Orders:
    # - alle Orders des gewählten Tages
    # - plus aktive, unbezahlte Orders außerhalb des Tages (z.B. Altlasten),
    #   damit Konflikte im Tischplan sichtbar sind.
    try:
        has_table_ids_column_result = await session.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'orders'
                      AND column_name = 'table_ids'
                )
                """)
        )
        has_table_ids_column = bool(has_table_ids_column_result.scalar())

        if has_table_ids_column:
            orders_result = await session.execute(
                text("""
                    SELECT id, tenant_id, reservation_id, table_id, table_ids, order_number, status,
                           subtotal, tax_amount, total, payment_status,
                           notes, opened_at, sent_to_kitchen_at, in_preparation_at,
                           ready_at, served_at, closed_at, created_at, updated_at
                    FROM orders
                    WHERE tenant_id = :tid
                      AND (
                        (opened_at >= :day_start AND opened_at < :day_end)
                        OR (status NOT IN ('paid', 'canceled') AND payment_status <> 'paid')
                      )
                    ORDER BY
                      CASE
                        WHEN status NOT IN ('paid', 'canceled') AND payment_status <> 'paid'
                        THEN 0
                        ELSE 1
                      END,
                      opened_at DESC
                    LIMIT 1000
                    """),
                {"tid": str(rid), "day_start": day_start, "day_end": day_end},
            )
        else:
            orders_result = await session.execute(
                text("""
                    SELECT id, tenant_id, reservation_id, table_id, order_number, status,
                           subtotal, tax_amount, total, payment_status,
                           notes, opened_at, sent_to_kitchen_at, in_preparation_at,
                           ready_at, served_at, closed_at, created_at, updated_at
                    FROM orders
                    WHERE tenant_id = :tid
                      AND (
                        (opened_at >= :day_start AND opened_at < :day_end)
                        OR (status NOT IN ('paid', 'canceled') AND payment_status <> 'paid')
                      )
                    ORDER BY
                      CASE
                        WHEN status NOT IN ('paid', 'canceled') AND payment_status <> 'paid'
                        THEN 0
                        ELSE 1
                      END,
                      opened_at DESC
                    LIMIT 1000
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
            raw_table_ids = o.get("table_ids")
            normalized_table_ids: list[str] = []
            if isinstance(raw_table_ids, list):
                normalized_table_ids = [str(table_id) for table_id in raw_table_ids if table_id]
            elif o.get("table_id"):
                normalized_table_ids = [str(o["table_id"])]
            o["table_ids"] = normalized_table_ids
            if o.get("table_id") is None and normalized_table_ids:
                o["table_id"] = normalized_table_ids[0]
    except SQLAlchemyError:
        logger.exception(
            "Orders konnten fuer Dashboard-Batch nicht geladen werden",
            extra={
                "restaurant_id": str(rid),
                "day_start": day_start.isoformat(),
                "day_end": day_end.isoformat(),
            },
        )
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
    request: Request,
    restaurant_id: str,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
) -> dict:
    """
    Küchen-Ansicht: aktive Orders mit kitchen-relevanten Items und Tischen.
    Die Queue ist item-getrieben (sent/in_preparation/ready), nicht nur order.status-getrieben.
    """
    restaurant = await _get_scoped_restaurant_or_404(
        request=request,
        current_user=current_user,
        restaurant_id=restaurant_id,
        session=session,
    )
    rid = restaurant.id

    # Tabellen für Tischnamen
    tables_result = await session.execute(select(Table).where(Table.tenant_id == rid))
    tables = [_serialize(r) for r in tables_result.scalars().all()]

    # Aktive Kitchen-Items (item-getrieben) + dazugehörige Orders
    try:
        kitchen_rows_result = await session.execute(
            text("""
                SELECT
                    o.id AS order_id,
                    o.tenant_id AS order_tenant_id,
                    o.table_id AS order_table_id,
                    o.order_number AS order_number,
                    o.status AS order_status,
                    o.subtotal AS order_subtotal,
                    o.tax_amount AS order_tax_amount,
                    o.total AS order_total,
                    o.payment_status AS order_payment_status,
                    o.notes AS order_notes,
                    o.opened_at AS order_opened_at,
                    o.sent_to_kitchen_at AS order_sent_to_kitchen_at,
                    o.in_preparation_at AS order_in_preparation_at,
                    o.ready_at AS order_ready_at,
                    o.served_at AS order_served_at,
                    o.closed_at AS order_closed_at,
                    o.created_at AS order_created_at,
                    o.updated_at AS order_updated_at,
                    oi.id AS item_id,
                    oi.order_id AS item_order_id,
                    oi.menu_item_id AS item_menu_item_id,
                    oi.item_name AS item_name,
                    oi.item_description AS item_description,
                    oi.category AS item_category,
                    oi.quantity AS item_quantity,
                    oi.unit_price AS item_unit_price,
                    oi.total_price AS item_total_price,
                    oi.tax_rate AS item_tax_rate,
                    oi.status AS item_status,
                    oi.notes AS item_notes,
                    oi.sort_order AS item_sort_order,
                    oi.kitchen_ticket_no AS item_kitchen_ticket_no,
                    oi.sent_to_kitchen_at AS item_sent_to_kitchen_at,
                    oi.created_at AS item_created_at,
                    oi.updated_at AS item_updated_at
                FROM orders o
                JOIN order_items oi ON oi.order_id = o.id
                WHERE o.tenant_id = :tid
                  AND o.status NOT IN ('paid', 'canceled')
                  AND oi.status IN ('sent', 'in_preparation', 'ready')
                ORDER BY
                    COALESCE(oi.sent_to_kitchen_at, oi.created_at) ASC,
                    oi.kitchen_ticket_no ASC NULLS LAST,
                    oi.sort_order ASC,
                    oi.created_at ASC
                """),
            {"tid": str(rid)},
        )
        kitchen_rows = [dict(row._mapping) for row in kitchen_rows_result]

        orders_map: dict[str, dict] = {}
        order_items: list[dict] = []
        ordered_order_ids: list[str] = []
        max_orders = 200

        for row in kitchen_rows:
            order_id = str(row["order_id"])
            if order_id not in orders_map:
                if len(ordered_order_ids) >= max_orders:
                    continue
                ordered_order_ids.append(order_id)
                orders_map[order_id] = {
                    "id": row["order_id"],
                    "tenant_id": row["order_tenant_id"],
                    "table_id": row["order_table_id"],
                    "order_number": row["order_number"],
                    "status": row["order_status"],
                    "subtotal": row["order_subtotal"],
                    "tax_amount": row["order_tax_amount"],
                    "total": row["order_total"],
                    "payment_status": row["order_payment_status"],
                    "notes": row["order_notes"],
                    "opened_at": row["order_opened_at"],
                    "sent_to_kitchen_at": row["order_sent_to_kitchen_at"],
                    "in_preparation_at": row["order_in_preparation_at"],
                    "ready_at": row["order_ready_at"],
                    "served_at": row["order_served_at"],
                    "closed_at": row["order_closed_at"],
                    "created_at": row["order_created_at"],
                    "updated_at": row["order_updated_at"],
                }

            if order_id not in orders_map:
                continue

            order_items.append(
                {
                    "id": row["item_id"],
                    "order_id": row["item_order_id"],
                    "menu_item_id": row["item_menu_item_id"],
                    "item_name": row["item_name"],
                    "item_description": row["item_description"],
                    "category": row["item_category"],
                    "quantity": row["item_quantity"],
                    "unit_price": row["item_unit_price"],
                    "total_price": row["item_total_price"],
                    "tax_rate": row["item_tax_rate"],
                    "status": row["item_status"],
                    "notes": row["item_notes"],
                    "sort_order": row["item_sort_order"],
                    "kitchen_ticket_no": row["item_kitchen_ticket_no"],
                    "sent_to_kitchen_at": row["item_sent_to_kitchen_at"],
                    "created_at": row["item_created_at"],
                    "updated_at": row["item_updated_at"],
                }
            )

        orders = [orders_map[order_id] for order_id in ordered_order_ids]

        # Serialisieren
        for collection in (orders, order_items):
            for row in collection:
                for k, v in row.items():
                    if isinstance(v, uuid.UUID):
                        row[k] = str(v)
                    elif isinstance(v, datetime):
                        row[k] = v.isoformat()

    except SQLAlchemyError:
        logger.exception(
            "Orders/Kitchen-Items konnten fuer Kitchen-Batch nicht geladen werden",
            extra={"restaurant_id": str(rid)},
        )
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
    request: Request,
    restaurant_id: str,
    from_date: date | None = Query(default=None, alias="from_date"),
    to_date: date | None = Query(default=None, alias="to_date"),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
) -> dict:
    """
    Analytics/Insights: Umsatz, Bestellungen, Reservierungen für einen Zeitraum.
    Standard: letzte 30 Tage.
    """
    restaurant = await _get_scoped_restaurant_or_404(
        request=request,
        current_user=current_user,
        restaurant_id=restaurant_id,
        session=session,
    )
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
            Reservation.status.notin_(["canceled", "no_show"]),
        )
    )
    res_count, guests_served = reservations_result.one()

    reservations_by_day: list[dict[str, int | str]] = []
    reservations_by_hour: list[dict[str, int | str]] = []
    try:
        reservations_by_day_result = await session.execute(
            text("""
                SELECT
                    DATE(start_at AT TIME ZONE 'UTC') AS day,
                    COUNT(*) AS cnt
                FROM reservations
                WHERE tenant_id = :tid
                  AND start_at >= :from_dt
                  AND start_at < :to_dt
                GROUP BY day
                ORDER BY day ASC
                """),
            {"tid": str(rid), "from_dt": period_start, "to_dt": period_end},
        )
        reservations_by_day = [
            {"date": str(row.day), "count": int(row.cnt)} for row in reservations_by_day_result
        ]

        reservations_by_hour_result = await session.execute(
            text("""
                SELECT
                    EXTRACT(HOUR FROM start_at AT TIME ZONE 'UTC')::int AS hour,
                    COUNT(*) AS cnt
                FROM reservations
                WHERE tenant_id = :tid
                  AND start_at >= :from_dt
                  AND start_at < :to_dt
                GROUP BY hour
                ORDER BY hour ASC
                """),
            {"tid": str(rid), "from_dt": period_start, "to_dt": period_end},
        )
        reservations_by_hour = [
            {"hour": str(int(row.hour)).zfill(2), "count": int(row.cnt)}
            for row in reservations_by_hour_result
        ]
    except SQLAlchemyError:
        logger.exception(
            "Reservation-Insights konnten nicht berechnet werden",
            extra={
                "restaurant_id": str(rid),
                "from_dt": period_start.isoformat(),
                "to_dt": period_end.isoformat(),
            },
        )

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
                  AND status NOT IN ('canceled')
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
                  AND status NOT IN ('canceled')
                GROUP BY day
                ORDER BY day ASC
                """),
            {"tid": str(rid), "from_dt": period_start, "to_dt": period_end},
        )
        revenue_by_day = [
            {"date": str(row.day), "revenue": float(row.revenue)} for row in revenue_by_day_result
        ]

        # Bestellungen pro Tag
        orders_by_day_result = await session.execute(
            text("""
                SELECT
                    DATE(opened_at AT TIME ZONE 'UTC') AS day,
                    COUNT(*) AS cnt
                FROM orders
                WHERE tenant_id = :tid
                  AND opened_at >= :from_dt
                  AND opened_at < :to_dt
                  AND status NOT IN ('canceled')
                GROUP BY day
                ORDER BY day ASC
                """),
            {"tid": str(rid), "from_dt": period_start, "to_dt": period_end},
        )
        orders_by_day = [
            {"date": str(row.day), "count": int(row.cnt)} for row in orders_by_day_result
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
                  AND o.status NOT IN ('canceled')
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

        # Kategorie-Statistiken
        category_result = await session.execute(
            text("""
                SELECT
                    COALESCE(NULLIF(oi.category, ''), 'Uncategorized') AS category,
                    SUM(oi.quantity) AS quantity,
                    COALESCE(SUM(oi.total_price), 0) AS revenue
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE o.tenant_id = :tid
                  AND o.opened_at >= :from_dt
                  AND o.opened_at < :to_dt
                  AND o.status NOT IN ('canceled')
                GROUP BY category
                """),
            {"tid": str(rid), "from_dt": period_start, "to_dt": period_end},
        )
        category_statistics: dict[str, dict[str, float | int]] = {}
        for row in category_result:
            category_statistics[str(row.category)] = {
                "quantity": int(row.quantity or 0),
                "revenue": float(row.revenue or 0.0),
            }

        # Stunden-Statistiken (wie /order-statistics/hourly-statistics)
        hourly_statistics: dict[str, dict[str, float | int]] = {
            str(hour).zfill(2): {"order_count": 0, "revenue": 0.0} for hour in range(24)
        }
        hourly_result = await session.execute(
            text("""
                SELECT
                    EXTRACT(HOUR FROM opened_at AT TIME ZONE 'UTC')::int AS hour,
                    COUNT(*) AS order_count,
                    COALESCE(SUM(total), 0) AS revenue
                FROM orders
                WHERE tenant_id = :tid
                  AND opened_at >= :from_dt
                  AND opened_at < :to_dt
                  AND status NOT IN ('canceled')
                GROUP BY hour
                ORDER BY hour ASC
                """),
            {"tid": str(rid), "from_dt": period_start, "to_dt": period_end},
        )
        for row in hourly_result:
            hour_key = str(int(row.hour)).zfill(2)
            hourly_statistics[hour_key] = {
                "order_count": int(row.order_count or 0),
                "revenue": float(row.revenue or 0.0),
            }

    except SQLAlchemyError:
        logger.exception(
            "Orders-Insights konnten nicht berechnet werden",
            extra={
                "restaurant_id": str(rid),
                "from_dt": period_start.isoformat(),
                "to_dt": period_end.isoformat(),
            },
        )
        orders_count = 0
        total_revenue = 0.0
        avg_order_value = 0.0
        revenue_by_day = []
        orders_by_day = []
        orders_by_status = {}
        popular_items = []
        category_statistics = {}
        hourly_statistics = {
            str(hour).zfill(2): {"order_count": 0, "revenue": 0.0} for hour in range(24)
        }

    return {
        "total_revenue": total_revenue,
        "orders_count": orders_count,
        "avg_order_value": avg_order_value,
        "reservations_count": int(res_count),
        "guests_served": int(guests_served),
        "popular_items": popular_items,
        "category_statistics": category_statistics,
        "hourly_statistics": hourly_statistics,
        "revenue_by_day": revenue_by_day,
        "orders_by_day": orders_by_day,
        "reservations_by_day": reservations_by_day,
        "reservations_by_hour": reservations_by_hour,
        "orders_by_status": orders_by_status,
    }
