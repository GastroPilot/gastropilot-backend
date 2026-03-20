"""Review endpoints — mixed public and staff-protected."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_manager_or_above
from app.core.guest_deps import get_current_guest
from app.models.reservation import Guest, Reservation
from app.models.restaurant import Restaurant
from app.models.review import Review
from app.models.user import GuestProfile
from app.schemas.review import (
    ReviewCreateRequest,
    ReviewReplyRequest,
    ReviewResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reviews"])


# --- Helpers ---


async def _get_restaurant_by_slug(slug: str, db: AsyncSession) -> Restaurant:
    result = await db.execute(select(Restaurant).where(Restaurant.slug == slug))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return restaurant


def _format_author_name(guest: GuestProfile) -> str:
    if guest.last_name:
        return f"{guest.first_name} {guest.last_name[0]}."
    return guest.first_name


# --- Public endpoints ---


@router.post(
    "/public/restaurants/{slug}/reviews",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_review(
    slug: str,
    body: ReviewCreateRequest,
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """Create a review for a restaurant (guest auth required)."""
    restaurant = await _get_restaurant_by_slug(slug, db)

    # Check for existing review by this guest
    existing = await db.execute(
        select(Review).where(
            and_(
                Review.tenant_id == restaurant.id,
                Review.guest_profile_id == guest.id,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="You have already reviewed this restaurant",
        )

    # Pruefen ob der Gast eine abgeschlossene Reservierung bei diesem Restaurant hat
    # Zwei Wege: 1) Guest-Tabelle mit guest_profile_id, 2) Reservierung mit guest_email
    verified_statuses = ("completed", "seated")

    # Weg 1: Ueber Guest-Profil-Verknuepfung
    verified_via_profile = await db.execute(
        select(Reservation.id)
        .join(Guest, Reservation.guest_id == Guest.id)
        .where(
            Guest.guest_profile_id == guest.id,
            Reservation.tenant_id == restaurant.id,
            Reservation.status.in_(verified_statuses),
        )
        .limit(1)
    )
    is_verified = verified_via_profile.scalar_one_or_none() is not None

    # Weg 2: Ueber E-Mail-Abgleich (Fallback)
    if not is_verified and guest.email:
        verified_via_email = await db.execute(
            select(Reservation.id)
            .where(
                Reservation.tenant_id == restaurant.id,
                Reservation.guest_email == guest.email,
                Reservation.status.in_(verified_statuses),
            )
            .limit(1)
        )
        is_verified = verified_via_email.scalar_one_or_none() is not None

    review = Review(
        tenant_id=restaurant.id,
        guest_profile_id=guest.id,
        rating=body.rating,
        title=body.title,
        text=body.text,
        is_verified=is_verified,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)

    return ReviewResponse(
        id=review.id,
        rating=review.rating,
        title=review.title,
        text=review.text,
        author_name=_format_author_name(guest),
        is_mine=True,
        is_verified=review.is_verified,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


@router.patch(
    "/public/restaurants/{slug}/reviews/{review_id}",
    response_model=ReviewResponse,
)
async def update_review(
    slug: str,
    review_id: uuid.UUID,
    body: ReviewCreateRequest,
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """Update own review for a restaurant (guest auth required)."""
    restaurant = await _get_restaurant_by_slug(slug, db)

    result = await db.execute(
        select(Review).where(
            and_(
                Review.id == review_id,
                Review.tenant_id == restaurant.id,
                Review.guest_profile_id == guest.id,
            )
        )
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    review.rating = body.rating
    review.title = body.title
    review.text = body.text
    await db.commit()
    await db.refresh(review)

    return ReviewResponse(
        id=review.id,
        rating=review.rating,
        title=review.title,
        text=review.text,
        author_name=_format_author_name(guest),
        is_mine=True,
        is_verified=review.is_verified,
        staff_reply=review.staff_reply,
        staff_reply_at=review.staff_reply_at,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


@router.delete(
    "/public/restaurants/{slug}/reviews/{review_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_own_review(
    slug: str,
    review_id: uuid.UUID,
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete own review for a restaurant (guest auth required)."""
    restaurant = await _get_restaurant_by_slug(slug, db)

    result = await db.execute(
        select(Review).where(
            and_(
                Review.id == review_id,
                Review.tenant_id == restaurant.id,
                Review.guest_profile_id == guest.id,
            )
        )
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    await db.delete(review)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Staff-protected endpoints ---


class ReviewModerationRequest(BaseModel):
    is_visible: bool


@router.patch("/reviews/{review_id}")
async def moderate_review(
    review_id: uuid.UUID,
    body: ReviewModerationRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    """Toggle review visibility (manager+)."""
    result = await db.execute(select(Review).where(Review.id == review_id))
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    review.is_visible = body.is_visible
    await db.commit()

    return {
        "id": str(review.id),
        "is_visible": review.is_visible,
    }


@router.get("/reviews")
async def list_tenant_reviews(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    """List all reviews for the current tenant (manager+)."""
    tenant_id = current_user.tenant_id

    # Total count
    count_result = await db.execute(
        select(func.count(Review.id)).where(Review.tenant_id == tenant_id)
    )
    total = count_result.scalar() or 0

    # Average rating
    avg_result = await db.execute(
        select(func.avg(Review.rating)).where(Review.tenant_id == tenant_id)
    )
    avg_rating = avg_result.scalar()
    avg_rating = round(float(avg_rating), 2) if avg_rating else None

    # Paginated reviews
    offset = (page - 1) * per_page
    result = await db.execute(
        select(Review, GuestProfile)
        .join(
            GuestProfile,
            Review.guest_profile_id == GuestProfile.id,
        )
        .where(Review.tenant_id == tenant_id)
        .order_by(Review.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    rows = result.all()

    items = [
        {
            "id": str(review.id),
            "rating": review.rating,
            "title": review.title,
            "text": review.text,
            "author_name": (f"{guest.first_name} {guest.last_name}"),
            "author_email": guest.email,
            "is_visible": review.is_visible,
            "staff_reply": review.staff_reply,
            "staff_reply_at": (
                review.staff_reply_at.isoformat() if review.staff_reply_at else None
            ),
            "created_at": review.created_at.isoformat(),
        }
        for review, guest in rows
    ]

    return {
        "items": items,
        "total": total,
        "average_rating": avg_rating,
        "page": page,
        "per_page": per_page,
    }


@router.post("/reviews/{review_id}/reply")
async def reply_to_review(
    review_id: uuid.UUID,
    body: ReviewReplyRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    """Reply to a review (manager+)."""
    from datetime import UTC, datetime

    result = await db.execute(select(Review).where(Review.id == review_id))
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    review.staff_reply = body.text
    review.staff_reply_at = datetime.now(UTC)
    review.staff_reply_by = current_user.id
    await db.commit()

    return {
        "id": str(review.id),
        "staff_reply": review.staff_reply,
        "staff_reply_at": review.staff_reply_at.isoformat(),
    }
