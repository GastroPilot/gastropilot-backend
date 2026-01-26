"""
ICS (iCalendar) Datei-Generierung für Reservierungen.
"""

from datetime import UTC, datetime


def generate_ics_file(
    summary: str,
    start: datetime,
    end: datetime,
    description: str | None = None,
    location: str | None = None,
    organizer_name: str | None = None,
    organizer_email: str | None = None,
    attendee_name: str | None = None,
    attendee_email: str | None = None,
    url: str | None = None,
) -> str:
    """
    Generiert eine ICS-Datei für eine Reservierung.

    Args:
        summary: Titel der Reservierung
        start: Startzeitpunkt (datetime mit timezone)
        end: Endzeitpunkt (datetime mit timezone)
        description: Beschreibung der Reservierung
        location: Ort/Adresse
        organizer_name: Name des Organisators (Restaurant)
        organizer_email: E-Mail des Organisators
        attendee_name: Name des Teilnehmers (Gast)
        attendee_email: E-Mail des Teilnehmers
        url: URL zur Reservierungsverwaltung

    Returns:
        ICS-Datei als String
    """
    # Konvertiere zu UTC für ICS
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)

    # Format: YYYYMMDDTHHMMSSZ
    def format_datetime(dt: datetime) -> str:
        return dt.strftime("%Y%m%dT%H%M%SZ")

    # Generiere UID (eindeutige ID)
    uid = f"{start_utc.strftime('%Y%m%dT%H%M%SZ')}-{attendee_email or 'guest'}@gastropilot.org"

    # Escape ICS-Text (Zeilenumbrüche und spezielle Zeichen)
    def escape_ics_text(text: str) -> str:
        if not text:
            return ""
        # Ersetze Zeilenumbrüche
        text = text.replace("\n", "\\n")
        text = text.replace("\r", "")
        # Escape spezielle Zeichen
        text = text.replace("\\", "\\\\")
        text = text.replace(",", "\\,")
        text = text.replace(";", "\\;")
        return text

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//GastroPilot//Reservation System//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{format_datetime(datetime.now(UTC))}",
        f"DTSTART:{format_datetime(start_utc)}",
        f"DTEND:{format_datetime(end_utc)}",
        f"SUMMARY:{escape_ics_text(summary)}",
    ]

    if description:
        lines.append(f"DESCRIPTION:{escape_ics_text(description)}")

    if location:
        lines.append(f"LOCATION:{escape_ics_text(location)}")

    # ORGANIZER muss immer eine E-Mail haben (RFC 5545)
    if organizer_email:
        organizer_line = "ORGANIZER"
        if organizer_name:
            organizer_line += f";CN={escape_ics_text(organizer_name)}"
        organizer_line += f":mailto:{organizer_email}"
        lines.append(organizer_line)
    elif organizer_name:
        # Fallback: Verwende Platzhalter-E-Mail wenn nur Name vorhanden
        organizer_line = (
            f"ORGANIZER;CN={escape_ics_text(organizer_name)}:mailto:noreply@gastropilot.org"
        )
        lines.append(organizer_line)

    # ATTENDEE (Teilnehmer/Gast)
    if attendee_email:
        attendee_line = "ATTENDEE"
        if attendee_name:
            attendee_line += f";CN={escape_ics_text(attendee_name)}"
        attendee_line += f":mailto:{attendee_email}"
        attendee_line += ";RSVP=TRUE"
        lines.append(attendee_line)
    elif attendee_name:
        # Fallback: Verwende Platzhalter-E-Mail wenn nur Name vorhanden
        attendee_line = (
            f"ATTENDEE;CN={escape_ics_text(attendee_name)}:mailto:noreply@gastropilot.org;RSVP=TRUE"
        )
        lines.append(attendee_line)

    if url:
        lines.append(f"URL:{url}")

    # Status
    lines.append("STATUS:CONFIRMED")

    # Transparenz (OPAQUE = blockiert Zeit, TRANSPARENT = blockiert nicht)
    lines.append("TRANSP:OPAQUE")

    lines.extend(
        [
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )

    return "\r\n".join(lines) + "\r\n"
