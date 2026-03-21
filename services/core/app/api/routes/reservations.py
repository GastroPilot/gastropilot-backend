from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_staff_or_above
from app.models.reservation import Guest, Reservation
from app.models.restaurant import Restaurant, Table
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
    get_available_timeslots,
)

router = APIRouter(prefix="/reservations", tags=["reservations"])


class ReservationCancelRequest(BaseModel):
    canceled_reason: str | None = None


def _split_guest_name(name: str | None) -> tuple[str, str]:
    cleaned = (name or "").strip()
    if not cleaned:
        return "Gast", ""
    parts = cleaned.split(" ", 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _require_tenant_context(request: Request, current_user: User) -> UUID:
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
    if not effective_tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return effective_tenant_id


async def _resolve_tenant_context_for_create(
    request: Request,
    current_user: User,
    db: AsyncSession,
    requested_tenant_id: UUID | None,
    table_id: UUID | None,
    guest_id: UUID | None,
) -> UUID:
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
    if effective_tenant_id:
        if requested_tenant_id and requested_tenant_id != effective_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Requested restaurant_id does not match tenant context",
            )
        return effective_tenant_id

    if current_user.role != "platform_admin":
        raise HTTPException(status_code=403, detail="User has no tenant context")

    if requested_tenant_id:
        restaurant_result = await db.execute(
            select(Restaurant.id).where(Restaurant.id == requested_tenant_id)
        )
        if restaurant_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Restaurant not found")
        return requested_tenant_id

    if table_id:
        table_tenant_result = await db.execute(select(Table.tenant_id).where(Table.id == table_id))
        table_tenant_id = table_tenant_result.scalar_one_or_none()
        if table_tenant_id:
            return table_tenant_id

    if guest_id:
        guest_tenant_result = await db.execute(select(Guest.tenant_id).where(Guest.id == guest_id))
        guest_tenant_id = guest_tenant_result.scalar_one_or_none()
        if guest_tenant_id:
            return guest_tenant_id

    raise HTTPException(
        status_code=400,
        detail=(
            "Tenant context required (token has no tenant and no table/guest tenant "
            "could be resolved)"
        ),
    )


def _reservation_to_dict(r: Reservation) -> dict:
    return {
        "id": str(r.id),
        "tenant_id": str(r.tenant_id),
        "guest_id": str(r.guest_id) if r.guest_id else None,
        "table_id": str(r.table_id) if r.table_id else None,
        "party_size": r.party_size,
        "starts_at": r.start_at.isoformat() if r.start_at else None,
        "ends_at": r.end_at.isoformat() if r.end_at else None,
        "start_at": r.start_at.isoformat() if r.start_at else None,
        "end_at": r.end_at.isoformat() if r.end_at else None,
        "status": r.status,
        "notes": r.notes,
        "special_requests": r.special_requests,
        "guest_name": r.guest_name,
        "guest_email": r.guest_email,
        "guest_phone": r.guest_phone,
        "confirmation_code": r.confirmation_code,
        "channel": r.channel,
        "tags": r.tags or [],
        "source": r.channel,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("/")
async def list_reservations(
    request: Request,
    date: str | None = Query(None, description="YYYY-MM-DD"),
    from_dt: str | None = Query(None, alias="from", description="ISO datetime"),
    to_dt: str | None = Query(None, alias="to", description="ISO datetime"),
    status_filter: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    from datetime import UTC
    from datetime import datetime as dt

    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
    query = select(Reservation)
    if effective_tenant_id:
        query = query.where(Reservation.tenant_id == effective_tenant_id)
    elif current_user.role != "platform_admin":
        raise HTTPException(status_code=400, detail="Tenant context required")
    filters = []

    if from_dt and to_dt:
        start = dt.fromisoformat(from_dt.replace("Z", "+00:00"))
        end = dt.fromisoformat(to_dt.replace("Z", "+00:00"))
        filters.append(Reservation.start_at >= start)
        filters.append(Reservation.start_at <= end)
    elif date:
        day_start = dt.fromisoformat(date).replace(tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        filters.append(Reservation.start_at >= day_start)
        filters.append(Reservation.start_at < day_end)

    if status_filter:
        filters.append(Reservation.status == status_filter)

    if filters:
        query = query.where(and_(*filters))

    query = query.order_by(Reservation.start_at)
    result = await db.execute(query)
    reservations = result.scalars().all()

    return [_reservation_to_dict(r) for r in reservations]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_reservation(
    request: Request,
    body: ReservationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_create(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=body.restaurant_id,
        table_id=body.table_id,
        guest_id=body.guest_id,
    )
    # Gast erstellen oder finden
    guest_id = body.guest_id
    if not guest_id and body.guest_name:
        first_name, last_name = _split_guest_name(body.guest_name)
        guest = Guest(
            tenant_id=effective_tenant_id,
            first_name=first_name,
            last_name=last_name,
            email=body.guest_email,
            phone=body.guest_phone,
        )
        db.add(guest)
        await db.flush()
        guest_id = guest.id

    # Kein automatisches Tisch-Matching mehr im Staff-Flow:
    # Ohne explizite Tischwahl bleibt die Reservierung unzugewiesen.
    table_id = body.table_id

    reservation = Reservation(
        tenant_id=effective_tenant_id,
        guest_id=guest_id,
        table_id=table_id,
        party_size=body.party_size,
        start_at=body.starts_at,
        end_at=body.ends_at or (body.starts_at + timedelta(minutes=DEFAULT_DURATION_MINUTES)),
        notes=body.notes,
        special_requests=body.special_requests,
        channel=body.source,
        guest_name=body.guest_name,
        guest_email=body.guest_email,
        guest_phone=body.guest_phone,
        tags=body.tags or [],
        status=body.status,
    )
    db.add(reservation)
    await db.commit()
    await db.refresh(reservation)
    return _reservation_to_dict(reservation)


@router.get("/timeslots", response_model=list[TimeSlot])
async def get_timeslots(
    request: Request,
    date: str = Query(..., description="YYYY-MM-DD"),
    party_size: int = Query(..., ge=1),
    duration_minutes: int = Query(DEFAULT_DURATION_MINUTES, ge=15, le=360),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = _require_tenant_context(request, current_user)
    from datetime import date as date_type

    target_date = date_type.fromisoformat(date)
    return await get_available_timeslots(
        db,
        effective_tenant_id,
        target_date,
        party_size,
        duration_minutes,
    )


@router.get("/{reservation_id}")
async def get_reservation(
    request: Request,
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = _require_tenant_context(request, current_user)
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservierung nicht gefunden")
    if reservation.tenant_id != effective_tenant_id:
        raise HTTPException(status_code=404, detail="Reservierung nicht gefunden")
    return _reservation_to_dict(reservation)


@router.patch("/{reservation_id}")
async def update_reservation(
    request: Request,
    reservation_id: UUID,
    body: ReservationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = _require_tenant_context(request, current_user)
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservierung nicht gefunden")
    if reservation.tenant_id != effective_tenant_id:
        raise HTTPException(status_code=404, detail="Reservierung nicht gefunden")

    update_data = body.model_dump(exclude_none=True)
    # Map schema field names to model field names
    field_map = {"starts_at": "start_at", "ends_at": "end_at"}
    for field, value in update_data.items():
        model_field = field_map.get(field, field)
        setattr(reservation, model_field, value)

    await db.commit()
    await db.refresh(reservation)
    return _reservation_to_dict(reservation)


@router.delete("/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reservation(
    request: Request,
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = _require_tenant_context(request, current_user)
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservierung nicht gefunden")
    if reservation.tenant_id != effective_tenant_id:
        raise HTTPException(status_code=404, detail="Reservierung nicht gefunden")

    await db.delete(reservation)
    await db.commit()


@router.post("/{reservation_id}/cancel")
async def cancel_reservation_post(
    request: Request,
    reservation_id: UUID,
    body: ReservationCancelRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = _require_tenant_context(request, current_user)
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservierung nicht gefunden")
    if reservation.tenant_id != effective_tenant_id:
        raise HTTPException(status_code=404, detail="Reservierung nicht gefunden")

    reservation.status = "canceled"
    reservation.canceled_at = datetime.now(UTC)
    reservation.canceled_reason = body.canceled_reason
    await db.commit()
    await db.refresh(reservation)
    return _reservation_to_dict(reservation)
