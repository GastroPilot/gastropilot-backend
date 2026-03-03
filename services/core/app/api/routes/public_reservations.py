"""Public reservation endpoints for the booking widget."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.block import Block, BlockAssignment
from app.models.prepayment import ReservationPrepayment
from app.models.reservation import Guest, Reservation
from app.models.restaurant import Restaurant, Table
from app.models.table_config import ReservationTable, TableDayConfig
from app.models.upsell import ReservationUpsellPackage, UpsellPackage
from app.models.user import GuestProfile
from app.models.voucher import Voucher, VoucherUsage
from app.utils.ics_generator import generate_ics_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/restaurants", tags=["public-reservations"])

RESTAURANT_TZ = ZoneInfo("Europe/Berlin")


# --- Schemas ---


class NotificationChannels(BaseModel):
    email: bool = True
    sms: bool = False
    whatsapp: bool = False


class PublicReservationCreate(BaseModel):
    guest_name: str
    guest_email: EmailStr
    guest_phone: Optional[str] = None
    party_size: int
    desired_date: date
    desired_time: str  # HH:MM
    special_requests: Optional[str] = None
    channel: str = "web"
    privacy_accepted: bool = True
    notification_channels: NotificationChannels = NotificationChannels()
    voucher_code: Optional[str] = None
    upsell_package_ids: Optional[list[UUID]] = None
    prepayment_required: bool = False


class AvailabilitySlot(BaseModel):
    time: str
    available: bool
    tables_available: int


class AvailabilityResponse(BaseModel):
    date: str
    slots: list[AvailabilitySlot]
    max_party_size: int


class PublicRestaurantInfo(BaseModel):
    id: UUID
    name: str
    slug: str | None
    address: str | None = None
    phone: str | None = None
    description: str | None = None
    opening_hours: dict | None = None
    max_party_size: int
    lead_time_hours: int


class PublicReservationResponse(BaseModel):
    success: bool
    confirmation_code: str
    restaurant_name: str
    guest_name: str
    date: str
    time: str
    party_size: int
    table_number: str | None = None
    message: str
    prepayment_checkout_url: str | None = None
    prepayment_amount: float | None = None


class ReservationUpdateRequest(BaseModel):
    desired_date: date | None = None
    desired_time: str | None = None
    party_size: int | None = None
    special_requests: str | None = None


# --- Helpers ---


async def _get_restaurant_by_slug(slug: str, db: AsyncSession) -> Restaurant:
    result = await db.execute(select(Restaurant).where(Restaurant.slug == slug))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    if not restaurant.public_booking_enabled:
        raise HTTPException(status_code=403, detail="Public booking not enabled")
    return restaurant


async def _find_available_table(
    db: AsyncSession,
    tenant_id: UUID,
    start_at: datetime,
    end_at: datetime,
    party_size: int,
    exclude_reservation_id: UUID | None = None,
) -> Table | None:
    """Find smallest available table that fits the party."""
    tables_result = await db.execute(
        select(Table)
        .where(
            and_(
                Table.tenant_id == tenant_id,
                Table.is_active.is_(True),
                Table.capacity >= party_size,
            )
        )
        .order_by(Table.capacity)
    )
    tables = tables_result.scalars().all()

    # Get blocked table IDs
    blocks_query = (
        select(BlockAssignment.table_id)
        .join(Block, BlockAssignment.block_id == Block.id)
        .where(
            and_(
                Block.tenant_id == tenant_id,
                Block.start_at < end_at,
                Block.end_at > start_at,
            )
        )
    )
    blocked_result = await db.execute(blocks_query)
    blocked_table_ids = {row[0] for row in blocked_result.all()}

    # Get reserved table IDs
    reserved_query = select(Reservation.table_id).where(
        and_(
            Reservation.tenant_id == tenant_id,
            Reservation.table_id.isnot(None),
            Reservation.status.in_(["pending", "confirmed", "seated"]),
            Reservation.start_at < end_at,
            Reservation.end_at > start_at,
        )
    )
    if exclude_reservation_id:
        reserved_query = reserved_query.where(Reservation.id != exclude_reservation_id)
    reserved_result = await db.execute(reserved_query)
    reserved_table_ids = {row[0] for row in reserved_result.all()}

    unavailable = blocked_table_ids | reserved_table_ids
    for table in tables:
        if table.id not in unavailable:
            return table
    return None


async def _count_available_tables(
    db: AsyncSession,
    tenant_id: UUID,
    start_at: datetime,
    end_at: datetime,
    party_size: int,
) -> int:
    tables_result = await db.execute(
        select(Table).where(
            and_(
                Table.tenant_id == tenant_id,
                Table.is_active.is_(True),
                Table.capacity >= party_size,
            )
        )
    )
    tables = tables_result.scalars().all()

    blocks_query = (
        select(BlockAssignment.table_id)
        .join(Block, BlockAssignment.block_id == Block.id)
        .where(
            and_(
                Block.tenant_id == tenant_id,
                Block.start_at < end_at,
                Block.end_at > start_at,
            )
        )
    )
    blocked_result = await db.execute(blocks_query)
    blocked_ids = {row[0] for row in blocked_result.all()}

    reserved_query = select(Reservation.table_id).where(
        and_(
            Reservation.tenant_id == tenant_id,
            Reservation.table_id.isnot(None),
            Reservation.status.in_(["pending", "confirmed", "seated"]),
            Reservation.start_at < end_at,
            Reservation.end_at > start_at,
        )
    )
    reserved_result = await db.execute(reserved_query)
    reserved_ids = {row[0] for row in reserved_result.all()}

    unavailable = blocked_ids | reserved_ids
    return sum(1 for t in tables if t.id not in unavailable)


# --- Endpoints ---


@router.get("/{slug}/info", response_model=PublicRestaurantInfo)
async def get_restaurant_info(slug: str, db: AsyncSession = Depends(get_db)):
    restaurant = await _get_restaurant_by_slug(slug, db)
    return PublicRestaurantInfo(
        id=restaurant.id,
        name=restaurant.name,
        slug=restaurant.slug,
        address=restaurant.address,
        phone=restaurant.phone,
        description=restaurant.description,
        opening_hours=restaurant.opening_hours,
        max_party_size=restaurant.booking_max_party_size,
        lead_time_hours=restaurant.booking_lead_time_hours,
    )


@router.get("/{slug}/availability", response_model=AvailabilityResponse)
async def check_availability(
    slug: str,
    check_date: date = Query(..., alias="date"),
    party_size: int = Query(2, ge=1),
    db: AsyncSession = Depends(get_db),
):
    restaurant = await _get_restaurant_by_slug(slug, db)

    if party_size > restaurant.booking_max_party_size:
        raise HTTPException(status_code=400, detail="Party size exceeds maximum")

    today = date.today()
    if check_date < today:
        raise HTTPException(status_code=400, detail="Date cannot be in the past")

    duration = restaurant.booking_default_duration
    now_local = datetime.now(RESTAURANT_TZ)

    slots = []
    for hour in range(11, 23):
        for minute in (0, 30):
            time_str = f"{hour:02d}:{minute:02d}"
            slot_local = datetime.combine(check_date, datetime.min.time()).replace(
                hour=hour, minute=minute, tzinfo=RESTAURANT_TZ
            )

            # Skip past slots and slots within lead time
            if slot_local <= now_local + timedelta(hours=restaurant.booking_lead_time_hours):
                slots.append(AvailabilitySlot(time=time_str, available=False, tables_available=0))
                continue

            slot_utc = slot_local.astimezone(UTC)
            end_utc = slot_utc + timedelta(minutes=duration)

            count = await _count_available_tables(db, restaurant.id, slot_utc, end_utc, party_size)
            slots.append(
                AvailabilitySlot(time=time_str, available=count > 0, tables_available=count)
            )

    return AvailabilityResponse(
        date=check_date.isoformat(),
        slots=slots,
        max_party_size=restaurant.booking_max_party_size,
    )


@router.post(
    "/{slug}/reservations",
    response_model=PublicReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reservation(
    slug: str,
    body: PublicReservationCreate,
    db: AsyncSession = Depends(get_db),
):
    restaurant = await _get_restaurant_by_slug(slug, db)

    if body.party_size > restaurant.booking_max_party_size:
        raise HTTPException(status_code=400, detail="Party size exceeds maximum")

    # Parse desired time
    try:
        hour, minute = map(int, body.desired_time.split(":"))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM")

    slot_local = datetime.combine(body.desired_date, datetime.min.time()).replace(
        hour=hour, minute=minute, tzinfo=RESTAURANT_TZ
    )
    now_local = datetime.now(RESTAURANT_TZ)
    lead_cutoff = now_local + timedelta(hours=restaurant.booking_lead_time_hours)
    if slot_local <= lead_cutoff:
        raise HTTPException(
            status_code=400, detail="Reservation time does not meet lead time requirement"
        )

    start_utc = slot_local.astimezone(UTC)
    duration = restaurant.booking_default_duration
    end_utc = start_utc + timedelta(minutes=duration)

    # Find table
    table = await _find_available_table(db, restaurant.id, start_utc, end_utc, body.party_size)
    if not table:
        raise HTTPException(status_code=409, detail="No tables available for the requested time")

    # Create or find guest
    guest_result = await db.execute(
        select(Guest).where(and_(Guest.tenant_id == restaurant.id, Guest.email == body.guest_email))
    )
    guest = guest_result.scalar_one_or_none()

    # Look up global guest profile by email to link reservation to profile
    profile_result = await db.execute(
        select(GuestProfile).where(GuestProfile.email == body.guest_email)
    )
    guest_profile = profile_result.scalar_one_or_none()

    if not guest:
        name_parts = body.guest_name.strip().split(" ", 1)
        guest = Guest(
            tenant_id=restaurant.id,
            first_name=name_parts[0],
            last_name=name_parts[1] if len(name_parts) > 1 else "",
            email=body.guest_email,
            phone=body.guest_phone,
            guest_profile_id=guest_profile.id if guest_profile else None,
        )
        db.add(guest)
        await db.flush()
    elif guest_profile and not guest.guest_profile_id:
        # Link existing guest to profile if not yet linked
        guest.guest_profile_id = guest_profile.id

    confirmation_code = secrets.token_urlsafe(6).upper()[:8]

    reservation = Reservation(
        tenant_id=restaurant.id,
        guest_id=guest.id,
        table_id=table.id,
        start_at=start_utc,
        end_at=end_utc,
        party_size=body.party_size,
        status="confirmed",
        channel=body.channel,
        guest_name=body.guest_name,
        guest_email=body.guest_email,
        guest_phone=body.guest_phone or "",
        confirmation_code=confirmation_code,
        special_requests=body.special_requests,
        confirmed_at=datetime.now(UTC),
    )

    # Voucher processing
    if body.voucher_code:
        voucher_result = await db.execute(
            select(Voucher).where(
                and_(
                    Voucher.code == body.voucher_code.upper().strip(),
                    Voucher.tenant_id == restaurant.id,
                    Voucher.is_active.is_(True),
                )
            )
        )
        voucher = voucher_result.scalar_one_or_none()
        if voucher:
            today = date.today()
            valid = True
            if voucher.valid_from and today < voucher.valid_from:
                valid = False
            if voucher.valid_until and today > voucher.valid_until:
                valid = False
            if voucher.max_uses and voucher.used_count >= voucher.max_uses:
                valid = False

            if valid:
                discount = voucher.value
                if voucher.type == "percentage":
                    discount = 0  # percentage needs order value context
                reservation.voucher_id = voucher.id
                reservation.voucher_discount_amount = discount
                voucher.used_count += 1
                db.add(
                    VoucherUsage(
                        voucher_id=voucher.id,
                        tenant_id=restaurant.id,
                        used_by_email=body.guest_email,
                        discount_amount=discount,
                    )
                )

    db.add(reservation)
    await db.flush()

    # Reservation-Table junction
    db.add(
        ReservationTable(
            reservation_id=reservation.id,
            table_id=table.id,
            tenant_id=restaurant.id,
            start_at=start_utc,
            end_at=end_utc,
        )
    )

    # Upsell packages
    prepayment_amount = 0.0
    if body.upsell_package_ids:
        for pkg_id in body.upsell_package_ids:
            pkg_result = await db.execute(
                select(UpsellPackage).where(
                    and_(
                        UpsellPackage.id == pkg_id,
                        UpsellPackage.tenant_id == restaurant.id,
                        UpsellPackage.is_active.is_(True),
                    )
                )
            )
            pkg = pkg_result.scalar_one_or_none()
            if pkg:
                db.add(
                    ReservationUpsellPackage(
                        reservation_id=reservation.id,
                        upsell_package_id=pkg.id,
                        tenant_id=restaurant.id,
                        price_at_time=pkg.price,
                    )
                )
                prepayment_amount += pkg.price

    # Prepayment
    checkout_url = None
    if body.prepayment_required and prepayment_amount > 0:
        reservation.prepayment_required = True
        reservation.prepayment_amount = prepayment_amount
        # SumUp checkout creation would go here
        # For now, create a pending prepayment record
        db.add(
            ReservationPrepayment(
                reservation_id=reservation.id,
                tenant_id=restaurant.id,
                amount=prepayment_amount,
                payment_provider="sumup",
                status="pending",
            )
        )

    await db.commit()
    await db.refresh(reservation)

    return PublicReservationResponse(
        success=True,
        confirmation_code=confirmation_code,
        restaurant_name=restaurant.name,
        guest_name=body.guest_name,
        date=body.desired_date.isoformat(),
        time=body.desired_time,
        party_size=body.party_size,
        table_number=table.number,
        message="Reservation confirmed",
        prepayment_checkout_url=checkout_url,
        prepayment_amount=prepayment_amount if prepayment_amount > 0 else None,
    )


@router.get("/{slug}/reservations/{code}")
async def get_reservation_status(
    slug: str,
    code: str,
    db: AsyncSession = Depends(get_db),
):
    restaurant = await _get_restaurant_by_slug(slug, db)
    result = await db.execute(
        select(Reservation).where(
            and_(
                Reservation.tenant_id == restaurant.id,
                Reservation.confirmation_code == code,
            )
        )
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    now_utc = datetime.now(UTC)
    hours_until = (reservation.start_at - now_utc).total_seconds() / 3600
    can_modify = reservation.status in ("pending", "confirmed") and hours_until >= 2

    table_number = None
    if reservation.table_id:
        table_result = await db.execute(select(Table).where(Table.id == reservation.table_id))
        table = table_result.scalar_one_or_none()
        if table:
            table_number = table.number

    return {
        "confirmation_code": reservation.confirmation_code,
        "status": reservation.status,
        "guest_name": reservation.guest_name,
        "guest_email": reservation.guest_email,
        "date": reservation.start_at.astimezone(RESTAURANT_TZ).date().isoformat(),
        "time": reservation.start_at.astimezone(RESTAURANT_TZ).strftime("%H:%M"),
        "party_size": reservation.party_size,
        "table_number": table_number,
        "special_requests": reservation.special_requests,
        "can_modify": can_modify,
        "hours_until_reservation": round(hours_until, 1),
    }


@router.put("/{slug}/reservations/{code}/cancel")
async def cancel_reservation(
    slug: str,
    code: str,
    db: AsyncSession = Depends(get_db),
):
    restaurant = await _get_restaurant_by_slug(slug, db)
    result = await db.execute(
        select(Reservation).where(
            and_(
                Reservation.tenant_id == restaurant.id,
                Reservation.confirmation_code == code,
            )
        )
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if reservation.status in ("seated", "completed", "canceled"):
        raise HTTPException(
            status_code=400, detail=f"Cannot cancel reservation with status {reservation.status}"
        )

    reservation.status = "canceled"
    reservation.canceled_at = datetime.now(UTC)
    reservation.canceled_reason = "Canceled by guest"
    await db.commit()

    return {"message": "Reservation canceled", "confirmation_code": code}


@router.get("/{slug}/reservations/{code}/ics")
async def download_ics(
    slug: str,
    code: str,
    db: AsyncSession = Depends(get_db),
):
    restaurant = await _get_restaurant_by_slug(slug, db)
    result = await db.execute(
        select(Reservation).where(
            and_(
                Reservation.tenant_id == restaurant.id,
                Reservation.confirmation_code == code,
            )
        )
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    ics_content = generate_ics_file(
        summary=f"Reservierung bei {restaurant.name}",
        start=reservation.start_at,
        end=reservation.end_at,
        description=f"Party: {reservation.party_size} Personen\nCode: {reservation.confirmation_code}",
        location=restaurant.address,
        organizer_name=restaurant.name,
        organizer_email=restaurant.email,
        attendee_name=reservation.guest_name,
        attendee_email=reservation.guest_email,
    )

    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="reservation-{code}.ics"'},
    )


@router.get("/{slug}/upsell-packages")
async def list_public_upsell_packages(
    slug: str,
    party_size: int = Query(2, ge=1),
    check_date: date = Query(None, alias="date"),
    db: AsyncSession = Depends(get_db),
):
    restaurant = await _get_restaurant_by_slug(slug, db)
    result = await db.execute(
        select(UpsellPackage)
        .where(
            and_(
                UpsellPackage.tenant_id == restaurant.id,
                UpsellPackage.is_active.is_(True),
            )
        )
        .order_by(UpsellPackage.display_order)
    )
    packages = result.scalars().all()

    available = []
    target_date = check_date or date.today()
    weekday = target_date.weekday()

    for pkg in packages:
        if pkg.available_from_date and target_date < pkg.available_from_date:
            continue
        if pkg.available_until_date and target_date > pkg.available_until_date:
            continue
        if pkg.min_party_size and party_size < pkg.min_party_size:
            continue
        if pkg.max_party_size and party_size > pkg.max_party_size:
            continue
        if pkg.available_weekdays and weekday not in pkg.available_weekdays:
            continue
        available.append(
            {
                "id": str(pkg.id),
                "name": pkg.name,
                "description": pkg.description,
                "price": pkg.price,
                "image_url": pkg.image_url,
            }
        )

    return available


@router.post("/{slug}/voucher/validate")
async def validate_voucher(
    slug: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    restaurant = await _get_restaurant_by_slug(slug, db)
    code = body.get("code", "").upper().strip()
    if not code:
        return {"valid": False, "message": "No voucher code provided"}

    result = await db.execute(
        select(Voucher).where(
            and_(
                Voucher.code == code,
                Voucher.tenant_id == restaurant.id,
            )
        )
    )
    voucher = result.scalar_one_or_none()
    if not voucher:
        return {"valid": False, "message": "Voucher not found"}

    if not voucher.is_active:
        return {"valid": False, "message": "Voucher is inactive"}

    today = date.today()
    if voucher.valid_from and today < voucher.valid_from:
        return {"valid": False, "message": "Voucher not yet valid"}
    if voucher.valid_until and today > voucher.valid_until:
        return {"valid": False, "message": "Voucher expired"}
    if voucher.max_uses and voucher.used_count >= voucher.max_uses:
        return {"valid": False, "message": "Voucher usage limit reached"}

    return {
        "valid": True,
        "voucher_id": str(voucher.id),
        "type": voucher.type,
        "value": voucher.value,
        "name": voucher.name,
    }
