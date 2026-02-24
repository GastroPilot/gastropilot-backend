from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_staff_or_above
from app.models.reservation import Guest, Reservation
from app.models.user import User
from app.schemas.reservation import (
    ReservationCreate,
    ReservationResponse,
    ReservationUpdate,
    TimeSlot,
    TimeSlotRequest,
)
from app.services.reservation_service import (
    DEFAULT_DURATION_MINUTES,
    find_available_table,
    get_available_timeslots,
)

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.get("/", response_model=list[ReservationResponse])
async def list_reservations(
    date: str | None = Query(None, description="YYYY-MM-DD"),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    query = select(Reservation)
    filters = []

    if date:
        from datetime import UTC, datetime

        day_start = datetime.fromisoformat(date).replace(tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        filters.append(Reservation.starts_at >= day_start)
        filters.append(Reservation.starts_at < day_end)

    if status:
        filters.append(Reservation.status == status)

    if filters:
        query = query.where(and_(*filters))

    query = query.order_by(Reservation.starts_at)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/", response_model=ReservationResponse, status_code=status.HTTP_201_CREATED)
async def create_reservation(
    request: Request,
    body: ReservationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
    # Gast erstellen oder finden
    guest_id = body.guest_id
    if not guest_id and body.guest_name:
        guest = Guest(
            name=body.guest_name,
            email=body.guest_email,
            phone=body.guest_phone,
        )
        db.add(guest)
        await db.flush()
        guest_id = guest.id

    # Tisch automatisch zuweisen falls keiner angegeben
    table_id = body.table_id
    if not table_id:
        ends_at = body.ends_at or (body.starts_at + timedelta(minutes=DEFAULT_DURATION_MINUTES))
        table = await find_available_table(
            db,
            effective_tenant_id,
            body.starts_at,
            ends_at,
            body.party_size,
        )
        if table:
            table_id = table.id

    reservation = Reservation(
        tenant_id=effective_tenant_id,
        guest_id=guest_id,
        table_id=table_id,
        party_size=body.party_size,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        notes=body.notes,
        source=body.source,
        status="confirmed",
    )
    db.add(reservation)
    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.get("/timeslots", response_model=list[TimeSlot])
async def get_timeslots(
    request: Request,
    date: str = Query(..., description="YYYY-MM-DD"),
    party_size: int = Query(..., ge=1),
    duration_minutes: int = Query(DEFAULT_DURATION_MINUTES, ge=15, le=360),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
    from datetime import date as date_type

    target_date = date_type.fromisoformat(date)
    return await get_available_timeslots(
        db,
        effective_tenant_id,
        target_date,
        party_size,
        duration_minutes,
    )


@router.get("/{reservation_id}", response_model=ReservationResponse)
async def get_reservation(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservierung nicht gefunden")
    return reservation


@router.patch("/{reservation_id}", response_model=ReservationResponse)
async def update_reservation(
    reservation_id: UUID,
    body: ReservationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservierung nicht gefunden")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(reservation, field, value)

    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.delete("/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_reservation(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservierung nicht gefunden")

    reservation.status = "cancelled"
    await db.commit()
