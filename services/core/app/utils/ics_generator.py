"""ICS (iCalendar) file generation for reservations."""
from __future__ import annotations

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
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)

    def format_datetime(dt: datetime) -> str:
        return dt.strftime("%Y%m%dT%H%M%SZ")

    uid = f"{start_utc.strftime('%Y%m%dT%H%M%SZ')}-{attendee_email or 'guest'}@gastropilot.org"

    def escape_ics_text(text: str) -> str:
        if not text:
            return ""
        text = text.replace("\n", "\\n")
        text = text.replace("\r", "")
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

    if organizer_email:
        organizer_line = "ORGANIZER"
        if organizer_name:
            organizer_line += f";CN={escape_ics_text(organizer_name)}"
        organizer_line += f":mailto:{organizer_email}"
        lines.append(organizer_line)
    elif organizer_name:
        lines.append(
            f"ORGANIZER;CN={escape_ics_text(organizer_name)}:mailto:noreply@gastropilot.org"
        )

    if attendee_email:
        attendee_line = "ATTENDEE"
        if attendee_name:
            attendee_line += f";CN={escape_ics_text(attendee_name)}"
        attendee_line += f":mailto:{attendee_email}"
        attendee_line += ";RSVP=TRUE"
        lines.append(attendee_line)
    elif attendee_name:
        lines.append(
            f"ATTENDEE;CN={escape_ics_text(attendee_name)}:mailto:noreply@gastropilot.org;RSVP=TRUE"
        )

    if url:
        lines.append(f"URL:{url}")

    lines.append("STATUS:CONFIRMED")
    lines.append("TRANSP:OPAQUE")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])

    return "\r\n".join(lines) + "\r\n"
