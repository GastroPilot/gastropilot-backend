"""
Public Reservation API - Öffentliche Endpoints ohne Authentifizierung.

Ermöglicht Gästen, Reservierungen über Web-Formular oder WhatsApp vorzunehmen.
"""

import logging
import secrets
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Block,
    BlockAssignment,
    Reservation,
    ReservationPrepayment,
    ReservationTable,
    ReservationUpsellPackage,
    Restaurant,
    Table,
    UpsellPackage,
    Voucher,
    VoucherUsage,
)
from app.dependencies import get_session
from app.services.notification_service import ReservationNotification, notification_service
from app.services.sumup_service import SumUpService
from app.settings import RESERVATION_WIDGET_URL, SUMUP_API_KEY, SUMUP_MERCHANT_CODE
from app.utils.ics_generator import generate_ics_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/restaurants", tags=["public-reservations"])


# ============================================================================
# Schemas für öffentliche Reservierungen
# ============================================================================


class NotificationChannels(BaseModel):
    """Gewählte Benachrichtigungskanäle."""

    email: bool = True
    sms: bool = False
    whatsapp: bool = False


class PublicReservationCreate(BaseModel):
    """Schema für öffentliche Reservierungsanfrage."""

    guest_name: str = Field(min_length=2, max_length=240)
    guest_email: EmailStr
    guest_phone: str = Field(min_length=5, max_length=32)
    party_size: int = Field(gt=0, le=50)
    desired_date: date
    desired_time: str = Field(pattern=r"^\d{2}:\d{2}$")  # HH:MM Format
    special_requests: str | None = Field(None, max_length=1000)
    channel: str = Field(default="web", pattern="^(web|whatsapp|phone)$")
    privacy_accepted: bool = True
    notification_channels: NotificationChannels = Field(default_factory=NotificationChannels)
    # Neue Felder für beworbene Features
    voucher_code: str | None = Field(None, max_length=64)  # Gutschein-Code
    upsell_package_ids: list[int] | None = Field(None)  # IDs der gewählten Upsell-Pakete
    prepayment_required: bool = False  # Ist Vorauszahlung gewünscht/erforderlich?


class PublicReservationResponse(BaseModel):
    """Response nach erfolgreicher Reservierung."""

    success: bool
    confirmation_code: str
    restaurant_name: str
    guest_name: str
    date: str
    time: str
    party_size: int
    table_number: str | None = None
    message: str
    prepayment_checkout_url: str | None = None  # URL für Vorauszahlung falls erforderlich
    prepayment_amount: float | None = None  # Betrag der Vorauszahlung


class AvailabilitySlot(BaseModel):
    """Verfügbarer Zeitslot."""

    time: str
    available: bool
    tables_available: int


class AvailabilityResponse(BaseModel):
    """Response mit verfügbaren Zeitslots."""

    date: str
    slots: list[AvailabilitySlot]
    max_party_size: int


class PublicRestaurantInfo(BaseModel):
    """Öffentliche Restaurant-Informationen."""

    id: int
    name: str
    slug: str
    address: str | None = None
    phone: str | None = None
    description: str | None = None
    opening_hours: dict | None = None
    max_party_size: int
    lead_time_hours: int


# ============================================================================
# Helper Functions
# ============================================================================


async def _get_restaurant_by_slug(slug: str, session: AsyncSession) -> Restaurant:
    """Lädt Restaurant by Slug oder wirft 404."""
    result = await session.execute(select(Restaurant).where(Restaurant.slug == slug))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    if not restaurant.public_booking_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Online reservations are not available for this restaurant",
        )
    return restaurant


def _generate_confirmation_code() -> str:
    """Generiert einen eindeutigen Bestätigungscode."""
    return secrets.token_urlsafe(6).upper()[:8]


async def _find_available_table(
    restaurant_id: int,
    desired_datetime: datetime,
    end_datetime: datetime,
    party_size: int,
    session: AsyncSession,
    exclude_reservation_id: int | None = None,
) -> Table | None:
    """
    Findet den besten verfügbaren Tisch für eine Reservierung.

    Kriterien:
    1. Kapazität >= party_size
    2. Keine überlappende Reservierung (außer exclude_reservation_id)
    3. Keine Blockierung im Zeitraum
    4. Kleinster passender Tisch (optimale Auslastung)

    Args:
        exclude_reservation_id: Optional - Reservierungs-ID die ignoriert werden soll
                               (für Änderungen bestehender Reservierungen)
    """
    # Lade alle aktiven Tische
    tables_result = await session.execute(
        select(Table)
        .where(
            and_(
                Table.restaurant_id == restaurant_id,
                Table.is_active == True,
                Table.capacity >= party_size,
            )
        )
        .order_by(Table.capacity)  # Kleinster zuerst
    )
    tables = tables_result.scalars().all()

    if not tables:
        return None

    # Prüfe jeden Tisch auf Verfügbarkeit
    for table in tables:
        # Prüfe auf überlappende Reservierungen
        reservation_query = and_(
            Reservation.table_id == table.id,
            Reservation.status.in_(["pending", "confirmed", "seated"]),
            Reservation.start_at < end_datetime,
            Reservation.end_at > desired_datetime,
        )

        # Exkludiere bestimmte Reservierung wenn angegeben
        if exclude_reservation_id:
            reservation_query = and_(
                reservation_query,
                Reservation.id != exclude_reservation_id,
            )

        reservation_result = await session.execute(select(Reservation).where(reservation_query))
        if reservation_result.scalar_one_or_none():
            continue  # Tisch ist belegt

        # Prüfe auf Blockierungen
        block_result = await session.execute(
            select(BlockAssignment)
            .join(Block)
            .where(
                and_(
                    BlockAssignment.table_id == table.id,
                    Block.restaurant_id == restaurant_id,
                    Block.start_at < end_datetime,
                    Block.end_at > desired_datetime,
                )
            )
        )
        if block_result.scalar_one_or_none():
            continue  # Tisch ist blockiert

        # Tisch ist verfügbar!
        return table

    return None


async def _get_available_slots(
    restaurant: Restaurant,
    check_date: date,
    party_size: int,
    session: AsyncSession,
) -> list[AvailabilitySlot]:
    """Ermittelt verfügbare Zeitslots für ein Datum."""
    slots = []

    # Zeitzone Setup
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    restaurant_tz = ZoneInfo("Europe/Berlin")

    # Standard Zeitslots (30-Minuten-Intervalle von 11:00 bis 22:00)
    # TODO: Aus opening_hours ableiten
    start_hour = 11
    end_hour = 22

    duration_minutes = restaurant.booking_default_duration

    now = datetime.now(UTC)
    min_booking_time = now + timedelta(hours=restaurant.booking_lead_time_hours)

    for hour in range(start_hour, end_hour):
        for minute in [0, 30]:
            slot_time = time(hour, minute)
            # Lokale Zeit -> UTC
            local_dt = datetime.combine(check_date, slot_time).replace(tzinfo=restaurant_tz)
            slot_datetime = local_dt.astimezone(UTC)
            end_datetime = slot_datetime + timedelta(minutes=duration_minutes)

            # Prüfe ob Slot in der Vergangenheit liegt
            if slot_datetime < min_booking_time:
                slots.append(
                    AvailabilitySlot(
                        time=f"{hour:02d}:{minute:02d}",
                        available=False,
                        tables_available=0,
                    )
                )
                continue

            # Zähle verfügbare Tische
            available_count = 0
            tables_result = await session.execute(
                select(Table).where(
                    and_(
                        Table.restaurant_id == restaurant.id,
                        Table.is_active == True,
                        Table.capacity >= party_size,
                    )
                )
            )
            tables = tables_result.scalars().all()

            for table in tables:
                # Prüfe Reservierungen
                res_result = await session.execute(
                    select(Reservation).where(
                        and_(
                            Reservation.table_id == table.id,
                            Reservation.status.in_(["pending", "confirmed", "seated"]),
                            Reservation.start_at < end_datetime,
                            Reservation.end_at > slot_datetime,
                        )
                    )
                )
                if res_result.scalar_one_or_none():
                    continue

                # Prüfe Blockierungen
                block_result = await session.execute(
                    select(BlockAssignment)
                    .join(Block)
                    .where(
                        and_(
                            BlockAssignment.table_id == table.id,
                            Block.restaurant_id == restaurant.id,
                            Block.start_at < end_datetime,
                            Block.end_at > slot_datetime,
                        )
                    )
                )
                if block_result.scalar_one_or_none():
                    continue

                available_count += 1

            slots.append(
                AvailabilitySlot(
                    time=f"{hour:02d}:{minute:02d}",
                    available=available_count > 0,
                    tables_available=available_count,
                )
            )

    return slots


# ============================================================================
# API Endpoints
# ============================================================================


@router.get("/{restaurant_slug}/info", response_model=PublicRestaurantInfo)
async def get_restaurant_info(
    restaurant_slug: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Gibt öffentliche Restaurant-Informationen zurück.

    Wird vom Reservierungsformular beim Laden verwendet.
    """
    restaurant = await _get_restaurant_by_slug(restaurant_slug, session)

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


@router.get("/{restaurant_slug}/availability", response_model=AvailabilityResponse)
async def check_availability(
    restaurant_slug: str,
    check_date: date = Query(..., alias="date"),
    party_size: int = Query(2, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """
    Prüft die Verfügbarkeit für ein bestimmtes Datum.

    Gibt alle Zeitslots mit Verfügbarkeitsinfo zurück.
    """
    restaurant = await _get_restaurant_by_slug(restaurant_slug, session)

    # Prüfe ob Datum in der Vergangenheit
    today = date.today()
    if check_date < today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot check availability for past dates",
        )

    # Prüfe maximale Personenanzahl
    if party_size > restaurant.booking_max_party_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum party size is {restaurant.booking_max_party_size}",
        )

    slots = await _get_available_slots(restaurant, check_date, party_size, session)

    return AvailabilityResponse(
        date=check_date.isoformat(),
        slots=slots,
        max_party_size=restaurant.booking_max_party_size,
    )


@router.post("/{restaurant_slug}/reserve", response_model=PublicReservationResponse)
async def create_public_reservation(
    restaurant_slug: str,
    reservation_data: PublicReservationCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """
    Erstellt eine öffentliche Reservierung.

    Die KI wählt automatisch den besten verfügbaren Tisch.
    Bestätigungen werden über alle Kanäle gesendet (E-Mail, SMS, WhatsApp).
    """
    restaurant = await _get_restaurant_by_slug(restaurant_slug, session)

    # Validiere Personenanzahl
    if reservation_data.party_size > restaurant.booking_max_party_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum party size is {restaurant.booking_max_party_size}",
        )

    # Berechne Start- und Endzeit
    try:
        hour, minute = map(int, reservation_data.desired_time.split(":"))
        desired_time = time(hour, minute)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid time format. Use HH:MM"
        )

    # Kombiniere Datum und Zeit in lokaler Zeitzone des Restaurants
    # Dann konvertiere zu UTC für Speicherung
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    # Restaurant-Zeitzone (Standard: Europe/Berlin)
    restaurant_tz = ZoneInfo("Europe/Berlin")

    # Erstelle lokale Zeit
    local_dt = datetime.combine(reservation_data.desired_date, desired_time).replace(
        tzinfo=restaurant_tz
    )

    # Konvertiere zu UTC
    start_at = local_dt.astimezone(UTC)
    end_at = start_at + timedelta(minutes=restaurant.booking_default_duration)

    # Prüfe Mindestvorlaufzeit
    now = datetime.now(UTC)
    min_booking_time = now + timedelta(hours=restaurant.booking_lead_time_hours)
    if start_at < min_booking_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Reservations must be made at least {restaurant.booking_lead_time_hours} hours in advance",
        )

    # Finde verfügbaren Tisch (KI-gestützte Zuordnung)
    table = await _find_available_table(
        restaurant.id,
        start_at,
        end_at,
        reservation_data.party_size,
        session,
    )

    if not table:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No tables available for the requested time. Please try a different time.",
        )

    # Validiere und verarbeite Gutschein
    voucher = None
    voucher_discount_amount = None
    if reservation_data.voucher_code:
        voucher_result = await session.execute(
            select(Voucher).where(
                Voucher.code == reservation_data.voucher_code.upper(),
                Voucher.restaurant_id == restaurant.id,
                Voucher.is_active == True,
            )
        )
        voucher = voucher_result.scalar_one_or_none()

        if voucher:
            # Validiere Gutschein (vereinfachte Validierung - vollständige Validierung sollte über /validate Endpoint erfolgen)
            today = date.today()
            if (
                (voucher.valid_from and today < voucher.valid_from)
                or (voucher.valid_until and today > voucher.valid_until)
                or (voucher.max_uses and voucher.used_count >= voucher.max_uses)
            ):
                voucher = None  # Gutschein ungültig
            else:
                # Berechne Rabattbetrag (vereinfacht - könnte auch auf Basis von Paketpreisen berechnet werden)
                base_amount = 0.0  # TODO: Berechne basierend auf Upsell-Paketen oder Standardbetrag
                if voucher.type == "fixed":
                    voucher_discount_amount = min(voucher.value, base_amount)
                elif voucher.type == "percentage":
                    voucher_discount_amount = base_amount * (voucher.value / 100)
        else:
            # Gutschein nicht gefunden - könnte Warnung geben, aber Reservierung trotzdem erstellen
            logger.warning(
                f"Voucher code {reservation_data.voucher_code} not found for restaurant {restaurant.id}"
            )

    # Validiere Upsell-Pakete
    upsell_packages = []
    if reservation_data.upsell_package_ids:
        package_result = await session.execute(
            select(UpsellPackage).where(
                UpsellPackage.id.in_(reservation_data.upsell_package_ids),
                UpsellPackage.restaurant_id == restaurant.id,
                UpsellPackage.is_active == True,
            )
        )
        upsell_packages = list(package_result.scalars().all())

        # Prüfe Verfügbarkeit für jedes Paket
        available_packages = []
        for package in upsell_packages:
            # Vereinfachte Verfügbarkeitsprüfung
            today = date.today()
            if (
                (
                    package.available_from_date
                    and reservation_data.desired_date < package.available_from_date
                )
                or (
                    package.available_until_date
                    and reservation_data.desired_date > package.available_until_date
                )
                or (package.min_party_size and reservation_data.party_size < package.min_party_size)
                or (package.max_party_size and reservation_data.party_size > package.max_party_size)
            ):
                continue  # Paket nicht verfügbar
            available_packages.append(package)
        upsell_packages = available_packages

    # Generiere Bestätigungscode
    confirmation_code = _generate_confirmation_code()

    # Erstelle Reservierung - als "confirmed" mit zugewiesenem Tisch
    reservation = Reservation(
        restaurant_id=restaurant.id,
        table_id=table.id,
        start_at=start_at,
        end_at=end_at,
        party_size=reservation_data.party_size,
        status="confirmed",
        channel=reservation_data.channel,
        guest_name=reservation_data.guest_name,
        guest_email=reservation_data.guest_email,
        guest_phone=reservation_data.guest_phone,
        confirmation_code=confirmation_code,
        special_requests=reservation_data.special_requests,
        voucher_id=voucher.id if voucher else None,
        voucher_discount_amount=voucher_discount_amount,
        prepayment_required=reservation_data.prepayment_required,
    )

    try:
        session.add(reservation)
        await session.flush()

        # Erstelle ReservationTable Verknüpfung
        rt = ReservationTable(
            reservation_id=reservation.id,
            table_id=table.id,
            start_at=start_at,
            end_at=end_at,
        )
        session.add(rt)

        # Speichere Voucher-Nutzung falls vorhanden
        if voucher and voucher_discount_amount:
            voucher.used_count += 1
            voucher_usage = VoucherUsage(
                voucher_id=voucher.id,
                reservation_id=reservation.id,
                used_by_email=reservation_data.guest_email,
                discount_amount=voucher_discount_amount,
            )
            session.add(voucher_usage)

        # Speichere Upsell-Pakete mit Reservierung verknüpfen
        for package in upsell_packages:
            reservation_upsell = ReservationUpsellPackage(
                reservation_id=reservation.id,
                upsell_package_id=package.id,
                price_at_time=package.price,
            )
            session.add(reservation_upsell)

        # Berechne Gesamtbetrag für Prepayment (Upsell-Pakete + optionaler Standardbetrag)
        prepayment_amount = None
        if reservation_data.prepayment_required:
            total_amount = 0.0
            if upsell_packages:
                total_amount = sum(pkg.price for pkg in upsell_packages)
            # Falls keine Upsell-Pakete, könnte man einen Standardbetrag verwenden
            # Für jetzt verwenden wir nur Upsell-Pakete als Basis
            if total_amount > 0:
                prepayment_amount = total_amount

        await session.commit()
        await session.refresh(reservation)

        # Erstelle Prepayment falls gewünscht
        prepayment_checkout_url = None
        if reservation_data.prepayment_required and prepayment_amount and prepayment_amount > 0:
            try:
                if SUMUP_API_KEY and SUMUP_MERCHANT_CODE:
                    sumup_service = SumUpService(SUMUP_API_KEY)

                    checkout_reference = f"RES-{confirmation_code}-PREPAY-{reservation.id}"
                    return_url = f"{RESERVATION_WIDGET_URL}/{restaurant.slug}/manage/{confirmation_code}?prepayment=success"
                    description = (
                        f"Vorauszahlung für Reservierung {confirmation_code} bei {restaurant.name}"
                    )

                    checkout_response = await sumup_service.create_checkout(
                        merchant_code=SUMUP_MERCHANT_CODE,
                        amount=prepayment_amount,
                        currency="EUR",
                        checkout_reference=checkout_reference,
                        description=description,
                        return_url=return_url,
                    )

                    checkout_id = checkout_response.get("id") or checkout_response.get(
                        "checkout_id"
                    )

                    prepayment = ReservationPrepayment(
                        reservation_id=reservation.id,
                        restaurant_id=restaurant.id,
                        amount=prepayment_amount,
                        currency="EUR",
                        payment_provider="sumup",
                        payment_id=checkout_id,
                        transaction_id=checkout_response.get("client_transaction_id"),
                        status="processing",
                        payment_data=checkout_response,
                    )

                    session.add(prepayment)
                    await session.commit()

                    prepayment_checkout_url = f"https://checkout.sumup.com/checkout/{checkout_id}"
                    logger.info(
                        f"Prepayment created for reservation {reservation.id}: {checkout_id}"
                    )
            except Exception as prepay_error:
                logger.error(f"Failed to create prepayment: {prepay_error}")
                # Prepayment-Fehler sollten die Reservierung nicht abbrechen

        logger.info(
            f"Public reservation created: {confirmation_code} for {reservation_data.guest_name} "
            f"at {restaurant.name}, table {table.number}, {start_at}"
        )

        # Benachrichtigungen senden basierend auf gewählten Kanälen
        try:
            # Bestimme gewählte Kanäle
            channels = []
            if reservation_data.notification_channels.email:
                channels.append("email")
            if reservation_data.notification_channels.sms:
                channels.append("sms")
            if reservation_data.notification_channels.whatsapp:
                channels.append("whatsapp")

            # Mindestens ein Kanal muss gewählt sein
            if not channels:
                channels = ["email"]  # Fallback auf E-Mail

            # Erstelle Notification-Objekt
            from app.services.notification_service import UpsellPackageInfo
            from app.settings import RESERVATION_WIDGET_URL

            manage_url = f"{RESERVATION_WIDGET_URL}/{restaurant.slug}/manage/{confirmation_code}"

            # Bereite Upsell-Pakete für Notification vor
            upsell_packages_info = None
            if upsell_packages:
                upsell_packages_info = [
                    UpsellPackageInfo(
                        name=pkg.name,
                        price=pkg.price,
                        description=pkg.description,
                    )
                    for pkg in upsell_packages
                ]

            # Generiere ICS-Datei
            ics_content = None
            try:
                summary = f"Reservierung bei {restaurant.name}"
                description_parts = [
                    f"Reservierung für {reservation_data.party_size} {'Person' if reservation_data.party_size == 1 else 'Personen'}",
                    f"Bestätigungscode: {confirmation_code}",
                ]
                if reservation_data.special_requests:
                    description_parts.append(
                        f"Besondere Wünsche: {reservation_data.special_requests}"
                    )
                if upsell_packages:
                    packages_list = ", ".join([pkg.name for pkg in upsell_packages])
                    description_parts.append(f"Zusatzpakete: {packages_list}")

                description = "\n".join(description_parts)
                location = restaurant.address or restaurant.name

                # Verwende Restaurant-E-Mail falls vorhanden, sonst Fallback
                organizer_email = (
                    restaurant.email or f"noreply@{restaurant.slug or 'gastropilot'}.org"
                )

                ics_content = generate_ics_file(
                    summary=summary,
                    start=start_at,
                    end=end_at,
                    description=description,
                    location=location,
                    organizer_name=restaurant.name,
                    organizer_email=organizer_email,
                    attendee_name=reservation_data.guest_name,
                    attendee_email=reservation_data.guest_email,
                    url=manage_url,
                )
            except Exception as ics_error:
                logger.warning(f"Failed to generate ICS file: {ics_error}")
                # ICS-Fehler sollten die Reservierung nicht abbrechen

            notification = ReservationNotification(
                guest_name=reservation_data.guest_name,
                guest_email=reservation_data.guest_email,
                guest_phone=reservation_data.guest_phone,
                restaurant_name=restaurant.name,
                restaurant_slug=restaurant.slug,
                restaurant_address=restaurant.address,
                restaurant_phone=restaurant.phone,
                date=reservation_data.desired_date.strftime("%d.%m.%Y"),
                time=reservation_data.desired_time,
                party_size=reservation_data.party_size,
                table_number=table.number,
                confirmation_code=confirmation_code,
                special_requests=reservation_data.special_requests,
                manage_url=manage_url,
                upsell_packages=upsell_packages_info,
                ics_content=ics_content,
            )

            # Sende Bestätigungen asynchron
            results = await notification_service.send_reservation_confirmation(
                notification=notification,
                channels=channels,
            )

            # Logge Ergebnisse
            for result in results:
                if result.success:
                    logger.info(f"Notification sent via {result.channel}: {result.message}")
                else:
                    logger.warning(f"Notification failed via {result.channel}: {result.error}")

        except Exception as notify_error:
            # Benachrichtigungsfehler sollten die Reservierung nicht abbrechen
            logger.error(f"Failed to send notifications: {notify_error}")

    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to create reservation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create reservation. Please try again.",
        )

    return PublicReservationResponse(
        success=True,
        confirmation_code=confirmation_code,
        restaurant_name=restaurant.name,
        guest_name=reservation_data.guest_name,
        date=reservation_data.desired_date.isoformat(),
        time=reservation_data.desired_time,
        party_size=reservation_data.party_size,
        table_number=table.number,
        message=f"Ihre Reservierung wurde erfolgreich erstellt. Bestätigungscode: {confirmation_code}",
        prepayment_checkout_url=prepayment_checkout_url,
        prepayment_amount=prepayment_amount,
    )


@router.get("/{restaurant_slug}/reservation/{confirmation_code}")
async def get_reservation_status(
    restaurant_slug: str,
    confirmation_code: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Ruft den Status einer Reservierung ab.

    Gäste können damit ihre Reservierung überprüfen.
    """
    restaurant = await _get_restaurant_by_slug(restaurant_slug, session)

    result = await session.execute(
        select(Reservation).where(
            and_(
                Reservation.restaurant_id == restaurant.id,
                Reservation.confirmation_code == confirmation_code,
            )
        )
    )
    reservation = result.scalar_one_or_none()

    if not reservation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    # Lade Tisch-Info
    table = await session.get(Table, reservation.table_id) if reservation.table_id else None

    # Prüfe ob Reservierung noch bearbeitbar ist (2 Stunden vor Start)
    now = datetime.now(UTC)
    hours_until_reservation = (reservation.start_at - now).total_seconds() / 3600
    can_modify = reservation.status in ["pending", "confirmed"] and hours_until_reservation >= 2

    # Konvertiere UTC-Zeit zurück in lokale Zeit für Anzeige
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    restaurant_tz = ZoneInfo("Europe/Berlin")
    local_start = reservation.start_at.astimezone(restaurant_tz)

    return {
        "confirmation_code": reservation.confirmation_code,
        "status": reservation.status,
        "guest_name": reservation.guest_name,
        "date": local_start.strftime("%d.%m.%Y"),
        "time": local_start.strftime("%H:%M"),
        "party_size": reservation.party_size,
        "table_number": table.number if table else None,
        "special_requests": reservation.special_requests,
        "restaurant_name": restaurant.name,
        "restaurant_address": restaurant.address,
        "restaurant_phone": restaurant.phone,
        "can_modify": can_modify,
        "hours_until_reservation": round(hours_until_reservation, 1),
        "max_party_size": restaurant.booking_max_party_size,
    }


class ReservationUpdateRequest(BaseModel):
    """Schema für Reservierungsänderung."""

    desired_date: date | None = None
    desired_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    party_size: int | None = Field(None, gt=0, le=50)
    special_requests: str | None = Field(None, max_length=1000)


@router.patch("/{restaurant_slug}/reservation/{confirmation_code}")
async def update_reservation(
    restaurant_slug: str,
    confirmation_code: str,
    update_data: ReservationUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Aktualisiert eine Reservierung.

    Nur möglich bis 2 Stunden vor Reservierungsbeginn.
    """
    restaurant = await _get_restaurant_by_slug(restaurant_slug, session)

    result = await session.execute(
        select(Reservation).where(
            and_(
                Reservation.restaurant_id == restaurant.id,
                Reservation.confirmation_code == confirmation_code,
            )
        )
    )
    reservation = result.scalar_one_or_none()

    if not reservation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    # Prüfe Status
    if reservation.status not in ["pending", "confirmed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Reservation cannot be modified"
        )

    # Prüfe 2-Stunden-Regel
    now = datetime.now(UTC)
    hours_until_reservation = (reservation.start_at - now).total_seconds() / 3600
    if hours_until_reservation < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reservations can only be modified up to 2 hours before the reservation time",
        )

    # Zeitzone Setup
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    restaurant_tz = ZoneInfo("Europe/Berlin")

    # Berechne neue Start- und Endzeit falls Datum/Zeit geändert
    new_start_at = reservation.start_at
    if update_data.desired_date or update_data.desired_time:
        # Hole aktuelle lokale Werte
        current_local = reservation.start_at.astimezone(restaurant_tz)

        new_date = update_data.desired_date or current_local.date()
        if update_data.desired_time:
            hour, minute = map(int, update_data.desired_time.split(":"))
            new_time = time(hour, minute)
        else:
            new_time = current_local.time()

        # Erstelle neue lokale Zeit und konvertiere zu UTC
        new_local_dt = datetime.combine(new_date, new_time).replace(tzinfo=restaurant_tz)
        new_start_at = new_local_dt.astimezone(UTC)

        # Prüfe Mindestvorlaufzeit für neuen Termin
        min_booking_time = now + timedelta(hours=restaurant.booking_lead_time_hours)
        if new_start_at < min_booking_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"New reservation time must be at least {restaurant.booking_lead_time_hours} hours in advance",
            )

    new_end_at = new_start_at + timedelta(minutes=restaurant.booking_default_duration)
    new_party_size = update_data.party_size or reservation.party_size

    # Prüfe Personenanzahl
    if new_party_size > restaurant.booking_max_party_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum party size is {restaurant.booking_max_party_size}",
        )

    # Wenn Datum/Zeit/Personenanzahl geändert, prüfe Tischverfügbarkeit
    needs_new_table = (
        new_start_at != reservation.start_at or new_party_size != reservation.party_size
    )

    if needs_new_table:
        # Finde neuen verfügbaren Tisch (exkludiere aktuelle Reservierung)
        table = await _find_available_table_excluding(
            restaurant.id,
            new_start_at,
            new_end_at,
            new_party_size,
            reservation.id,
            session,
        )

        if not table:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No tables available for the new time/party size. Please try a different time.",
            )

        # Update Tisch
        reservation.table_id = table.id

        # Update ReservationTable
        rt_result = await session.execute(
            select(ReservationTable).where(ReservationTable.reservation_id == reservation.id)
        )
        rt = rt_result.scalar_one_or_none()
        if rt:
            rt.table_id = table.id
            rt.start_at = new_start_at
            rt.end_at = new_end_at

    # Update Reservierung
    reservation.start_at = new_start_at
    reservation.end_at = new_end_at
    reservation.party_size = new_party_size
    if update_data.special_requests is not None:
        reservation.special_requests = update_data.special_requests

    await session.commit()
    await session.refresh(reservation)

    # Lade Tisch-Info
    table = await session.get(Table, reservation.table_id) if reservation.table_id else None

    # Konvertiere zurück in lokale Zeit
    local_start = new_start_at.astimezone(restaurant_tz)

    logger.info(f"Reservation {confirmation_code} updated by guest")

    return {
        "success": True,
        "message": "Reservation has been updated successfully",
        "reservation": {
            "confirmation_code": reservation.confirmation_code,
            "date": local_start.strftime("%d.%m.%Y"),
            "time": local_start.strftime("%H:%M"),
            "party_size": reservation.party_size,
            "table_number": table.number if table else None,
            "special_requests": reservation.special_requests,
        },
    }


async def _find_available_table_excluding(
    restaurant_id: int,
    desired_datetime: datetime,
    end_datetime: datetime,
    party_size: int,
    exclude_reservation_id: int,
    session: AsyncSession,
) -> Table | None:
    """Findet einen verfügbaren Tisch, exkludiert eine bestimmte Reservierung."""
    # Hole alle Tische mit passender Kapazität
    tables_result = await session.execute(
        select(Table)
        .where(
            and_(
                Table.restaurant_id == restaurant_id,
                Table.is_active == True,
                Table.capacity >= party_size,
            )
        )
        .order_by(Table.capacity)  # Kleinster passender Tisch zuerst
    )
    tables = tables_result.scalars().all()

    for table in tables:
        # Prüfe auf überlappende Reservierungen (exkludiere aktuelle)
        reservation_result = await session.execute(
            select(Reservation).where(
                and_(
                    Reservation.table_id == table.id,
                    Reservation.id != exclude_reservation_id,
                    Reservation.status.in_(["pending", "confirmed", "seated"]),
                    Reservation.start_at < end_datetime,
                    Reservation.end_at > desired_datetime,
                )
            )
        )
        if reservation_result.scalar_one_or_none():
            continue

        # Prüfe auf Blockierungen
        block_result = await session.execute(
            select(BlockAssignment)
            .join(Block)
            .where(
                and_(
                    BlockAssignment.table_id == table.id,
                    Block.restaurant_id == restaurant_id,
                    Block.start_at < end_datetime,
                    Block.end_at > desired_datetime,
                )
            )
        )
        if block_result.scalar_one_or_none():
            continue

        return table

    return None


@router.post("/{restaurant_slug}/reservation/{confirmation_code}/cancel")
async def cancel_reservation(
    restaurant_slug: str,
    confirmation_code: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Storniert eine Reservierung.

    Gäste können ihre Reservierung selbst stornieren.
    """
    restaurant = await _get_restaurant_by_slug(restaurant_slug, session)

    result = await session.execute(
        select(Reservation).where(
            and_(
                Reservation.restaurant_id == restaurant.id,
                Reservation.confirmation_code == confirmation_code,
            )
        )
    )
    reservation = result.scalar_one_or_none()

    if not reservation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    if reservation.status == "canceled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Reservation is already canceled"
        )

    if reservation.status in ["seated", "completed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel a reservation that has already started",
        )

    reservation.status = "canceled"
    reservation.canceled_at = datetime.now(UTC)
    reservation.canceled_reason = "Canceled by guest"

    try:
        await session.commit()
        await session.refresh(reservation)
    except Exception:
        await session.rollback()
        raise

    logger.info(f"Reservation {confirmation_code} canceled by guest")

    # Sende Stornierungs-Benachrichtigung per E-Mail
    if reservation.guest_email:
        try:
            from app.services.notification_service import (
                ReservationNotification,
                notification_service,
            )
            from app.settings import RESERVATION_WIDGET_URL

            # Formatiere Datum und Zeit
            start_dt = reservation.start_at
            date_str = start_dt.strftime("%d.%m.%Y")
            time_str = start_dt.strftime("%H:%M")

            manage_url = (
                f"{RESERVATION_WIDGET_URL}/{restaurant.slug}/manage/{reservation.confirmation_code}"
                if reservation.confirmation_code and restaurant.slug
                else None
            )

            notification = ReservationNotification(
                guest_name=reservation.guest_name or "Gast",
                guest_email=reservation.guest_email,
                guest_phone=reservation.guest_phone or "",
                restaurant_name=restaurant.name,
                restaurant_slug=restaurant.slug,
                restaurant_address=restaurant.address,
                restaurant_phone=restaurant.phone,
                date=date_str,
                time=time_str,
                party_size=reservation.party_size,
                table_number=None,  # Nicht relevant für Stornierung
                confirmation_code=reservation.confirmation_code or "",
                special_requests=None,
                manage_url=manage_url,
            )

            # Sende Stornierungs-Benachrichtigung
            results = await notification_service.send_reservation_cancellation(
                notification=notification,
                channels=["email"],  # Nur E-Mail für Stornierung
            )

            # Logge Ergebnisse
            for result in results:
                if result.success:
                    logger.info(
                        f"Stornierungs-E-Mail gesendet via {result.channel}: {result.message}"
                    )
                else:
                    logger.warning(
                        f"Stornierungs-E-Mail fehlgeschlagen via {result.channel}: {result.error}"
                    )
        except Exception as notify_error:
            # Benachrichtigungsfehler sollten die Stornierung nicht abbrechen
            logger.error(f"Failed to send cancellation notification: {notify_error}")

    return {
        "success": True,
        "message": "Reservation has been canceled successfully",
    }


@router.get("/{restaurant_slug}/reservation/{confirmation_code}/ics")
async def download_reservation_ics(
    restaurant_slug: str,
    confirmation_code: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Lädt eine ICS-Datei für die Reservierung herunter.

    Gäste können diese Datei in ihren Kalender importieren.
    """
    restaurant = await _get_restaurant_by_slug(restaurant_slug, session)

    result = await session.execute(
        select(Reservation).where(
            and_(
                Reservation.restaurant_id == restaurant.id,
                Reservation.confirmation_code == confirmation_code,
            )
        )
    )
    reservation = result.scalar_one_or_none()

    if not reservation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    # Lade Tisch-Info
    table = await session.get(Table, reservation.table_id) if reservation.table_id else None
    table_number = table.number if table else None

    # Generiere ICS-Datei
    summary = f"Reservierung bei {restaurant.name}"
    if table_number:
        summary += f" - Tisch {table_number}"

    description = f"Reservierung für {reservation.party_size} {'Person' if reservation.party_size == 1 else 'Personen'}"
    if reservation.special_requests:
        description += f"\n\nBesondere Wünsche: {reservation.special_requests}"
    description += f"\n\nBestätigungscode: {confirmation_code}"

    location = restaurant.address or ""
    if restaurant.phone:
        location += f"\nTel: {restaurant.phone}"

    # URL zur Reservierungsverwaltung (falls vorhanden)
    manage_url = None
    # TODO: Konstruiere URL basierend auf RESERVATION_WIDGET_URL oder ähnlichem

    ics_content = generate_ics_file(
        summary=summary,
        start=reservation.start_at,
        end=reservation.end_at,
        description=description,
        location=location,
        organizer_name=restaurant.name,
        organizer_email=None,  # TODO: Restaurant-E-Mail falls vorhanden
        attendee_name=reservation.guest_name,
        attendee_email=reservation.guest_email,
        url=manage_url,
    )

    # Dateiname: reservation-{confirmation_code}.ics
    filename = f"reservation-{confirmation_code}.ics"

    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/calendar; charset=utf-8",
        },
    )
