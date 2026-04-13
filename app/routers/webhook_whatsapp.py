"""
WhatsApp Webhook Handler für Twilio.

Empfängt eingehende WhatsApp-Nachrichten und verarbeitet sie mit dem Bot.

Features:
- Reservierung erstellen
- Reservierung stornieren
- Reservierung ändern
- Alternative Zeiten vorschlagen wenn belegt
"""

import logging
from datetime import UTC, date, datetime
from datetime import time as dt_time
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Reservation, ReservationTable, Restaurant, Table
from app.dependencies import get_session
from app.routers.public_reservations import _find_available_table, _generate_confirmation_code
from app.services.notification_service import notification_service
from app.services.whatsapp_bot import WEEKDAY_NAMES_DE, check_opening_hours, whatsapp_bot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])


def _validate_twilio_signature(request: Request, body: bytes) -> bool:
    """
    Validiert die Twilio Webhook-Signatur.

    Für Production sollte dies aktiviert sein um Spoofing zu verhindern.
    """
    from app.settings import TWILIO_AUTH_TOKEN

    if not TWILIO_AUTH_TOKEN:
        logger.warning("Twilio auth token not configured, skipping signature validation")
        return True

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        return False

    # TODO: Vollständige Signatur-Validierung implementieren
    # Siehe: https://www.twilio.com/docs/usage/webhooks/webhooks-security
    return True


async def _find_alternative_times(
    restaurant: Restaurant,
    desired_date: date,
    desired_time: str,
    party_size: int,
    session: AsyncSession,
    max_alternatives: int = 3,
) -> list[str]:
    """
    Findet alternative verfügbare Zeiten nahe der gewünschten Zeit.

    Returns:
        Liste von verfügbaren Zeiten als Strings (z.B. ["18:30", "19:30", "20:00"])
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    restaurant_tz = ZoneInfo("Europe/Berlin")

    # Parse gewünschte Zeit
    try:
        desired_hour, desired_minute = map(int, desired_time.split(":"))
    except (ValueError, AttributeError):
        desired_hour, desired_minute = 19, 0

    desired_minutes = desired_hour * 60 + desired_minute

    # Hole Öffnungszeiten für diesen Tag
    start_hour = 11
    end_hour = 22

    if restaurant.opening_hours:
        from app.services.whatsapp_bot import WEEKDAY_NAMES

        weekday_name = WEEKDAY_NAMES.get(desired_date.weekday(), "monday")
        day_hours = restaurant.opening_hours.get(weekday_name)
        if day_hours:
            try:
                open_h, open_m = map(int, day_hours.get("open", "11:00").split(":"))
                close_h, close_m = map(int, day_hours.get("close", "22:00").split(":"))
                start_hour = open_h
                end_hour = close_h
            except (ValueError, AttributeError):
                pass

    # Generiere alle möglichen Zeitslots (30-Min Intervalle)
    duration_minutes = restaurant.booking_default_duration
    now = datetime.now(UTC)
    min_booking_time = now + timedelta(hours=restaurant.booking_lead_time_hours)

    available_times = []

    # Suche in beide Richtungen von der gewünschten Zeit
    for offset in range(0, 360, 30):  # Bis zu 6 Stunden Abweichung
        for direction in [-1, 1]:
            if offset == 0 and direction == 1:
                continue  # Überspringe 0 doppelt

            check_minutes = desired_minutes + (offset * direction)
            check_hour = check_minutes // 60
            check_minute = check_minutes % 60

            # Prüfe Grenzen
            if check_hour < start_hour or check_hour >= end_hour:
                continue
            if check_hour < 0 or check_hour >= 24:
                continue

            time_str = f"{check_hour:02d}:{check_minute:02d}"

            # Skip wenn es die gewünschte Zeit ist (die ist ja belegt)
            if time_str == desired_time:
                continue

            # Prüfe ob bereits in Liste
            if time_str in available_times:
                continue

            # Erstelle datetime für Verfügbarkeitsprüfung
            slot_time = dt_time(check_hour, check_minute)
            local_dt = datetime.combine(desired_date, slot_time).replace(tzinfo=restaurant_tz)
            slot_datetime = local_dt.astimezone(UTC)
            end_datetime = slot_datetime + timedelta(minutes=duration_minutes)

            # Prüfe Mindestvorlaufzeit
            if slot_datetime < min_booking_time:
                continue

            # Prüfe Öffnungszeiten
            if restaurant.opening_hours:
                is_open, _, _, _ = check_opening_hours(
                    restaurant.opening_hours, desired_date, time_str
                )
                if not is_open:
                    continue

            # Prüfe Verfügbarkeit
            table = await _find_available_table(
                restaurant.id,
                slot_datetime,
                end_datetime,
                party_size,
                session,
            )

            if table:
                available_times.append(time_str)

                if len(available_times) >= max_alternatives:
                    # Sortiere nach Nähe zur gewünschten Zeit
                    available_times.sort(
                        key=lambda t: abs(
                            int(t.split(":")[0]) * 60 + int(t.split(":")[1]) - desired_minutes
                        )
                    )
                    return available_times[:max_alternatives]

    # Sortiere nach Nähe zur gewünschten Zeit
    available_times.sort(
        key=lambda t: abs(int(t.split(":")[0]) * 60 + int(t.split(":")[1]) - desired_minutes)
    )

    return available_times[:max_alternatives]


@router.post("/whatsapp/{restaurant_slug}")
async def handle_whatsapp_webhook(
    restaurant_slug: str,
    request: Request,
    From: str = Form(...),
    Body: str = Form(...),
    To: str | None = Form(None),
    MessageSid: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    """
    Webhook für eingehende WhatsApp-Nachrichten.

    Twilio sendet POST-Requests mit:
    - From: Absender-Telefonnummer (whatsapp:+49...)
    - Body: Nachrichtentext
    - To: Empfänger (Restaurant-Nummer)
    - MessageSid: Eindeutige Nachrichten-ID
    """
    logger.info(f"WhatsApp webhook: {From} -> {Body[:50]}...")

    # Lade Restaurant
    result = await session.execute(select(Restaurant).where(Restaurant.slug == restaurant_slug))
    restaurant = result.scalar_one_or_none()

    if not restaurant:
        logger.warning(f"Restaurant not found: {restaurant_slug}")
        return Response(content="", media_type="text/xml")

    if not restaurant.public_booking_enabled:
        response = (
            f"Leider sind Online-Reservierungen für {restaurant.name} "
            f"derzeit nicht verfügbar.\n\n"
            f"Bitte rufen Sie uns an: {restaurant.phone or 'Telefonnummer auf Anfrage'}"
        )
        await notification_service.send_whatsapp_message(From, response)
        return Response(content="", media_type="text/xml")

    # Extrahiere Telefonnummer
    phone = From.replace("whatsapp:", "")

    # Verarbeite Nachricht mit Bot (mit Öffnungszeiten)
    bot_response = await whatsapp_bot.process_message(
        phone_number=phone,
        restaurant_id=restaurant.id,
        restaurant_name=restaurant.name,
        message=Body,
        opening_hours=restaurant.opening_hours,
    )

    # Log Response
    log_response = bot_response[:50] + "..." if len(bot_response) > 50 else bot_response
    logger.info(f"WhatsApp webhook: bot_response = {log_response}")

    # Verarbeite spezielle Bot-Signale
    if bot_response == "RESERVATION_CONFIRMED":
        await _handle_reservation_confirmed(restaurant, phone, From, session)

    elif bot_response.startswith("CANCELLATION_REQUEST:"):
        code = bot_response.split(":")[1]
        response = await _handle_cancellation(restaurant, code, session)
        await notification_service.send_whatsapp_message(From, response)
        whatsapp_bot.clear_conversation(phone, restaurant.id)

    elif bot_response.startswith("MODIFICATION_REQUEST:"):
        # Format: MODIFICATION_REQUEST:CODE:FIELD:VALUE
        parts = bot_response.split(":")
        if len(parts) >= 4:
            code = parts[1]
            field = parts[2]
            value = ":".join(parts[3:])  # Falls Value selbst : enthält
            response = await _handle_modification(restaurant, code, field, value, phone, session)
            await notification_service.send_whatsapp_message(From, response)
            if "erfolgreich" in response.lower():
                whatsapp_bot.clear_conversation(phone, restaurant.id)

    elif bot_response == "CHECK_AVAILABILITY":
        # Bot will Verfügbarkeit prüfen bevor Bestätigung
        await _handle_availability_check(restaurant, phone, From, session)

    else:
        # Normale Bot-Antwort senden
        await notification_service.send_whatsapp_message(From, bot_response)

    return Response(content="", media_type="text/xml")


async def _handle_reservation_confirmed(
    restaurant: Restaurant,
    phone: str,
    twilio_from: str,
    session: AsyncSession,
):
    """Behandelt eine bestätigte Reservierung."""
    logger.info(f"WhatsApp: Creating reservation for {phone}")
    conv = whatsapp_bot.get_or_create_conversation(phone, restaurant.id)

    try:
        # Prüfe zuerst Verfügbarkeit
        response = await _create_whatsapp_reservation(
            restaurant=restaurant,
            conv=conv,
            phone=phone,
            session=session,
        )

        # Wenn Tisch nicht verfügbar, biete Alternativen an
        if response.startswith("NO_TABLE_AVAILABLE"):
            alternatives = await _find_alternative_times(
                restaurant=restaurant,
                desired_date=conv.desired_date,
                desired_time=conv.desired_time,
                party_size=conv.party_size,
                session=session,
            )

            if alternatives:
                # Speichere Alternativen in Konversation
                conv.suggested_alternatives = alternatives
                conv.state = "SUGGEST_ALTERNATIVES"
                whatsapp_bot.update_conversation(conv)

                alt_list = "\n".join([f"• *{t} Uhr*" for t in alternatives])
                response = (
                    f"Leider ist um {conv.desired_time} Uhr kein Tisch mehr frei. 😔\n\n"
                    f"Folgende Zeiten sind noch verfügbar:\n\n"
                    f"{alt_list}\n\n"
                    f"Welche Uhrzeit passt Ihnen?"
                )
            else:
                response = (
                    f"Leider ist am {conv.desired_date.strftime('%d.%m.%Y')} kein Tisch mehr frei. 😔\n\n"
                    f"Möchten Sie einen anderen Tag versuchen?"
                )
                # Reset zum Datum sammeln
                conv.desired_time = None
                conv.state = "COLLECT_DATE"
                whatsapp_bot.update_conversation(conv)

        await notification_service.send_whatsapp_message(twilio_from, response)

        # Nur bei erfolgreicher Reservierung löschen
        if "bestätigt" in response.lower():
            whatsapp_bot.clear_conversation(phone, restaurant.id)

    except Exception as e:
        logger.error(f"Failed to create WhatsApp reservation: {e}")
        response = (
            f"Es ist leider ein Fehler aufgetreten. 😔\n\n"
            f"Bitte versuchen Sie es erneut oder rufen Sie uns an:\n"
            f"📞 {restaurant.phone or 'Telefonnummer auf Anfrage'}"
        )
        await notification_service.send_whatsapp_message(twilio_from, response)


async def _handle_availability_check(
    restaurant: Restaurant,
    phone: str,
    twilio_from: str,
    session: AsyncSession,
):
    """Prüft Verfügbarkeit und schlägt ggf. Alternativen vor."""
    conv = whatsapp_bot.get_or_create_conversation(phone, restaurant.id)

    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    restaurant_tz = ZoneInfo("Europe/Berlin")

    hour, minute = map(int, conv.desired_time.split(":"))
    start_time = dt_time(hour, minute)
    local_dt = datetime.combine(conv.desired_date, start_time).replace(tzinfo=restaurant_tz)
    start_at = local_dt.astimezone(UTC)
    end_at = start_at + timedelta(minutes=restaurant.booking_default_duration)

    # Prüfe Verfügbarkeit
    table = await _find_available_table(
        restaurant.id,
        start_at,
        end_at,
        conv.party_size,
        session,
    )

    if table:
        # Verfügbar - weiter zur Bestätigung
        conv.state = "CONFIRM"
        whatsapp_bot.update_conversation(conv)

        weekday_name = WEEKDAY_NAMES_DE.get(conv.desired_date.weekday(), "")
        response = (
            f"Super, {conv.desired_time} Uhr ist verfügbar! ✓\n\n"
            f"Hier Ihre Reservierung im Überblick:\n\n"
            f"🍽️ *{restaurant.name}*\n"
            f"📅 {weekday_name}, {conv.desired_date.strftime('%d.%m.%Y')}\n"
            f"⏰ {conv.desired_time} Uhr\n"
            f"👥 {conv.party_size} Personen\n"
            f"👤 {conv.guest_name}\n\n"
            f"Stimmt das so? Antworten Sie mit *Ja* zum Bestätigen."
        )
    else:
        # Nicht verfügbar - finde Alternativen
        alternatives = await _find_alternative_times(
            restaurant=restaurant,
            desired_date=conv.desired_date,
            desired_time=conv.desired_time,
            party_size=conv.party_size,
            session=session,
        )

        if alternatives:
            conv.suggested_alternatives = alternatives
            conv.state = "SUGGEST_ALTERNATIVES"
            whatsapp_bot.update_conversation(conv)

            alt_list = "\n".join([f"• *{t} Uhr*" for t in alternatives])
            response = (
                f"Leider ist um {conv.desired_time} Uhr kein Tisch für {conv.party_size} Personen frei. 😔\n\n"
                f"Folgende Zeiten sind noch verfügbar:\n\n"
                f"{alt_list}\n\n"
                f"Welche Uhrzeit passt Ihnen?"
            )
        else:
            conv.state = "COLLECT_DATE"
            conv.desired_time = None
            whatsapp_bot.update_conversation(conv)

            response = (
                f"Leider ist am {conv.desired_date.strftime('%d.%m.%Y')} kein Tisch mehr frei. 😔\n\n"
                f"Möchten Sie einen anderen Tag versuchen?"
            )

    await notification_service.send_whatsapp_message(twilio_from, response)


async def _create_whatsapp_reservation(
    restaurant: Restaurant,
    conv,
    phone: str,
    session: AsyncSession,
) -> str:
    """Erstellt eine Reservierung aus WhatsApp-Konversation."""

    # Parse Zeit
    hour, minute = map(int, conv.desired_time.split(":"))
    start_time = dt_time(hour, minute)

    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    restaurant_tz = ZoneInfo("Europe/Berlin")

    # Erstelle lokale Zeit und konvertiere zu UTC
    local_dt = datetime.combine(
        conv.desired_date,
        start_time,
    ).replace(tzinfo=restaurant_tz)

    start_at = local_dt.astimezone(UTC)
    end_at = start_at + timedelta(minutes=restaurant.booking_default_duration)

    # Prüfe Mindestvorlaufzeit
    now = datetime.now(UTC)
    min_booking_time = now + timedelta(hours=restaurant.booking_lead_time_hours)
    if start_at < min_booking_time:
        return (
            f"Leider ist eine Reservierung für diesen Zeitpunkt nicht mehr möglich. 😔\n\n"
            f"Reservierungen müssen mindestens {restaurant.booking_lead_time_hours} Stunden "
            f"im Voraus erfolgen.\n\n"
            f"Möchten Sie einen anderen Termin wählen?"
        )

    # Finde verfügbaren Tisch
    table = await _find_available_table(
        restaurant.id,
        start_at,
        end_at,
        conv.party_size,
        session,
    )

    if not table:
        return "NO_TABLE_AVAILABLE"

    # Generiere Bestätigungscode
    confirmation_code = _generate_confirmation_code()

    # Erstelle Reservierung
    reservation = Reservation(
        restaurant_id=restaurant.id,
        table_id=table.id,
        start_at=start_at,
        end_at=end_at,
        party_size=conv.party_size,
        status="confirmed",
        channel="whatsapp",
        guest_name=conv.guest_name,
        guest_phone=phone,
        confirmation_code=confirmation_code,
        special_requests=conv.special_requests,
    )

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

    await session.commit()

    logger.info(f"WhatsApp reservation created: {confirmation_code} for {conv.guest_name}")

    # Tischname formatieren
    table_display = (
        table.number if str(table.number).lower().startswith("tisch") else f"Tisch {table.number}"
    )

    # Wochentag
    weekday_name = WEEKDAY_NAMES_DE.get(conv.desired_date.weekday(), "")

    # Sonderwünsche
    special_line = ""
    if conv.special_requests:
        special_line = f"📝 {conv.special_requests}\n"

    return (
        f"✅ *Reservierung bestätigt!*\n\n"
        f"🍽️ *{restaurant.name}*\n"
        f"📅 {weekday_name}, {conv.desired_date.strftime('%d.%m.%Y')}\n"
        f"⏰ {conv.desired_time} Uhr\n"
        f"👥 {conv.party_size} {'Person' if conv.party_size == 1 else 'Personen'}\n"
        f"👤 {conv.guest_name}\n"
        f"🪑 {table_display}\n"
        f"{special_line}\n"
        f"🔑 *Bestätigungscode: {confirmation_code}*\n"
        f"(Bitte für Änderungen/Stornierung aufbewahren)\n\n"
        f"Wir freuen uns auf Ihren Besuch! 🎉\n\n"
        f"📍 {restaurant.address or 'Adresse auf Anfrage'}\n"
        f"📞 {restaurant.phone or ''}"
    )


async def _handle_cancellation(
    restaurant: Restaurant,
    confirmation_code: str,
    session: AsyncSession,
) -> str:
    """Verarbeitet eine Stornierungsanfrage via WhatsApp."""
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
        return (
            f"❌ Reservierung nicht gefunden.\n\n"
            f"Bitte überprüfen Sie den Bestätigungscode: *{confirmation_code}*\n\n"
            f"Bei Fragen rufen Sie uns gerne an:\n"
            f"📞 {restaurant.phone or 'Telefonnummer auf Anfrage'}"
        )

    if reservation.status == "canceled":
        return f"Diese Reservierung wurde bereits storniert.\n\nCode: {confirmation_code}"

    if reservation.status in ("seated", "completed"):
        return (
            f"Diese Reservierung kann nicht mehr storniert werden, "
            f"da sie bereits begonnen hat oder abgeschlossen ist.\n\n"
            f"Bei Fragen rufen Sie uns bitte an:\n"
            f"📞 {restaurant.phone or ''}"
        )

    # Lokale Zeit für Anzeige
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    restaurant_tz = ZoneInfo("Europe/Berlin")
    local_time = reservation.start_at.astimezone(restaurant_tz)
    weekday_name = WEEKDAY_NAMES_DE.get(local_time.weekday(), "")

    # Storniere Reservierung
    reservation.status = "canceled"
    reservation.canceled_at = datetime.now(UTC)
    reservation.canceled_reason = "Storniert via WhatsApp"

    await session.commit()

    logger.info(f"Reservation {confirmation_code} canceled via WhatsApp")

    return (
        f"✅ Ihre Reservierung wurde erfolgreich storniert.\n\n"
        f"📅 {weekday_name}, {local_time.strftime('%d.%m.%Y')}\n"
        f"⏰ {local_time.strftime('%H:%M')} Uhr\n"
        f"👤 {reservation.guest_name}\n\n"
        f"Wir hoffen, Sie bald wieder bei uns begrüßen zu dürfen! 👋"
    )


async def _handle_modification(
    restaurant: Restaurant,
    confirmation_code: str,
    field: str,
    new_value: str,
    phone: str,
    session: AsyncSession,
) -> str:
    """Verarbeitet eine Änderungsanfrage via WhatsApp."""
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
        return (
            f"❌ Reservierung nicht gefunden.\n\n"
            f"Bitte überprüfen Sie den Bestätigungscode: *{confirmation_code}*"
        )

    if reservation.status in ("canceled", "seated", "completed"):
        return (
            f"Diese Reservierung kann nicht mehr geändert werden.\n\n"
            f"Status: {reservation.status}\n\n"
            f"Bei Fragen rufen Sie uns bitte an."
        )

    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    restaurant_tz = ZoneInfo("Europe/Berlin")

    # Änderung durchführen
    if field == "date":
        new_date = date.fromisoformat(new_value)

        # Behalte Uhrzeit bei
        old_local = reservation.start_at.astimezone(restaurant_tz)
        new_local = datetime.combine(new_date, old_local.time()).replace(tzinfo=restaurant_tz)
        new_start = new_local.astimezone(UTC)
        new_end = new_start + timedelta(minutes=restaurant.booking_default_duration)

        # Prüfe Verfügbarkeit
        table = await _find_available_table(
            restaurant.id,
            new_start,
            new_end,
            reservation.party_size,
            session,
            exclude_reservation_id=reservation.id,
        )

        if not table:
            return (
                f"Leider ist am {new_date.strftime('%d.%m.%Y')} kein Tisch frei. 😔\n\n"
                f"Möchten Sie einen anderen Tag versuchen?"
            )

        reservation.start_at = new_start
        reservation.end_at = new_end
        if table.id != reservation.table_id:
            reservation.table_id = table.id

        weekday_name = WEEKDAY_NAMES_DE.get(new_date.weekday(), "")
        change_info = f"📅 Neues Datum: {weekday_name}, {new_date.strftime('%d.%m.%Y')}"

    elif field == "time":
        # Behalte Datum bei
        old_local = reservation.start_at.astimezone(restaurant_tz)
        hour, minute = map(int, new_value.split(":"))
        new_time = dt_time(hour, minute)
        new_local = datetime.combine(old_local.date(), new_time).replace(tzinfo=restaurant_tz)
        new_start = new_local.astimezone(UTC)
        new_end = new_start + timedelta(minutes=restaurant.booking_default_duration)

        # Prüfe Verfügbarkeit
        table = await _find_available_table(
            restaurant.id,
            new_start,
            new_end,
            reservation.party_size,
            session,
            exclude_reservation_id=reservation.id,
        )

        if not table:
            return (
                f"Leider ist um {new_value} Uhr kein Tisch frei. 😔\n\n"
                f"Möchten Sie eine andere Uhrzeit versuchen?"
            )

        reservation.start_at = new_start
        reservation.end_at = new_end
        if table.id != reservation.table_id:
            reservation.table_id = table.id

        change_info = f"⏰ Neue Uhrzeit: {new_value} Uhr"

    elif field == "party_size":
        new_size = int(new_value)

        # Prüfe ob aktueller Tisch groß genug
        table_result = await session.execute(select(Table).where(Table.id == reservation.table_id))
        current_table = table_result.scalar_one_or_none()

        if current_table and current_table.capacity >= new_size:
            reservation.party_size = new_size
        else:
            # Finde neuen Tisch
            table = await _find_available_table(
                restaurant.id,
                reservation.start_at,
                reservation.end_at,
                new_size,
                session,
                exclude_reservation_id=reservation.id,
            )

            if not table:
                return (
                    f"Leider haben wir keinen Tisch für {new_size} Personen zu diesem Zeitpunkt frei. 😔\n\n"
                    f"Möchten Sie eine andere Zeit oder ein anderes Datum versuchen?"
                )

            reservation.party_size = new_size
            reservation.table_id = table.id

        change_info = f"👥 Neue Personenanzahl: {new_size}"

    else:
        return f"Unbekanntes Feld: {field}"

    reservation.updated_at_utc = datetime.now(UTC)
    await session.commit()

    logger.info(f"Reservation {confirmation_code} modified via WhatsApp: {field}={new_value}")

    # Zeige aktualisierte Reservierung
    local_time = reservation.start_at.astimezone(restaurant_tz)
    weekday_name = WEEKDAY_NAMES_DE.get(local_time.weekday(), "")

    return (
        f"✅ Ihre Reservierung wurde erfolgreich geändert!\n\n"
        f"{change_info}\n\n"
        f"Aktualisierte Reservierung:\n\n"
        f"🍽️ *{restaurant.name}*\n"
        f"📅 {weekday_name}, {local_time.strftime('%d.%m.%Y')}\n"
        f"⏰ {local_time.strftime('%H:%M')} Uhr\n"
        f"👥 {reservation.party_size} Personen\n"
        f"👤 {reservation.guest_name}\n\n"
        f"🔑 Bestätigungscode: *{confirmation_code}*"
    )


@router.get("/whatsapp/{restaurant_slug}")
async def verify_whatsapp_webhook(
    restaurant_slug: str,
    request: Request,
):
    """
    Webhook-Verifizierung für Twilio.

    Twilio kann einen GET-Request senden um den Webhook zu verifizieren.
    """
    return {"status": "ok", "restaurant": restaurant_slug}
