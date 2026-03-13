"""Guest profile endpoints (protected by guest JWT)."""

from __future__ import annotations

import logging
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.guest_deps import get_current_guest
from app.models.guest_favorite import GuestFavorite
from app.models.reservation import Guest, Reservation
from app.models.restaurant import Restaurant
from app.models.review import Review
from app.models.user import GuestProfile
from app.schemas.guest_auth import (
    GuestProfileResponse,
    GuestProfileUpdateRequest,
)

RESTAURANT_TZ = ZoneInfo("Europe/Berlin")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/me", tags=["guest-profile"])


@router.get("", response_model=GuestProfileResponse)
async def get_guest_profile(
    guest: GuestProfile = Depends(get_current_guest),
):
    """Get the authenticated guest's profile."""
    return GuestProfileResponse(
        id=guest.id,
        first_name=guest.first_name,
        last_name=guest.last_name,
        email=guest.email,
        phone=guest.phone,
        allergen_profile=guest.allergen_profile,
        email_verified=guest.email_verified,
    )


@router.put("", response_model=GuestProfileResponse)
async def update_guest_profile(
    body: GuestProfileUpdateRequest,
    guest: GuestProfile = Depends(get_current_guest),
):
    """Update guest profile (name, phone, allergen_profile)."""
    from app.core.database import get_session_factories

    session_factory_app, _ = get_session_factories()
    async with session_factory_app() as session:
        result = await session.execute(select(GuestProfile).where(GuestProfile.id == guest.id))
        db_guest = result.scalar_one()

        if body.first_name is not None:
            db_guest.first_name = body.first_name
        if body.last_name is not None:
            db_guest.last_name = body.last_name
        if body.phone is not None:
            db_guest.phone = body.phone
        if body.allergen_profile is not None:
            db_guest.allergen_profile = body.allergen_profile

        await session.commit()
        await session.refresh(db_guest)

        return GuestProfileResponse(
            id=db_guest.id,
            first_name=db_guest.first_name,
            last_name=db_guest.last_name,
            email=db_guest.email,
            phone=db_guest.phone,
            allergen_profile=db_guest.allergen_profile,
            email_verified=db_guest.email_verified,
        )


@router.put("/push-token")
async def update_push_token(
    body: dict,
    guest: GuestProfile = Depends(get_current_guest),
):
    """Register or update push notification token."""
    from pydantic import BaseModel

    from app.core.database import get_session_factories

    token = body.get("push_token")
    if not token or not isinstance(token, str):
        raise HTTPException(status_code=400, detail="push_token is required")

    session_factory_app, _ = get_session_factories()
    async with session_factory_app() as session:
        result = await session.execute(select(GuestProfile).where(GuestProfile.id == guest.id))
        db_guest = result.scalar_one()
        db_guest.push_token = token
        await session.commit()

    return {"message": "Push token updated"}


@router.get("/reservations")
async def get_guest_reservations(
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """Get booking history across all restaurants."""
    # Find all tenant-level guest records linked to this profile
    guest_records = await db.execute(select(Guest).where(Guest.guest_profile_id == guest.id))
    guests = guest_records.scalars().all()
    guest_ids = [g.id for g in guests]

    if not guest_ids:
        return []

    result = await db.execute(
        select(Reservation, Restaurant)
        .join(Restaurant, Reservation.tenant_id == Restaurant.id)
        .where(Reservation.guest_id.in_(guest_ids))
        .order_by(Reservation.start_at.desc())
    )
    rows = result.all()

    return [
        {
            "id": str(r.id),
            "restaurant_id": str(r.tenant_id),
            "restaurant_name": rest.name,
            "restaurant_slug": rest.slug or "",
            "date": (
                r.start_at.astimezone(RESTAURANT_TZ).date().isoformat() if r.start_at else None
            ),
            "time": (
                r.start_at.astimezone(RESTAURANT_TZ).strftime("%H:%M") if r.start_at else None
            ),
            "party_size": r.party_size,
            "status": r.status,
            "guest_name": r.guest_name,
            "guest_email": r.guest_email,
            "guest_phone": r.guest_phone,
            "special_requests": r.special_requests,
            "confirmation_code": r.confirmation_code,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r, rest in rows
    ]


@router.post("/reservations/{reservation_id}/cancel")
async def cancel_guest_reservation(
    reservation_id: str,
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a reservation owned by the authenticated guest."""
    from uuid import UUID as PyUUID

    try:
        res_uuid = PyUUID(reservation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid reservation ID")

    # Find guest records linked to this profile
    guest_records = await db.execute(select(Guest).where(Guest.guest_profile_id == guest.id))
    guest_ids = [g.id for g in guest_records.scalars().all()]

    if not guest_ids:
        raise HTTPException(status_code=404, detail="Reservation not found")

    result = await db.execute(
        select(Reservation).where(
            and_(
                Reservation.id == res_uuid,
                Reservation.guest_id.in_(guest_ids),
            )
        )
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if reservation.status not in ("pending", "confirmed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel reservation with status {reservation.status}",
        )

    from datetime import UTC, datetime

    reservation.status = "canceled"
    reservation.canceled_at = datetime.now(UTC)
    reservation.canceled_reason = "Canceled by guest"
    await db.commit()

    return {"message": "Reservation cancelled", "id": str(reservation.id)}


@router.delete("")
async def delete_guest_account(
    guest: GuestProfile = Depends(get_current_guest),
):
    """Delete the guest account."""
    from app.core.database import get_session_factories

    session_factory_app, _ = get_session_factories()
    async with session_factory_app() as session:
        result = await session.execute(select(GuestProfile).where(GuestProfile.id == guest.id))
        db_guest = result.scalar_one_or_none()
        if db_guest:
            await session.delete(db_guest)
            await session.commit()

    return {"message": "Account deleted successfully"}


# --- Favorites ---


@router.get("/favorites")
async def list_favorites(
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """List all favorited restaurants for the authenticated guest."""
    result = await db.execute(
        select(GuestFavorite, Restaurant)
        .join(Restaurant, GuestFavorite.restaurant_id == Restaurant.id)
        .where(GuestFavorite.guest_profile_id == guest.id)
        .order_by(GuestFavorite.created_at.desc())
    )
    rows = result.all()

    items = []
    for fav, rest in rows:
        avg_result = await db.execute(
            select(func.avg(Review.rating), func.count(Review.id)).where(
                and_(
                    Review.tenant_id == rest.id,
                    Review.is_visible.is_(True),
                )
            )
        )
        avg_row = avg_result.one()
        avg_rating = round(float(avg_row[0]), 2) if avg_row[0] else None
        review_count = avg_row[1] or 0

        items.append(
            {
                "id": str(rest.id),
                "name": rest.name,
                "slug": rest.slug,
                "address": rest.address,
                "description": rest.description,
                "cuisine_type": (rest.settings or {}).get("cuisine_type"),
                "image_url": (rest.settings or {}).get("image_url"),
                "average_rating": avg_rating,
                "review_count": review_count,
                "favorited_at": fav.created_at.isoformat(),
            }
        )

    return items


@router.get("/favorites/ids")
async def list_favorite_ids(
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """Return only restaurant IDs of favorites (for fast heart-icon rendering)."""
    result = await db.execute(
        select(GuestFavorite.restaurant_id).where(GuestFavorite.guest_profile_id == guest.id)
    )
    ids = [str(row[0]) for row in result.all()]
    return ids


@router.post(
    "/favorites/{restaurant_id}",
    status_code=status.HTTP_201_CREATED,
)
async def add_favorite(
    restaurant_id: uuid.UUID,
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """Add a restaurant to favorites."""
    # Check restaurant exists
    rest = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    if not rest.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Restaurant not found")

    # Check duplicate
    existing = await db.execute(
        select(GuestFavorite).where(
            and_(
                GuestFavorite.guest_profile_id == guest.id,
                GuestFavorite.restaurant_id == restaurant_id,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already in favorites")

    fav = GuestFavorite(
        guest_profile_id=guest.id,
        restaurant_id=restaurant_id,
    )
    db.add(fav)
    await db.commit()

    return {"message": "Added to favorites", "restaurant_id": str(restaurant_id)}


@router.delete(
    "/favorites/{restaurant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_favorite(
    restaurant_id: uuid.UUID,
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """Remove a restaurant from favorites."""
    result = await db.execute(
        select(GuestFavorite).where(
            and_(
                GuestFavorite.guest_profile_id == guest.id,
                GuestFavorite.restaurant_id == restaurant_id,
            )
        )
    )
    fav = result.scalar_one_or_none()
    if not fav:
        raise HTTPException(status_code=404, detail="Not in favorites")

    await db.delete(fav)
    await db.commit()


# --- Reservation Detail ---


@router.get("/reservations/{reservation_id}")
async def get_guest_reservation_detail(
    reservation_id: str,
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """Get a single reservation detail owned by the authenticated guest."""
    from uuid import UUID as PyUUID

    try:
        res_uuid = PyUUID(reservation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid reservation ID")

    guest_records = await db.execute(select(Guest).where(Guest.guest_profile_id == guest.id))
    guest_ids = [g.id for g in guest_records.scalars().all()]

    if not guest_ids:
        raise HTTPException(status_code=404, detail="Reservation not found")

    result = await db.execute(
        select(Reservation, Restaurant)
        .join(Restaurant, Reservation.tenant_id == Restaurant.id)
        .where(
            and_(
                Reservation.id == res_uuid,
                Reservation.guest_id.in_(guest_ids),
            )
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Reservation not found")

    r, rest = row
    return {
        "id": str(r.id),
        "restaurant_id": str(r.tenant_id),
        "restaurant_name": rest.name,
        "restaurant_slug": rest.slug or "",
        "date": (r.start_at.astimezone(RESTAURANT_TZ).date().isoformat() if r.start_at else None),
        "time": (r.start_at.astimezone(RESTAURANT_TZ).strftime("%H:%M") if r.start_at else None),
        "party_size": r.party_size,
        "status": r.status,
        "guest_name": r.guest_name,
        "guest_email": r.guest_email,
        "guest_phone": r.guest_phone,
        "special_requests": r.special_requests,
        "confirmation_code": r.confirmation_code,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
