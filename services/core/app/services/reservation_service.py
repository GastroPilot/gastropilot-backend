from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reservation import Reservation
from app.models.restaurant import Table
from app.schemas.reservation import TimeSlot
from app.services.table_group_service import (
    fetch_reservation_table_ids_map,
    fetch_reserved_table_ids,
)

logger = logging.getLogger(__name__)

# Standardmäßige Slot-Konfiguration
DEFAULT_SLOT_INTERVAL_MINUTES = 30
DEFAULT_DURATION_MINUTES = 90
OPENING_HOUR = 11
CLOSING_HOUR = 23


async def get_available_timeslots(
    session: AsyncSession,
    tenant_id: UUID,
    target_date: date,
    party_size: int,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
) -> list[TimeSlot]:
    """
    Berechnet verfügbare Zeitslots für ein gegebenes Datum und eine Personenanzahl.
    Berücksichtigt bestehende Reservierungen und Tischkapazitäten.
    """
    # Tische laden, die groß genug sind
    tables_result = await session.execute(
        select(Table).where(
            and_(
                Table.tenant_id == tenant_id,
                Table.capacity >= party_size,
                Table.is_active.is_(True),
            )
        )
    )
    suitable_tables = tables_result.scalars().all()

    if not suitable_tables:
        return []

    # Bestehende Reservierungen für den Tag laden
    day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)

    reservations_result = await session.execute(
        select(Reservation).where(
            and_(
                Reservation.tenant_id == tenant_id,
                Reservation.start_at >= day_start,
                Reservation.start_at < day_end,
                Reservation.status.in_(["pending", "confirmed", "seated"]),
            )
        )
    )
    existing_reservations = reservations_result.scalars().all()
    reservation_ids = [reservation.id for reservation in existing_reservations]
    reservation_table_id_map = await fetch_reservation_table_ids_map(
        session,
        tenant_id,
        reservation_ids,
    )

    # Zeitslots generieren
    slots = []
    current_time = datetime(
        target_date.year, target_date.month, target_date.day, OPENING_HOUR, 0, tzinfo=UTC
    )
    end_of_service = datetime(
        target_date.year, target_date.month, target_date.day, CLOSING_HOUR, 0, tzinfo=UTC
    )
    slot_end = end_of_service - timedelta(minutes=duration_minutes)

    while current_time <= slot_end:
        slot_end_time = current_time + timedelta(minutes=duration_minutes)
        available_count = 0

        for table in suitable_tables:
            # Prüfe ob dieser Tisch in dem Zeitfenster frei ist
            conflict = False
            for res in existing_reservations:
                affected_table_ids = reservation_table_id_map.get(str(res.id))
                if affected_table_ids:
                    if str(table.id) not in affected_table_ids:
                        continue
                elif res.table_id != table.id:
                    continue
                res_end = res.end_at or (res.start_at + timedelta(minutes=DEFAULT_DURATION_MINUTES))
                # Überlappungs-Check
                if not (slot_end_time <= res.start_at or current_time >= res_end):
                    conflict = True
                    break
            if not conflict:
                available_count += 1

        slots.append(
            TimeSlot(
                starts_at=current_time,
                ends_at=slot_end_time,
                available=available_count > 0,
                available_tables=available_count,
            )
        )

        current_time += timedelta(minutes=DEFAULT_SLOT_INTERVAL_MINUTES)

    return slots


async def find_available_table(
    session: AsyncSession,
    tenant_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    party_size: int,
) -> Table | None:
    """Findet den passendsten freien Tisch für eine Reservierung."""
    tables_result = await session.execute(
        select(Table)
        .where(
            and_(
                Table.tenant_id == tenant_id,
                Table.capacity >= party_size,
                Table.is_active.is_(True),
            )
        )
        .order_by(Table.capacity)  # kleinsten passenden zuerst
    )
    suitable_tables = tables_result.scalars().all()
    if not suitable_tables:
        return None

    reserved_table_ids = await fetch_reserved_table_ids(session, tenant_id, starts_at, ends_at)
    for table in suitable_tables:
        if table.id not in reserved_table_ids:
            return table

    return None
