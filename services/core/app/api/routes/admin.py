from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_platform_admin
from app.core.security import create_access_token, hash_password, hash_pin
from app.models.audit import PlatformAuditLog
from app.models.reservation import Reservation
from app.models.restaurant import Restaurant
from app.models.review import Review
from app.models.user import GuestProfile, User

router = APIRouter(prefix="/admin", tags=["admin"])


# ─── Schemas ──────────────────────────────────────────────────────────────────


class TenantCreate(BaseModel):
    # Restaurant
    name: str
    slug: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    # Erster Owner-User
    owner_first_name: str
    owner_last_name: str
    owner_operator_number: str  # 4-stellige Bediener-Nr., z.B. "0001"
    owner_pin: str  # 6–8 Ziffern

    @field_validator("owner_operator_number")
    @classmethod
    def validate_operator_number(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}", v):
            raise ValueError("operator_number muss genau 4 Ziffern sein")
        return v

    @field_validator("owner_pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        if not re.fullmatch(r"\d{6,8}", v):
            raise ValueError("PIN muss 6–8 Ziffern enthalten")
        return v

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"[a-z0-9-]+", v):
            raise ValueError("slug darf nur Kleinbuchstaben, Ziffern und Bindestriche enthalten")
        return v


class TenantCreateResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    owner_id: str
    owner_operator_number: str


class TenantUpdate(BaseModel):
    name: str | None = None
    settings: dict | None = None


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/tenants")
async def list_tenants(
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Restaurant))
    tenants = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "slug": t.slug,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tenants
    ]


@router.post("/tenants", response_model=TenantCreateResponse, status_code=201)
async def create_tenant(
    data: TenantCreate,
    request: Request,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    # Slug-Konflikt prüfen
    if data.slug:
        existing = await session.execute(select(Restaurant).where(Restaurant.slug == data.slug))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Slug ist bereits vergeben")

    # 1. Restaurant anlegen
    restaurant = Restaurant(
        name=data.name,
        slug=data.slug,
        address=data.address,
        phone=data.phone,
        email=data.email,
    )
    session.add(restaurant)
    await session.flush()  # ID generieren, noch kein Commit

    # 2. Owner-User anlegen
    owner = User(
        tenant_id=restaurant.id,
        operator_number=data.owner_operator_number,
        pin_hash=hash_pin(data.owner_pin),
        first_name=data.owner_first_name,
        last_name=data.owner_last_name,
        role="owner",
        auth_method="pin",
        is_active=True,
    )
    session.add(owner)

    # 3. Audit-Log
    log = PlatformAuditLog(
        admin_user_id=current_user.id,
        target_tenant_id=restaurant.id,
        action="tenant.created",
        entity_type="restaurant",
        entity_id=restaurant.id,
        description=f"Tenant '{data.name}' mit Owner {data.owner_operator_number} angelegt",
        ip_address=request.client.host if request.client else None,
    )
    session.add(log)

    await session.commit()

    return TenantCreateResponse(
        tenant_id=str(restaurant.id),
        tenant_name=restaurant.name,
        owner_id=str(owner.id),
        owner_operator_number=owner.operator_number,
    )


@router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: uuid.UUID,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Restaurant).where(Restaurant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "address": tenant.address,
        "phone": tenant.phone,
        "email": tenant.email,
        "settings": tenant.settings,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
    }


@router.patch("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: uuid.UUID,
    data: TenantUpdate,
    request: Request,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Restaurant).where(Restaurant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if data.name is not None:
        tenant.name = data.name
    if data.settings is not None:
        current = dict(tenant.settings or {})
        current.update(data.settings)
        tenant.settings = current

    log = PlatformAuditLog(
        admin_user_id=current_user.id,
        target_tenant_id=tenant_id,
        action="tenant.updated",
        entity_type="restaurant",
        entity_id=tenant_id,
        ip_address=request.client.host if request.client else None,
    )
    session.add(log)
    await session.commit()
    return {"id": str(tenant.id), "name": tenant.name}


@router.delete("/tenants/{tenant_id}", status_code=200)
async def delete_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Restaurant).where(Restaurant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant_name = tenant.name

    # Audit-Log VOR dem Loeschen erstellen (target_tenant_id wird via CASCADE nicht geloescht,
    # da PlatformAuditLog.target_tenant_id nullable ist oder kein FK-Constraint hat)
    log = PlatformAuditLog(
        admin_user_id=current_user.id,
        target_tenant_id=tenant_id,
        action="tenant.deleted",
        entity_type="restaurant",
        entity_id=tenant_id,
        description=f"Tenant '{tenant_name}' und alle zugehoerigen Daten geloescht",
        ip_address=request.client.host if request.client else None,
    )
    session.add(log)
    await session.flush()

    # Tenant loeschen — CASCADE loescht Users, Areas, Tables, Obstacles etc.
    await session.delete(tenant)
    await session.commit()

    return {"deleted": True, "tenant_id": str(tenant_id), "tenant_name": tenant_name}


@router.get("/tenants/{tenant_id}/impersonate")
async def impersonate_tenant(
    tenant_id: uuid.UUID,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Restaurant).where(Restaurant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    token_data = {
        "sub": str(current_user.id),
        "role": "platform_admin",
        "tenant_id": None,
        "impersonating_tenant_id": str(tenant_id),
    }
    impersonation_token = create_access_token(token_data)
    return {
        "impersonation_token": impersonation_token,
        "tenant_id": str(tenant_id),
        "tenant_name": tenant.name,
    }


@router.get("/audit-log")
async def get_audit_log(
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(PlatformAuditLog).order_by(PlatformAuditLog.created_at.desc()).limit(200)
    )
    logs = result.scalars().all()
    return [
        {
            "id": str(log.id),
            "admin_user_id": str(log.admin_user_id) if log.admin_user_id else None,
            "target_tenant_id": str(log.target_tenant_id) if log.target_tenant_id else None,
            "action": log.action,
            "description": log.description,
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


# ─── Guest-Profile Schemas ──────────────────────────────────────────────────


class GuestProfileUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    language: str | None = None
    notes: str | None = None
    allergen_profile: list | None = None
    email_verified: bool | None = None
    password: str | None = None  # Klartext, wird gehasht


class ReservationStatusUpdate(BaseModel):
    status: str
    canceled_reason: str | None = None


class ReviewVisibilityUpdate(BaseModel):
    is_visible: bool


# ─── Gaeste-Verwaltung ───────────────────────────────────────────────────────


@router.get("/guests")
async def list_guests(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query("", max_length=200),
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    query = select(GuestProfile)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                GuestProfile.first_name.ilike(pattern),
                GuestProfile.last_name.ilike(pattern),
                GuestProfile.email.ilike(pattern),
            )
        )
    query = query.order_by(GuestProfile.created_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_q)).scalar() or 0

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await session.execute(query)
    guests = result.scalars().all()

    return {
        "items": [
            {
                "id": str(g.id),
                "first_name": g.first_name,
                "last_name": g.last_name,
                "email": g.email,
                "phone": g.phone,
                "email_verified": g.email_verified,
                "has_password": g.password_hash is not None,
                "created_at": g.created_at.isoformat() if g.created_at else None,
            }
            for g in guests
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/guests/{guest_id}")
async def get_guest(
    guest_id: uuid.UUID,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(GuestProfile).where(GuestProfile.id == guest_id)
    )
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    return {
        "id": str(guest.id),
        "first_name": guest.first_name,
        "last_name": guest.last_name,
        "email": guest.email,
        "phone": guest.phone,
        "language": guest.language,
        "notes": guest.notes,
        "email_verified": guest.email_verified,
        "has_password": guest.password_hash is not None,
        "allergen_profile": guest.allergen_profile,
        "created_at": guest.created_at.isoformat() if guest.created_at else None,
        "updated_at": guest.updated_at.isoformat() if guest.updated_at else None,
    }


@router.patch("/guests/{guest_id}")
async def update_guest(
    guest_id: uuid.UUID,
    data: GuestProfileUpdate,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(GuestProfile).where(GuestProfile.id == guest_id)
    )
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    for field in (
        "first_name", "last_name", "email", "phone",
        "language", "notes", "allergen_profile", "email_verified",
    ):
        value = getattr(data, field)
        if value is not None:
            setattr(guest, field, value)

    if data.password is not None:
        if len(data.password) < 8:
            raise HTTPException(
                status_code=400, detail="Passwort muss mindestens 8 Zeichen lang sein"
            )
        guest.password_hash = hash_password(data.password)

    await session.commit()
    await session.refresh(guest)
    return {
        "id": str(guest.id),
        "first_name": guest.first_name,
        "last_name": guest.last_name,
        "email": guest.email,
        "phone": guest.phone,
        "language": guest.language,
        "notes": guest.notes,
        "email_verified": guest.email_verified,
        "has_password": guest.password_hash is not None,
        "allergen_profile": guest.allergen_profile,
    }


@router.delete("/guests/{guest_id}", status_code=200)
async def delete_guest(
    guest_id: uuid.UUID,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(GuestProfile).where(GuestProfile.id == guest_id)
    )
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    await session.delete(guest)
    await session.commit()
    return {"deleted": True, "guest_id": str(guest_id)}


# ─── Reservierungs-Verwaltung ────────────────────────────────────────────────


@router.get("/reservations")
async def list_reservations(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    restaurant_id: uuid.UUID | None = Query(None),
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    query = select(Reservation, Restaurant.name.label("restaurant_name")).join(
        Restaurant, Reservation.tenant_id == Restaurant.id
    )
    if status:
        query = query.where(Reservation.status == status)
    if restaurant_id:
        query = query.where(Reservation.tenant_id == restaurant_id)
    query = query.order_by(Reservation.created_at.desc())

    count_q = select(func.count()).select_from(
        select(Reservation.id).where(
            *(
                [Reservation.status == status] if status else []
            ),
            *(
                [Reservation.tenant_id == restaurant_id] if restaurant_id else []
            ),
        ).subquery()
    )
    total = (await session.execute(count_q)).scalar() or 0

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await session.execute(query)
    rows = result.all()

    return {
        "items": [
            {
                "id": str(r.id),
                "tenant_id": str(r.tenant_id),
                "restaurant_name": restaurant_name,
                "guest_name": r.guest_name,
                "guest_email": r.guest_email,
                "guest_phone": r.guest_phone,
                "party_size": r.party_size,
                "start_at": r.start_at.isoformat() if r.start_at else None,
                "end_at": r.end_at.isoformat() if r.end_at else None,
                "status": r.status,
                "channel": r.channel,
                "special_requests": r.special_requests,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r, restaurant_name in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/reservations/{reservation_id}")
async def get_reservation(
    reservation_id: uuid.UUID,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(Reservation, Restaurant.name.label("restaurant_name")).join(
            Restaurant, Reservation.tenant_id == Restaurant.id
        ).where(Reservation.id == reservation_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Reservation not found")

    r, restaurant_name = row
    return {
        "id": str(r.id),
        "tenant_id": str(r.tenant_id),
        "restaurant_name": restaurant_name,
        "guest_name": r.guest_name,
        "guest_email": r.guest_email,
        "guest_phone": r.guest_phone,
        "party_size": r.party_size,
        "start_at": r.start_at.isoformat() if r.start_at else None,
        "end_at": r.end_at.isoformat() if r.end_at else None,
        "status": r.status,
        "channel": r.channel,
        "special_requests": r.special_requests,
        "notes": r.notes,
        "confirmation_code": r.confirmation_code,
        "canceled_reason": r.canceled_reason,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.patch("/reservations/{reservation_id}/status")
async def update_reservation_status(
    reservation_id: uuid.UUID,
    data: ReservationStatusUpdate,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    VALID_STATUSES = {
        "pending", "confirmed", "seated", "completed", "canceled", "no_show"
    }
    if data.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    result = await session.execute(
        select(Reservation).where(Reservation.id == reservation_id)
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    reservation.status = data.status
    now = datetime.now(UTC)
    status_ts_map = {
        "confirmed": "confirmed_at",
        "seated": "seated_at",
        "completed": "completed_at",
        "canceled": "canceled_at",
        "no_show": "no_show_at",
    }
    ts_field = status_ts_map.get(data.status)
    if ts_field:
        setattr(reservation, ts_field, now)
    if data.status == "canceled" and data.canceled_reason:
        reservation.canceled_reason = data.canceled_reason

    await session.commit()
    return {"id": str(reservation.id), "status": reservation.status}


# ─── Bewertungs-Moderation ───────────────────────────────────────────────────


@router.get("/reviews")
async def list_reviews(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    restaurant_id: uuid.UUID | None = Query(None),
    visible: bool | None = Query(None),
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    query = (
        select(
            Review,
            Restaurant.name.label("restaurant_name"),
            GuestProfile.first_name.label("guest_first_name"),
            GuestProfile.last_name.label("guest_last_name"),
        )
        .join(Restaurant, Review.tenant_id == Restaurant.id)
        .outerjoin(GuestProfile, Review.guest_profile_id == GuestProfile.id)
    )
    if restaurant_id:
        query = query.where(Review.tenant_id == restaurant_id)
    if visible is not None:
        query = query.where(Review.is_visible == visible)
    query = query.order_by(Review.created_at.desc())

    # Count
    count_base = select(Review.id)
    if restaurant_id:
        count_base = count_base.where(Review.tenant_id == restaurant_id)
    if visible is not None:
        count_base = count_base.where(Review.is_visible == visible)
    count_q = select(func.count()).select_from(count_base.subquery())
    total = (await session.execute(count_q)).scalar() or 0

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await session.execute(query)
    rows = result.all()

    return {
        "items": [
            {
                "id": str(rv.id),
                "tenant_id": str(rv.tenant_id),
                "restaurant_name": rname,
                "guest_profile_id": str(rv.guest_profile_id)
                if rv.guest_profile_id
                else None,
                "guest_name": f"{gfn or ''} {gln or ''}".strip() or None,
                "rating": rv.rating,
                "title": rv.title,
                "text": rv.text,
                "is_visible": rv.is_visible,
                "is_verified": rv.is_verified,
                "created_at": rv.created_at.isoformat()
                if rv.created_at
                else None,
            }
            for rv, rname, gfn, gln in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.patch("/reviews/{review_id}")
async def update_review_visibility(
    review_id: uuid.UUID,
    data: ReviewVisibilityUpdate,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(Review).where(Review.id == review_id)
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    review.is_visible = data.is_visible
    await session.commit()
    return {"id": str(review.id), "is_visible": review.is_visible}


@router.delete("/reviews/{review_id}", status_code=200)
async def delete_review(
    review_id: uuid.UUID,
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(Review).where(Review.id == review_id)
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    await session.delete(review)
    await session.commit()
    return {"deleted": True, "review_id": str(review_id)}


# ─── Statistiken ─────────────────────────────────────────────────────────────


@router.get("/stats")
async def get_stats(
    current_user=Depends(require_platform_admin),
    session: AsyncSession = Depends(get_db),
):
    thirty_days_ago = datetime.now(UTC) - timedelta(days=30)

    total_guests = (
        await session.execute(select(func.count(GuestProfile.id)))
    ).scalar() or 0

    total_reservations = (
        await session.execute(select(func.count(Reservation.id)))
    ).scalar() or 0

    total_reviews = (
        await session.execute(select(func.count(Review.id)))
    ).scalar() or 0

    total_restaurants = (
        await session.execute(select(func.count(Restaurant.id)))
    ).scalar() or 0

    # Reservations by status
    status_rows = (
        await session.execute(
            select(
                Reservation.status, func.count(Reservation.id)
            ).group_by(Reservation.status)
        )
    ).all()
    reservations_by_status = {row[0]: row[1] for row in status_rows}

    recent_guests_30d = (
        await session.execute(
            select(func.count(GuestProfile.id)).where(
                GuestProfile.created_at >= thirty_days_ago
            )
        )
    ).scalar() or 0

    recent_reservations_30d = (
        await session.execute(
            select(func.count(Reservation.id)).where(
                Reservation.created_at >= thirty_days_ago
            )
        )
    ).scalar() or 0

    return {
        "total_guests": total_guests,
        "total_reservations": total_reservations,
        "total_reviews": total_reviews,
        "total_restaurants": total_restaurants,
        "reservations_by_status": reservations_by_status,
        "recent_guests_30d": recent_guests_30d,
        "recent_reservations_30d": recent_reservations_30d,
    }
