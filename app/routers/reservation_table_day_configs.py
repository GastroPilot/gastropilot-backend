from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Reservation,
    ReservationTableDayConfig,
    Restaurant,
    TableDayConfig,
    User,
)
from app.dependencies import (
    get_session,
    normalize_datetime_to_utc,
    require_mitarbeiter_role,
    require_reservations_module,
)
from app.schemas import ReservationTableDayConfigCreate, ReservationTableDayConfigRead

router = APIRouter(
    prefix="/restaurants/{restaurant_id}/reservation-table-day-configs",
    tags=["reservation_table_day_configs"],
)


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


@router.post("/", response_model=ReservationTableDayConfigRead, status_code=status.HTTP_201_CREATED)
async def add_reservation_table_day_config(
    restaurant_id: int,
    body: ReservationTableDayConfigCreate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Fügt eine Reservierung einem temporären Tisch (TableDayConfig) hinzu."""
    await _get_restaurant_or_404(restaurant_id, session)
    reservation = await session.get(Reservation, body.reservation_id)
    if not reservation or reservation.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    table_day_config = await session.get(TableDayConfig, body.table_day_config_id)
    if not table_day_config or table_day_config.restaurant_id != restaurant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Table day config not found"
        )
    if not table_day_config.is_temporary:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Table day config must be temporary"
        )

    start_at = normalize_datetime_to_utc(body.start_at)
    end_at = normalize_datetime_to_utc(body.end_at)
    if start_at >= end_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="End time must be after start time"
        )

    # Prüfe, ob die Reservierung bereits diesem temporären Tisch zugewiesen ist
    existing = await session.get(ReservationTableDayConfig, (reservation.id, table_day_config.id))
    if existing:
        # Aktualisiere die Zeiten
        existing.start_at = start_at
        existing.end_at = end_at
        try:
            await session.commit()
            await session.refresh(existing)
            return existing
        except IntegrityError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Reservation-table day config conflict"
            )

    rt = ReservationTableDayConfig(
        reservation_id=reservation.id,
        table_day_config_id=table_day_config.id,
        start_at=start_at,
        end_at=end_at,
    )
    session.add(rt)

    try:
        await session.commit()
        await session.refresh(rt)
        return rt
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Reservation-table day config conflict"
        )


@router.get("/", response_model=list[ReservationTableDayConfigRead])
async def list_reservation_table_day_configs(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Listet alle Zuordnungen zwischen Reservierungen und temporären Tischen für ein Restaurant."""
    await _get_restaurant_or_404(restaurant_id, session)
    result = await session.execute(
        select(ReservationTableDayConfig)
        .join(Reservation, Reservation.id == ReservationTableDayConfig.reservation_id)
        .join(TableDayConfig, TableDayConfig.id == ReservationTableDayConfig.table_day_config_id)
        .where(Reservation.restaurant_id == restaurant_id)
    )
    return result.scalars().all()


@router.delete("/", status_code=status.HTTP_200_OK)
async def remove_reservation_table_day_config(
    restaurant_id: int,
    reservation_id: int,
    table_day_config_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Entfernt eine Reservierung von einem temporären Tisch."""
    await _get_restaurant_or_404(restaurant_id, session)
    table_day_config = await session.get(TableDayConfig, table_day_config_id)
    if not table_day_config or table_day_config.restaurant_id != restaurant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Table day config not found"
        )

    rt = await session.get(ReservationTableDayConfig, (reservation_id, table_day_config_id))
    if not rt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation-table day config mapping not found",
        )

    await session.delete(rt)

    try:
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise
    return {"message": "deleted"}


@router.get("/by-reservation/{reservation_id}", response_model=list[ReservationTableDayConfigRead])
async def get_reservation_table_day_configs_by_reservation(
    restaurant_id: int,
    reservation_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Holt alle temporären Tisch-Zuordnungen für eine Reservierung."""
    await _get_restaurant_or_404(restaurant_id, session)
    reservation = await session.get(Reservation, reservation_id)
    if not reservation or reservation.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    result = await session.execute(
        select(ReservationTableDayConfig).where(
            ReservationTableDayConfig.reservation_id == reservation_id
        )
    )
    return result.scalars().all()


@router.get(
    "/by-table-day-config/{table_day_config_id}", response_model=list[ReservationTableDayConfigRead]
)
async def get_reservation_table_day_configs_by_table_day_config(
    restaurant_id: int,
    table_day_config_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Holt alle Reservierungs-Zuordnungen für einen temporären Tisch."""
    await _get_restaurant_or_404(restaurant_id, session)
    table_day_config = await session.get(TableDayConfig, table_day_config_id)
    if not table_day_config or table_day_config.restaurant_id != restaurant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Table day config not found"
        )

    result = await session.execute(
        select(ReservationTableDayConfig).where(
            ReservationTableDayConfig.table_day_config_id == table_day_config_id
        )
    )
    return result.scalars().all()
