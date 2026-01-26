"""
AI Router für KI-gestützte Funktionen.

Bietet Endpoints für:
- Tischvorschläge basierend auf aktuellem Restaurant-Kontext
"""

import logging
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Order,
    OrderItem,
    Reservation,
    Restaurant,
    Table,
    User,
)
from app.dependencies import get_current_user, get_session, require_mitarbeiter_role
from app.services.ai_service import TableSuggestion, ai_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/restaurants/{restaurant_id}/ai",
    tags=["ai"],
)


class SuggestTableRequest(BaseModel):
    """Request für Tischvorschläge."""

    context_hint: str | None = None  # z.B. Gästename oder Tischnummer


class SuggestTableResponse(BaseModel):
    """Response mit Tischvorschlägen."""

    suggestions: list[TableSuggestion]
    ai_enabled: bool
    message: str | None = None


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    """Lädt ein Restaurant oder wirft 404."""
    result = await session.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


@router.post("/suggest-table", response_model=SuggestTableResponse)
async def suggest_table(
    restaurant_id: int,
    request: SuggestTableRequest = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """
    Schlägt die wahrscheinlichsten Tische für eine neue Bestellung vor.

    Verwendet KI um basierend auf:
    - Aktiven Reservierungen
    - Belegten Tischen
    - Offenen Bestellungen

    die Top-3 Tische zu empfehlen.

    Args:
        restaurant_id: ID des Restaurants
        request: Optional mit context_hint (z.B. Gästename)

    Returns:
        Liste von bis zu 3 Tischvorschlägen mit Confidence-Score
    """
    # Prüfe ob AI Service verfügbar ist
    if not ai_service.is_enabled:
        return SuggestTableResponse(
            suggestions=[],
            ai_enabled=False,
            message="AI Service ist nicht aktiviert. Bitte OPENAI_API_KEY konfigurieren.",
        )

    # Prüfe Restaurant
    await _get_restaurant_or_404(restaurant_id, session)

    # Berechne Tagesbereich für Reservierungen
    today = date.today()
    start_of_day = datetime.combine(today, datetime.min.time()).replace(tzinfo=UTC)
    end_of_day = datetime.combine(today, datetime.max.time()).replace(tzinfo=UTC)

    # Lade Tische
    tables_result = await session.execute(
        select(Table).where(
            and_(
                Table.restaurant_id == restaurant_id,
                Table.is_active == True,
            )
        )
    )
    tables = tables_result.scalars().all()

    # Lade aktive Reservierungen für heute
    reservations_result = await session.execute(
        select(Reservation).where(
            and_(
                Reservation.restaurant_id == restaurant_id,
                Reservation.start_at >= start_of_day,
                Reservation.start_at <= end_of_day,
                Reservation.status.in_(["confirmed", "seated"]),
            )
        )
    )
    reservations = reservations_result.scalars().all()

    # Lade offene Bestellungen
    orders_result = await session.execute(
        select(Order).where(
            and_(
                Order.restaurant_id == restaurant_id,
                Order.status.not_in(["paid", "canceled"]),
            )
        )
    )
    orders = orders_result.scalars().all()

    # Lade Order Items count für jede Bestellung
    order_items_count = {}
    if orders:
        order_ids = [o.id for o in orders]
        from sqlalchemy import func

        items_result = await session.execute(
            select(OrderItem.order_id, func.count(OrderItem.id))
            .where(OrderItem.order_id.in_(order_ids))
            .group_by(OrderItem.order_id)
        )
        order_items_count = dict(items_result.all())

    # Konvertiere zu Dicts für den AI Service
    def table_to_dict(t: Table) -> dict:
        return {
            "id": t.id,
            "number": t.number,
            "capacity": t.capacity,
            "is_active": t.is_active,
        }

    def reservation_to_dict(r: Reservation) -> dict:
        return {
            "id": r.id,
            "table_id": r.table_id,
            "guest_name": r.guest_name,
            "party_size": r.party_size,
            "status": r.status,
            "start_at": r.start_at.isoformat() if r.start_at else None,
            "end_at": r.end_at.isoformat() if r.end_at else None,
        }

    def order_to_dict(o: Order) -> dict:
        return {
            "id": o.id,
            "table_id": o.table_id,
            "status": o.status,
            "items": [None] * order_items_count.get(o.id, 0),  # Dummy list for count
        }

    tables_data = [table_to_dict(t) for t in tables]
    reservations_data = [reservation_to_dict(r) for r in reservations]
    orders_data = [order_to_dict(o) for o in orders]

    # Baue Kontext
    context = ai_service.build_context_from_data(
        tables=tables_data,
        reservations=reservations_data,
        orders=orders_data,
        context_hint=request.context_hint if request else None,
    )

    logger.info(
        f"AI suggest-table for restaurant {restaurant_id}: "
        f"{len(tables)} tables, {len(reservations)} reservations, {len(orders)} orders"
    )

    # Hole Vorschläge von der KI
    suggestions = await ai_service.suggest_tables(context)

    return SuggestTableResponse(
        suggestions=suggestions,
        ai_enabled=True,
        message=None if suggestions else "Keine Vorschläge verfügbar",
    )


@router.get("/status")
async def get_ai_status(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Gibt den Status des AI Services zurück.

    Nützlich um im Frontend zu prüfen, ob AI-Features verfügbar sind.
    """
    await _get_restaurant_or_404(restaurant_id, session)

    return {
        "ai_enabled": ai_service.is_enabled,
        "features": {
            "table_suggestions": ai_service.is_enabled,
        },
    }
