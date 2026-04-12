"""Public restaurant search and detail endpoints."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.guest_deps import get_optional_guest
from app.models.menu import MenuCategory, MenuItem
from app.models.restaurant import Restaurant
from app.models.review import Review
from app.models.user import GuestProfile
from app.schemas.restaurant_search import (
    RestaurantSearchResponse,
)
from app.schemas.review import ReviewListResponse, ReviewResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/restaurants", tags=["restaurant-search"])


async def _get_public_restaurant(slug: str, db: AsyncSession) -> Restaurant:
    """Get a restaurant by slug, only if public booking is enabled."""
    result = await db.execute(select(Restaurant).where(Restaurant.slug == slug))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return restaurant


async def _get_rating_stats(db: AsyncSession, tenant_id: UUID) -> tuple[float | None, int]:
    """Get average rating and count for a restaurant."""
    result = await db.execute(
        select(
            func.avg(Review.rating),
            func.count(Review.id),
        ).where(
            and_(
                Review.tenant_id == tenant_id,
                Review.is_visible.is_(True),
            )
        )
    )
    row = result.one()
    avg_rating = float(row[0]) if row[0] is not None else None
    count = row[1] or 0
    return avg_rating, count


@router.get("/cuisines")
async def list_cuisines(
    db: AsyncSession = Depends(get_db),
):
    """Return distinct cuisine types from public restaurants."""
    cuisine_type_expr = Restaurant.settings["cuisine_type"].astext.label(
        "cuisine_type"
    )

    result = await db.execute(
        select(cuisine_type_expr)
        .where(
            and_(
                Restaurant.public_booking_enabled.is_(True),
                Restaurant.settings["cuisine_type"].astext.isnot(None),
                Restaurant.settings["cuisine_type"].astext != "",
            )
        )
        .distinct()
        .order_by(cuisine_type_expr)
    )
    cuisines = [row[0] for row in result.all() if row[0]]
    return {"cuisines": cuisines}


@router.get("")
async def search_restaurants(
    q: str | None = Query(None, alias="query", description="Search query"),
    allergens: str | None = Query(None, description="Comma-separated allergen IDs"),
    cuisine: str | None = Query(None, description="Cuisine type"),
    price_range: int | None = Query(None, ge=1, le=4, description="Price range 1-4"),
    lat: float | None = Query(None, description="Latitude"),
    lng: float | None = Query(None, description="Longitude"),
    radius: float | None = Query(None, description="Search radius in km"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    limit: int | None = Query(None, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search restaurants with filters.

    Returns paginated list of public restaurant info.
    Only returns restaurants with public_booking_enabled=True.
    """
    actual_limit = limit or per_page

    base_query = select(Restaurant).where(Restaurant.public_booking_enabled.is_(True))

    if q:
        search_term = f"%{q}%"
        base_query = base_query.where(
            Restaurant.name.ilike(search_term)
            | Restaurant.description.ilike(search_term)
            | Restaurant.address.ilike(search_term)
        )

    if cuisine:
        base_query = base_query.where(Restaurant.settings["cuisine_type"].astext == cuisine)

    if price_range:
        from sqlalchemy import Integer as SAInteger

        base_query = base_query.where(
            Restaurant.settings["price_range"].astext.cast(SAInteger) == price_range
        )

    # Total count
    count_result = await db.execute(select(func.count()).select_from(base_query.subquery()))
    total = count_result.scalar() or 0

    # Pagination
    offset = (page - 1) * actual_limit
    query = base_query.offset(offset).limit(actual_limit)
    query = query.order_by(
        Restaurant.is_featured.desc().nullslast(),
        Restaurant.name,
    )

    result = await db.execute(query)
    restaurants = result.scalars().all()

    # Build response with ratings
    items = []
    for r in restaurants:
        avg_rating, rating_count = await _get_rating_stats(db, r.id)
        s = r.settings or {}
        cuisine_type = s.get("cuisine_type")
        image_url = s.get("image_url") or s.get("logo_url")
        items.append(
            {
                "id": str(r.id),
                "name": r.name,
                "slug": r.slug,
                "address": r.address,
                "description": r.description,
                "phone": r.phone,
                "cuisine_type": cuisine_type,
                "price_range": s.get("price_range"),
                "average_rating": avg_rating,
                "review_count": rating_count,
                "opening_hours": r.opening_hours,
                "image_url": image_url,
                "latitude": s.get("latitude"),
                "longitude": s.get("longitude"),
                "allergen_safe": [],
                "public_booking_enabled": True,
                "booking_max_party_size": s.get("max_party_size", 10),
                "is_featured": bool(r.is_featured),
            }
        )

    import math

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": actual_limit,
        "pages": math.ceil(total / actual_limit) if total > 0 else 0,
    }


@router.get("/{slug}")
async def get_restaurant_detail(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Full restaurant detail with menu and reviews summary."""
    restaurant = await _get_public_restaurant(slug, db)

    avg_rating, rating_count = await _get_rating_stats(db, restaurant.id)

    # Menu summary: category names and item counts
    cat_result = await db.execute(
        select(MenuCategory)
        .where(
            and_(
                MenuCategory.tenant_id == restaurant.id,
                MenuCategory.is_active.is_(True),
            )
        )
        .order_by(MenuCategory.sort_order)
    )
    categories = cat_result.scalars().all()

    menu_summary = []
    for cat in categories:
        item_count_result = await db.execute(
            select(func.count(MenuItem.id)).where(
                and_(
                    MenuItem.category_id == cat.id,
                    MenuItem.is_available.is_(True),
                )
            )
        )
        count = item_count_result.scalar() or 0
        menu_summary.append({"category": cat.name, "item_count": count})

    s = restaurant.settings or {}
    cuisine_type = s.get("cuisine_type")
    image_url = s.get("image_url")

    return {
        "id": str(restaurant.id),
        "name": restaurant.name,
        "slug": restaurant.slug,
        "address": restaurant.address,
        "phone": restaurant.phone,
        "description": restaurant.description,
        "email": None,
        "cuisine_type": cuisine_type,
        "price_range": s.get("price_range"),
        "average_rating": avg_rating,
        "review_count": rating_count,
        "opening_hours": restaurant.opening_hours,
        "image_url": image_url,
        "latitude": s.get("latitude"),
        "longitude": s.get("longitude"),
        "allergen_safe": [],
        "public_booking_enabled": True,
        "booking_max_party_size": s.get("max_party_size", 10),
        "menu_summary": menu_summary,
        "reviews_summary": {
            "average_rating": avg_rating,
            "total_reviews": rating_count,
        },
    }


@router.get("/{slug}/menu")
async def get_restaurant_menu(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Full menu with allergen info for a restaurant."""
    restaurant = await _get_public_restaurant(slug, db)

    cat_result = await db.execute(
        select(MenuCategory)
        .where(
            and_(
                MenuCategory.tenant_id == restaurant.id,
                MenuCategory.is_active.is_(True),
            )
        )
        .order_by(MenuCategory.sort_order)
    )
    categories = cat_result.scalars().all()

    menu = []
    for cat in categories:
        items_result = await db.execute(
            select(MenuItem)
            .where(
                and_(
                    MenuItem.category_id == cat.id,
                    MenuItem.is_available.is_(True),
                )
            )
            .order_by(MenuItem.sort_order)
        )
        items = items_result.scalars().all()
        menu.append(
            {
                "id": str(cat.id),
                "name": cat.name,
                "description": cat.description,
                "items": [
                    {
                        "id": str(item.id),
                        "name": item.name,
                        "description": item.description,
                        "price": item.price,
                        "allergens": item.allergens or [],
                        "modifiers": item.modifiers,
                    }
                    for item in items
                ],
            }
        )

    return {"restaurant": restaurant.name, "categories": menu}


@router.get("/{slug}/reviews", response_model=ReviewListResponse)
async def list_restaurant_reviews(
    slug: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_guest: GuestProfile | None = Depends(get_optional_guest),
):
    """Paginated reviews for a restaurant."""
    restaurant = await _get_public_restaurant(slug, db)

    avg_rating, total = await _get_rating_stats(db, restaurant.id)

    offset = (page - 1) * per_page
    result = await db.execute(
        select(Review, GuestProfile)
        .join(
            GuestProfile,
            Review.guest_profile_id == GuestProfile.id,
        )
        .where(
            and_(
                Review.tenant_id == restaurant.id,
                Review.is_visible.is_(True),
            )
        )
        .order_by(Review.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    rows = result.all()

    items = [
        ReviewResponse(
            id=review.id,
            rating=review.rating,
            title=review.title,
            text=review.text,
            author_name=(
                f"{review_author.first_name} {review_author.last_name[0]}."
                if review_author.last_name
                else review_author.first_name
            ),
            is_mine=bool(current_guest and review.guest_profile_id == current_guest.id),
            is_verified=getattr(review, "is_verified", False),
            staff_reply=review.staff_reply,
            staff_reply_at=review.staff_reply_at,
            created_at=review.created_at,
            updated_at=review.updated_at,
        )
        for review, review_author in rows
    ]

    return ReviewListResponse(
        items=items,
        total=total,
        average_rating=avg_rating,
    )
