"""CRM/Guests API endpoints for staff."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_manager_or_above
from app.models.reservation import Guest, Reservation
from app.schemas.guests import (
    GuestDetailResponse,
    GuestListResponse,
    GuestStatsResponse,
    GuestUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/guests", tags=["guests-crm"])


@router.get("", response_model=list[GuestListResponse])
async def list_guests(
    q: str | None = Query(None, description="Search query"),
    sort_by: str = Query("last_visit", description="Sort field"),
    sort_dir: str = Query("desc", description="Sort direction"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    """List guests with search/filter/sort/pagination."""
    tenant_id = current_user.tenant_id
    query = select(Guest).where(Guest.tenant_id == tenant_id)

    if q:
        search = f"%{q}%"
        query = query.where(
            Guest.first_name.ilike(search)
            | Guest.last_name.ilike(search)
            | Guest.email.ilike(search)
            | Guest.phone.ilike(search)
        )

    # Sort
    if sort_by == "name":
        order_col = Guest.last_name
    elif sort_by == "created_at":
        order_col = Guest.created_at
    else:
        order_col = Guest.updated_at

    if sort_dir == "asc":
        query = query.order_by(order_col.asc())
    else:
        query = query.order_by(order_col.desc())

    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    guests = result.scalars().all()

    responses = []
    for g in guests:
        # Count reservations for visit count
        visit_result = await db.execute(
            select(func.count(Reservation.id)).where(
                and_(
                    Reservation.guest_id == g.id,
                    Reservation.status.in_(["completed", "seated"]),
                )
            )
        )
        visit_count = visit_result.scalar() or 0

        # Last visit
        last_result = await db.execute(
            select(Reservation.start_at)
            .where(
                and_(
                    Reservation.guest_id == g.id,
                    Reservation.status.in_(["completed", "seated"]),
                )
            )
            .order_by(Reservation.start_at.desc())
            .limit(1)
        )
        last_visit_row = last_result.scalar_one_or_none()

        tags = []
        if g.type:
            tags.append(g.type)

        responses.append(
            GuestListResponse(
                id=g.id,
                name=f"{g.first_name} {g.last_name}",
                email=g.email,
                phone=g.phone,
                visit_count=visit_count,
                last_visit=last_visit_row,
                is_regular=visit_count >= 5,
                tags=tags,
            )
        )

    return responses


@router.get("/stats", response_model=GuestStatsResponse)
async def get_guest_stats(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    """CRM statistics: total guests, regulars, new this month."""
    tenant_id = current_user.tenant_id

    # Total guests
    total_result = await db.execute(
        select(func.count(Guest.id)).where(Guest.tenant_id == tenant_id)
    )
    total = total_result.scalar() or 0

    # New this month
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_result = await db.execute(
        select(func.count(Guest.id)).where(
            and_(
                Guest.tenant_id == tenant_id,
                Guest.created_at >= month_start,
            )
        )
    )
    new_this_month = new_result.scalar() or 0

    # Regulars: guests with 5+ completed reservations
    regulars_subq = (
        select(Reservation.guest_id)
        .where(
            and_(
                Reservation.tenant_id == tenant_id,
                Reservation.status.in_(["completed", "seated"]),
            )
        )
        .group_by(Reservation.guest_id)
        .having(func.count(Reservation.id) >= 5)
    )
    regulars_result = await db.execute(select(func.count()).select_from(regulars_subq.subquery()))
    regulars = regulars_result.scalar() or 0

    return GuestStatsResponse(
        total=total,
        regulars=regulars,
        new_this_month=new_this_month,
    )


@router.get("/{guest_id}", response_model=GuestDetailResponse)
async def get_guest_detail(
    guest_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    """Guest detail with reservation history."""
    result = await db.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    # Reservation history
    res_result = await db.execute(
        select(Reservation)
        .where(Reservation.guest_id == guest_id)
        .order_by(Reservation.start_at.desc())
        .limit(50)
    )
    reservations = res_result.scalars().all()

    visit_count = sum(1 for r in reservations if r.status in ("completed", "seated"))

    last_visit = None
    for r in reservations:
        if r.status in ("completed", "seated"):
            last_visit = r.start_at
            break

    reservation_history = [
        {
            "id": str(r.id),
            "date": r.start_at.isoformat() if r.start_at else None,
            "party_size": r.party_size,
            "status": r.status,
        }
        for r in reservations
    ]

    tags = []
    if guest.type:
        tags.append(guest.type)

    # Fetch order history
    order_result = await db.execute(
        text(
            "SELECT id, order_number, status, total, opened_at, closed_at "
            "FROM orders WHERE guest_id = :guest_id "
            "ORDER BY opened_at DESC LIMIT 50"
        ),
        {"guest_id": guest_id},
    )
    order_rows = order_result.all()
    order_history = [
        {
            "id": str(o.id),
            "order_number": o.order_number,
            "status": o.status,
            "total": float(o.total) if o.total else 0.0,
            "opened_at": o.opened_at.isoformat() if o.opened_at else None,
            "closed_at": o.closed_at.isoformat() if o.closed_at else None,
        }
        for o in order_rows
    ]
    total_spend = sum(o["total"] for o in order_history)

    return GuestDetailResponse(
        id=guest.id,
        name=f"{guest.first_name} {guest.last_name}",
        email=guest.email,
        phone=guest.phone,
        visit_count=visit_count,
        last_visit=last_visit,
        is_regular=visit_count >= 5,
        tags=tags,
        notes=guest.notes,
        reservation_history=reservation_history,
        order_history=order_history,
        total_spend=total_spend,
    )


@router.get("/{guest_id}/history")
async def get_guest_history(
    guest_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    """Reservation + order history for a guest."""
    result = await db.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    res_result = await db.execute(
        select(Reservation)
        .where(Reservation.guest_id == guest_id)
        .order_by(Reservation.start_at.desc())
    )
    reservations = res_result.scalars().all()

    return {
        "guest_id": str(guest_id),
        "reservations": [
            {
                "id": str(r.id),
                "date": (r.start_at.isoformat() if r.start_at else None),
                "party_size": r.party_size,
                "status": r.status,
                "notes": r.notes,
            }
            for r in reservations
        ],
        "orders": [
            {
                "id": str(o.id),
                "order_number": o.order_number,
                "status": o.status,
                "total": float(o.total) if o.total else 0.0,
                "opened_at": o.opened_at.isoformat() if o.opened_at else None,
            }
            for o in (
                await db.execute(
                    text(
                        "SELECT id, order_number, status, total, opened_at "
                        "FROM orders WHERE guest_id = :gid "
                        "ORDER BY opened_at DESC LIMIT 50"
                    ),
                    {"gid": guest_id},
                )
            ).all()
        ],
    }


@router.patch("/{guest_id}")
async def update_guest(
    guest_id: UUID,
    body: GuestUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    """Update guest notes/tags."""
    result = await db.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    if body.notes is not None:
        guest.notes = body.notes
    if body.type is not None:
        guest.type = body.type

    await db.commit()

    return {
        "id": str(guest.id),
        "notes": guest.notes,
        "type": guest.type,
    }
