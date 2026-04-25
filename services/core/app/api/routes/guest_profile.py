"""Guest profile endpoints (protected by guest JWT)."""

from __future__ import annotations

import logging
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.public_reservations import (
    _compute_has_outdoor_table,
    _load_tables_by_id,
    _reservation_table_ids,
)
from app.core.deps import get_db
from app.core.guest_deps import get_current_guest
from app.models.guest_favorite import GuestFavorite
from app.models.reservation import Guest, Reservation
from app.models.restaurant import Restaurant
from app.models.review import Review
from app.models.user import GuestProfile
from app.schemas.guest_auth import (
    GuestChangeEmailRequest,
    GuestChangePasswordRequest,
    GuestProfileResponse,
    GuestProfileUpdateRequest,
)

RESTAURANT_TZ = ZoneInfo("Europe/Berlin")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/me", tags=["guest-profile"])


async def _table_exists(db: AsyncSession, table_name: str) -> bool:
    result = await db.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = :table_name
            )
            """),
        {"table_name": table_name},
    )
    return bool(result.scalar())


async def _column_exists(db: AsyncSession, table_name: str, column_name: str) -> bool:
    result = await db.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :table_name
                  AND column_name = :column_name
            )
            """),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(result.scalar())


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
        created_at=guest.created_at,
        updated_at=guest.updated_at,
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
            created_at=db_guest.created_at,
            updated_at=db_guest.updated_at,
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


@router.put("/email", response_model=GuestProfileResponse)
async def change_email(
    body: GuestChangeEmailRequest,
    guest: GuestProfile = Depends(get_current_guest),
):
    """Change the guest's email address (requires current password)."""
    from app.core.database import get_session_factories
    from packages.shared.auth import verify_password

    if not guest.password_hash or not verify_password(body.password, guest.password_hash):
        raise HTTPException(status_code=401, detail="Falsches Passwort")

    session_factory_app, _ = get_session_factories()
    async with session_factory_app() as session:
        # Check if new email is already taken
        existing = await session.execute(
            select(GuestProfile).where(
                and_(
                    GuestProfile.email == body.new_email,
                    GuestProfile.id != guest.id,
                )
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail="Diese E-Mail-Adresse wird bereits verwendet",
            )

        result = await session.execute(select(GuestProfile).where(GuestProfile.id == guest.id))
        db_guest = result.scalar_one()
        db_guest.email = body.new_email
        db_guest.email_verified = False
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
            created_at=db_guest.created_at,
            updated_at=db_guest.updated_at,
        )


@router.put("/password")
async def change_password(
    body: GuestChangePasswordRequest,
    guest: GuestProfile = Depends(get_current_guest),
):
    """Change the guest's password (requires current password)."""
    from app.core.database import get_session_factories
    from packages.shared.auth import hash_password, verify_password

    if not guest.password_hash or not verify_password(body.current_password, guest.password_hash):
        raise HTTPException(status_code=401, detail="Aktuelles Passwort ist falsch")

    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=422, detail="Das neue Passwort muss mindestens 8 Zeichen lang sein"
        )

    session_factory_app, _ = get_session_factories()
    async with session_factory_app() as session:
        result = await session.execute(select(GuestProfile).where(GuestProfile.id == guest.id))
        db_guest = result.scalar_one()
        db_guest.password_hash = hash_password(body.new_password)
        await session.commit()

    return {"message": "Passwort wurde erfolgreich geändert"}


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
            "notes": r.notes,
            "confirmation_code": r.confirmation_code,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r, rest in rows
    ]


@router.get("/orders")
async def get_guest_orders(
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """Get order history across all restaurants for the authenticated guest."""
    if not await _table_exists(db, "orders"):
        return []

    has_guest_profile_id = await _column_exists(db, "orders", "guest_profile_id")
    has_guest_id = await _column_exists(db, "orders", "guest_id")
    has_order_items = await _table_exists(db, "order_items")

    guest_ids: list[str] = []
    if has_guest_id and await _table_exists(db, "guests"):
        guest_rows = await db.execute(
            text("SELECT id FROM guests WHERE guest_profile_id = :guest_profile_id"),
            {"guest_profile_id": str(guest.id)},
        )
        guest_ids = [str(row.id) for row in guest_rows if row.id]

    if not has_guest_profile_id and (not has_guest_id or not guest_ids):
        return []

    scope_filter_parts: list[str] = []
    params: dict[str, object] = {"guest_profile_id": str(guest.id)}
    if has_guest_profile_id:
        scope_filter_parts.append("o.guest_profile_id = CAST(:guest_profile_id AS uuid)")
    if has_guest_id and guest_ids:
        guest_id_placeholders: list[str] = []
        for idx, guest_id in enumerate(guest_ids):
            param_name = f"guest_id_{idx}"
            params[param_name] = guest_id
            guest_id_placeholders.append(f"CAST(:{param_name} AS uuid)")
        scope_filter_parts.append(f"o.guest_id IN ({', '.join(guest_id_placeholders)})")

    if not scope_filter_parts:
        return []

    item_count_join = ""
    item_count_select = "0 AS items_count"
    if has_order_items:
        item_count_join = """
            LEFT JOIN (
                SELECT order_id, COALESCE(SUM(quantity), 0) AS items_count
                FROM order_items
                GROUP BY order_id
            ) oi_count ON oi_count.order_id = o.id
        """
        item_count_select = "COALESCE(oi_count.items_count, 0) AS items_count"

    sql = f"""
        SELECT
            o.id,
            COALESCE(r.name, '') AS restaurant_name,
            COALESCE(r.slug, '') AS restaurant_slug,
            COALESCE(o.order_number, '') AS order_number,
            COALESCE(o.total, 0) AS total,
            COALESCE(o.status, 'open') AS status,
            {item_count_select},
            COALESCE(o.opened_at, o.created_at) AS created_at
        FROM orders o
        LEFT JOIN restaurants r ON r.id = o.tenant_id
        {item_count_join}
        WHERE ({" OR ".join(scope_filter_parts)})
        ORDER BY COALESCE(o.opened_at, o.created_at) DESC
        LIMIT 200
    """

    rows = await db.execute(text(sql), params)

    return [
        {
            "id": str(row.id),
            "restaurant_name": row.restaurant_name,
            "restaurant_slug": row.restaurant_slug,
            "order_number": row.order_number,
            "total": float(row.total or 0),
            "status": row.status,
            "items_count": int(row.items_count or 0),
            "created_at": (row.created_at.isoformat() if row.created_at is not None else None),
        }
        for row in rows
    ]


@router.get("/receipts")
async def get_guest_receipts(
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """Get paid order receipts for the authenticated guest."""
    if not await _table_exists(db, "orders"):
        return []

    has_guest_profile_id = await _column_exists(db, "orders", "guest_profile_id")
    has_guest_id = await _column_exists(db, "orders", "guest_id")
    has_tip_amount = await _column_exists(db, "orders", "tip_amount")
    has_order_items = await _table_exists(db, "order_items")

    guest_ids: list[str] = []
    if has_guest_id and await _table_exists(db, "guests"):
        guest_rows = await db.execute(
            text("SELECT id FROM guests WHERE guest_profile_id = :guest_profile_id"),
            {"guest_profile_id": str(guest.id)},
        )
        guest_ids = [str(row.id) for row in guest_rows if row.id]

    if not has_guest_profile_id and (not has_guest_id or not guest_ids):
        return []

    scope_filter_parts: list[str] = []
    params: dict[str, object] = {"guest_profile_id": str(guest.id)}
    if has_guest_profile_id:
        scope_filter_parts.append("o.guest_profile_id = CAST(:guest_profile_id AS uuid)")
    if has_guest_id and guest_ids:
        guest_id_placeholders: list[str] = []
        for idx, guest_id in enumerate(guest_ids):
            param_name = f"guest_id_{idx}"
            params[param_name] = guest_id
            guest_id_placeholders.append(f"CAST(:{param_name} AS uuid)")
        scope_filter_parts.append(f"o.guest_id IN ({', '.join(guest_id_placeholders)})")

    if not scope_filter_parts:
        return []

    tip_expr = "COALESCE(o.tip_amount, 0)" if has_tip_amount else "0"
    receipts_sql = f"""
        SELECT
            o.id,
            COALESCE(r.name, '') AS restaurant_name,
            COALESCE(o.subtotal, 0) AS subtotal,
            {tip_expr} AS tip,
            COALESCE(o.total, 0) AS total,
            COALESCE(o.payment_method, '') AS payment_method,
            COALESCE(o.paid_at, o.closed_at, o.updated_at, o.created_at) AS paid_at
        FROM orders o
        LEFT JOIN restaurants r ON r.id = o.tenant_id
        WHERE ({" OR ".join(scope_filter_parts)})
          AND (
              COALESCE(o.payment_status, '') = 'paid'
              OR o.status = 'paid'
              OR o.paid_at IS NOT NULL
          )
        ORDER BY COALESCE(o.paid_at, o.closed_at, o.updated_at, o.created_at) DESC
        LIMIT 200
    """

    rows = await db.execute(text(receipts_sql), params)
    receipts = []
    for row in rows:
        items: list[dict[str, object]] = []
        if has_order_items:
            item_rows = await db.execute(
                text("""
                    SELECT item_name, quantity, unit_price
                    FROM order_items
                    WHERE order_id = :order_id
                    ORDER BY sort_order ASC, created_at ASC
                    """),
                {"order_id": str(row.id)},
            )
            items = [
                {
                    "name": item_row.item_name,
                    "quantity": int(item_row.quantity or 0),
                    "price": float(item_row.unit_price or 0),
                }
                for item_row in item_rows
            ]

        receipts.append(
            {
                "id": str(row.id),
                "order_id": str(row.id),
                "restaurant_name": row.restaurant_name,
                "items": items,
                "subtotal": float(row.subtotal or 0),
                "tip": float(row.tip or 0),
                "total": float(row.total or 0),
                "payment_method": row.payment_method or "card",
                "paid_at": row.paid_at.isoformat() if row.paid_at is not None else None,
            }
        )

    return receipts


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

    # Weather-banner feed: the app shows an outdoor-weather warning <24h
    # before the reservation when the assigned table is outdoor. Requires
    # the `has_outdoor_table` flag (same semantic as the public widget
    # endpoint — see public_reservations._compute_has_outdoor_table) plus
    # enough location data to geocode via Open-Meteo.
    table_ids = await _reservation_table_ids(db, r)
    tables_by_id = await _load_tables_by_id(db, rest.id, table_ids)
    has_outdoor_table = _compute_has_outdoor_table(table_ids, tables_by_id)

    return {
        "id": str(r.id),
        "restaurant_id": str(r.tenant_id),
        "restaurant_name": rest.name,
        "restaurant_slug": rest.slug or "",
        "restaurant_city": rest.city,
        "restaurant_zip_code": rest.zip_code,
        "date": (r.start_at.astimezone(RESTAURANT_TZ).date().isoformat() if r.start_at else None),
        "time": (r.start_at.astimezone(RESTAURANT_TZ).strftime("%H:%M") if r.start_at else None),
        "party_size": r.party_size,
        "status": r.status,
        "guest_name": r.guest_name,
        "guest_email": r.guest_email,
        "guest_phone": r.guest_phone,
        "notes": r.notes,
        "confirmation_code": r.confirmation_code,
        "has_outdoor_table": has_outdoor_table,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
