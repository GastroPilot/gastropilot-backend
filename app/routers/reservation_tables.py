from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Reservation, ReservationTable, Restaurant, Table, User
from app.dependencies import (
    get_session,
    normalize_datetime_to_utc,
    require_mitarbeiter_role,
    require_reservations_module,
)
from app.schemas import ReservationTableCreate, ReservationTableRead

router = APIRouter(
    prefix="/restaurants/{restaurant_id}/reservation-tables", tags=["reservation_tables"]
)


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


@router.post("/", response_model=ReservationTableRead, status_code=status.HTTP_201_CREATED)
async def add_reservation_table(
    restaurant_id: int,
    body: ReservationTableCreate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Fügt eine Reservierung einem Tisch hinzu. Wenn der Tisch in einer Gruppe ist, wird die Reservierung auch allen anderen Tischen der Gruppe zugewiesen."""
    await _get_restaurant_or_404(restaurant_id, session)
    reservation = await session.get(Reservation, body.reservation_id)
    if not reservation or reservation.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    table = await session.get(Table, body.table_id)
    if not table or table.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")

    start_at = normalize_datetime_to_utc(body.start_at)
    end_at = normalize_datetime_to_utc(body.end_at)
    if start_at >= end_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="End time must be after start time"
        )

    tables_to_assign = [table]
    if table.join_group_id is not None:
        result = await session.execute(
            select(Table).where(
                Table.restaurant_id == restaurant_id,
                Table.join_group_id == table.join_group_id,
                Table.id != table.id,
            )
        )
        group_tables = result.scalars().all()
        tables_to_assign.extend(group_tables)

    created_rt = None
    for tbl in tables_to_assign:
        existing = await session.get(ReservationTable, (reservation.id, tbl.id))
        if existing:
            continue

        rt = ReservationTable(
            reservation_id=reservation.id,
            table_id=tbl.id,
            start_at=start_at,
            end_at=end_at,
        )
        session.add(rt)
        if tbl.id == table.id:
            created_rt = rt

    try:
        await session.commit()
        if created_rt:
            await session.refresh(created_rt)
            return created_rt
        else:
            existing_rt = await session.get(ReservationTable, (reservation.id, table.id))
            if existing_rt:
                return existing_rt
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create reservation table",
            )
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Reservation-table conflict"
        )


@router.get("/", response_model=list[ReservationTableRead])
async def list_reservation_tables(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    result = await session.execute(
        select(ReservationTable)
        .join(Reservation, Reservation.id == ReservationTable.reservation_id)
        .where(Reservation.restaurant_id == restaurant_id)
    )
    return result.scalars().all()


@router.delete("/", status_code=status.HTTP_200_OK)
async def remove_reservation_table(
    restaurant_id: int,
    reservation_id: int,
    table_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Entfernt eine Reservierung von einem Tisch. Wenn der Tisch in einer Gruppe ist, wird die Reservierung auch von allen anderen Tischen der Gruppe entfernt."""
    await _get_restaurant_or_404(restaurant_id, session)
    table = await session.get(Table, table_id)
    if not table or table.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")

    rt = await session.get(ReservationTable, (reservation_id, table_id))
    if not rt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reservation-table mapping not found"
        )

    tables_to_remove = [table]
    if table.join_group_id is not None:
        result = await session.execute(
            select(Table).where(
                Table.restaurant_id == restaurant_id,
                Table.join_group_id == table.join_group_id,
                Table.id != table.id,
            )
        )
        group_tables = result.scalars().all()
        tables_to_remove.extend(group_tables)

    for tbl in tables_to_remove:
        rt_to_delete = await session.get(ReservationTable, (reservation_id, tbl.id))
        if rt_to_delete:
            await session.delete(rt_to_delete)

    try:
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise
    return {"message": "deleted"}
