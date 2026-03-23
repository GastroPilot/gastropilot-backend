from __future__ import annotations

from datetime import UTC, date as date_type, datetime
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reservation import Reservation
from app.models.restaurant import Table
from app.models.table_config import ReservationTable, TableDayConfig

ACTIVE_RESERVATION_STATUSES = ("pending", "confirmed", "seated")


def _normalize_reference_date(reference_start_at: datetime) -> date_type:
    if reference_start_at.tzinfo is None:
        return reference_start_at.date()
    return reference_start_at.astimezone(UTC).date()


def _deduplicate_table_ids(table_ids: list[UUID]) -> list[UUID]:
    deduped: list[UUID] = []
    seen: set[UUID] = set()
    for table_id in table_ids:
        if table_id in seen:
            continue
        seen.add(table_id)
        deduped.append(table_id)
    return deduped


async def resolve_group_table_ids(
    session: AsyncSession,
    tenant_id: UUID,
    table_id: UUID,
    reference_start_at: datetime,
) -> list[UUID]:
    table_result = await session.execute(
        select(Table).where(and_(Table.id == table_id, Table.tenant_id == tenant_id))
    )
    table = table_result.scalar_one_or_none()
    if table is None:
        raise ValueError("Table not found")

    target_date = _normalize_reference_date(reference_start_at)

    day_config_result = await session.execute(
        select(TableDayConfig.id, TableDayConfig.join_group_id).where(
            and_(
                TableDayConfig.tenant_id == tenant_id,
                TableDayConfig.table_id == table.id,
                TableDayConfig.date == target_date,
            )
        )
    )
    day_config_row = day_config_result.first()
    if day_config_row is not None:
        effective_group_id = day_config_row[1]
    else:
        effective_group_id = table.join_group_id
    if effective_group_id is None:
        return [table.id]

    day_group_result = await session.execute(
        select(TableDayConfig.table_id).where(
            and_(
                TableDayConfig.tenant_id == tenant_id,
                TableDayConfig.date == target_date,
                TableDayConfig.join_group_id == effective_group_id,
                TableDayConfig.table_id.is_not(None),
                TableDayConfig.is_hidden.is_(False),
                or_(TableDayConfig.is_active.is_(None), TableDayConfig.is_active.is_(True)),
            )
        )
    )
    day_group_table_ids = [
        table_id
        for table_id in day_group_result.scalars().all()
        if table_id is not None
    ]
    if day_group_table_ids:
        return _deduplicate_table_ids([table.id, *day_group_table_ids])

    permanent_group_result = await session.execute(
        select(Table.id).where(
            and_(
                Table.tenant_id == tenant_id,
                Table.join_group_id == effective_group_id,
                Table.is_active.is_(True),
            )
        )
    )
    permanent_group_table_ids = permanent_group_result.scalars().all()
    if not permanent_group_table_ids:
        return [table.id]

    return _deduplicate_table_ids([table.id, *permanent_group_table_ids])


async def sync_reservation_table_links(
    session: AsyncSession,
    reservation: Reservation,
    table_ids: list[UUID],
) -> None:
    await session.execute(
        delete(ReservationTable).where(
            ReservationTable.reservation_id == reservation.id,
        )
    )

    if not table_ids:
        return

    resolved_ids = _deduplicate_table_ids(table_ids)
    links = [
        ReservationTable(
            reservation_id=reservation.id,
            table_id=table_id,
            tenant_id=reservation.tenant_id,
            start_at=reservation.start_at,
            end_at=reservation.end_at,
        )
        for table_id in resolved_ids
    ]
    session.add_all(links)


async def fetch_reservation_table_ids_map(
    session: AsyncSession,
    tenant_id: UUID,
    reservation_ids: list[UUID],
) -> dict[str, list[str]]:
    if not reservation_ids:
        return {}

    result = await session.execute(
        select(ReservationTable.reservation_id, ReservationTable.table_id).where(
            and_(
                ReservationTable.tenant_id == tenant_id,
                ReservationTable.reservation_id.in_(reservation_ids),
            )
        )
    )

    mapping: dict[str, list[str]] = {}
    for reservation_id, table_id in result.all():
        key = str(reservation_id)
        values = mapping.get(key)
        if values is None:
            values = []
            mapping[key] = values
        table_id_str = str(table_id)
        if table_id_str not in values:
            values.append(table_id_str)

    return mapping


async def fetch_reserved_table_ids(
    session: AsyncSession,
    tenant_id: UUID,
    start_at: datetime,
    end_at: datetime,
    exclude_reservation_id: UUID | None = None,
) -> set[UUID]:
    reserved_table_ids: set[UUID] = set()

    grouped_query = select(ReservationTable.table_id).join(
        Reservation,
        Reservation.id == ReservationTable.reservation_id,
    )
    grouped_query = grouped_query.where(
        and_(
            ReservationTable.tenant_id == tenant_id,
            Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            ReservationTable.start_at < end_at,
            ReservationTable.end_at > start_at,
        )
    )
    if exclude_reservation_id is not None:
        grouped_query = grouped_query.where(ReservationTable.reservation_id != exclude_reservation_id)

    grouped_result = await session.execute(grouped_query)
    reserved_table_ids.update(grouped_result.scalars().all())

    legacy_query = select(Reservation.table_id).where(
        and_(
            Reservation.tenant_id == tenant_id,
            Reservation.table_id.is_not(None),
            Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            Reservation.start_at < end_at,
            Reservation.end_at > start_at,
        )
    )
    if exclude_reservation_id is not None:
        legacy_query = legacy_query.where(Reservation.id != exclude_reservation_id)

    legacy_result = await session.execute(legacy_query)
    reserved_table_ids.update(
        table_id for table_id in legacy_result.scalars().all() if table_id is not None
    )

    return reserved_table_ids
