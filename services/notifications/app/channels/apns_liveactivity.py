"""APNs Live Activity Push-Channel.

Sendet Updates an iOS-Live-Activities via Apple Push Notification Service.
Authentifizierung erfolgt Token-based (.p8-Key + Key-ID + Team-ID).

Die hier verwendete Topic-Struktur ist Apple-Pflicht für Live Activities:
    apns-topic: <bundle-id>.push-type.liveactivity
    apns-push-type: liveactivity
    apns-priority: 10

Der Channel ist "lazy": Er kann existieren, ohne dass die APNs-Settings gesetzt
sind. Erst beim tatsächlichen Versand wird ein klarer Fehler geworfen, wenn
Pflicht-Felder fehlen. Das erlaubt Boots in Dev/CI ohne Apple-Credentials.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class APNsConfigurationError(RuntimeError):
    """Wird geworfen, wenn ein Live-Activity-Versand ohne komplette Settings versucht wird."""


class APNsTokenExpiredError(RuntimeError):
    """Apple meldet Status 410 → Push-Token ungültig, Live Activity ist beendet."""


@dataclass
class LiveActivityResult:
    success: bool
    status_code: int | None = None
    description: str | None = None


def _ensure_configured() -> None:
    missing = [
        name
        for name, value in (
            ("APNS_KEY_ID", settings.APNS_KEY_ID),
            ("APNS_TEAM_ID", settings.APNS_TEAM_ID),
            ("APNS_BUNDLE_ID", settings.APNS_BUNDLE_ID),
            ("APNS_AUTH_KEY_PATH", settings.APNS_AUTH_KEY_PATH),
        )
        if not value
    ]
    if missing:
        raise APNsConfigurationError(
            "APNs Live Activity ist nicht vollständig konfiguriert. "
            f"Fehlende Settings: {', '.join(missing)}"
        )


_apns_client: Any | None = None


def _get_client() -> Any:
    """Erzeugt (und cached) einen aioapns-Client mit Token-Auth.

    Wir importieren aioapns lazy, damit Tests den Channel ohne installierte
    Dependency mocken können.
    """
    global _apns_client
    if _apns_client is not None:
        return _apns_client

    _ensure_configured()

    try:
        from aioapns import APNs
    except ImportError as exc:
        raise APNsConfigurationError(
            "aioapns ist nicht installiert – Live Activity Versand nicht möglich."
        ) from exc

    _apns_client = APNs(
        key=settings.APNS_AUTH_KEY_PATH,
        key_id=settings.APNS_KEY_ID,
        team_id=settings.APNS_TEAM_ID,
        topic=f"{settings.APNS_BUNDLE_ID}.push-type.liveactivity",
        use_sandbox=settings.APNS_USE_SANDBOX,
    )
    return _apns_client


def _build_payload(
    *,
    event: str,
    content_state: dict,
    dismiss_at: int | None = None,
) -> dict:
    aps: dict[str, Any] = {
        "timestamp": int(time.time()),
        "event": event,
        "content-state": content_state,
    }
    if dismiss_at is not None and event == "end":
        aps["dismissal-date"] = dismiss_at
    return {"aps": aps}


async def _send(
    *,
    activity_push_token: str,
    payload: dict,
    priority: int = 10,
) -> LiveActivityResult:
    """Interner Sendepfad – verzweigt aioapns + Fehlerbehandlung."""
    if not activity_push_token:
        raise ValueError("activity_push_token darf nicht leer sein")

    client = _get_client()

    try:
        from aioapns import NotificationRequest
    except ImportError as exc:  # pragma: no cover - defensive
        raise APNsConfigurationError("aioapns nicht installiert") from exc

    request = NotificationRequest(
        device_token=activity_push_token,
        message=payload,
        priority=priority,
        push_type="liveactivity",
        topic=f"{settings.APNS_BUNDLE_ID}.push-type.liveactivity",
    )

    response = await client.send_notification(request)

    status = getattr(response, "status", None)
    description = getattr(response, "description", None)

    if status == "200" or status == 200:
        return LiveActivityResult(success=True, status_code=200, description=description)

    # 410 → Token expired / unregistered
    if status in ("410", 410):
        raise APNsTokenExpiredError(
            f"APNs Token expired für {activity_push_token[:10]}…: {description}"
        )

    return LiveActivityResult(
        success=False,
        status_code=int(status) if status is not None else None,
        description=description,
    )


async def send_live_activity_update(
    activity_push_token: str,
    content_state: dict,
    dismiss_at: int | None = None,
) -> LiveActivityResult:
    """Sendet ein ``event: update`` an eine laufende Live Activity.

    Wenn ``dismiss_at`` gesetzt ist, schickt iOS die Activity ab dem Zeitpunkt
    nicht mehr aktiv aus – nützlich, um sie kurz nach Endstatus auslaufen
    zu lassen, ohne sie sofort zu beenden.
    """
    payload = _build_payload(
        event="update",
        content_state=content_state,
        dismiss_at=dismiss_at,
    )
    logger.debug("Sende Live Activity Update an %s…", activity_push_token[:10])
    return await _send(activity_push_token=activity_push_token, payload=payload)


async def send_live_activity_end(
    activity_push_token: str,
    content_state: dict,
    dismiss_at: int | None = None,
) -> LiveActivityResult:
    """Beendet eine Live Activity (``event: end``)."""
    payload = _build_payload(
        event="end",
        content_state=content_state,
        dismiss_at=dismiss_at,
    )
    logger.debug("Beende Live Activity für %s…", activity_push_token[:10])
    return await _send(activity_push_token=activity_push_token, payload=payload)


def reset_client_for_tests() -> None:
    """Test-Hook – setzt den gecachten Client zurück."""
    global _apns_client
    _apns_client = None
