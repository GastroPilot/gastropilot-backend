"""Geocoding-Service auf Basis der Nominatim-API (OpenStreetMap).

Best-effort: Fehler werden geschluckt und als Warning geloggt, sodass das
Restaurant-Create/Update nicht abbricht, falls Nominatim nicht erreichbar ist.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
GEOCODING_TIMEOUT_SECONDS = 5.0


def _user_agent() -> str:
    """User-Agent-Header (Pflicht bei Nominatim)."""
    return f"gastropilot/{settings.APP_VERSION} (contact@gastropilot.de)"


def build_address_string(
    *,
    street: str | None,
    zip_code: str | None,
    city: str | None,
    country: str | None,
    address_fallback: str | None = None,
) -> str | None:
    """Baut einen Adress-String für Nominatim aus den strukturierten Feldern.

    Fällt auf den freien `address`-String zurück, wenn keine strukturierten
    Felder vorhanden sind. Gibt `None` zurück, wenn kein Adress-Bestandteil
    gesetzt ist.
    """
    zip_city = " ".join(p for p in (zip_code, city) if p)
    parts = [street, zip_city, country]
    structured = ", ".join(p for p in parts if p)
    if structured:
        return structured
    if address_fallback:
        return address_fallback
    return None


async def geocode_address(address: str) -> tuple[float, float] | None:
    """Geocodet einen Adress-String via Nominatim.

    Returns:
        ``(latitude, longitude)`` bei Erfolg, sonst ``None``.

    Schluckt sämtliche Exceptions (Timeout, HTTPError, JSON-/Value-Errors,
    leeres Result) und loggt sie als Warning. Niemals re-raisen.
    """
    if not address or not address.strip():
        return None

    headers = {"User-Agent": _user_agent()}
    params = {"q": address, "format": "json", "limit": 1}

    try:
        async with httpx.AsyncClient(timeout=GEOCODING_TIMEOUT_SECONDS) as client:
            response = await client.get(NOMINATIM_URL, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Geocoding fehlgeschlagen für '%s': %s", address, exc)
        return None
    except Exception as exc:  # noqa: BLE001 — best-effort, niemals re-raisen
        logger.warning("Unerwarteter Geocoding-Fehler für '%s': %s", address, exc)
        return None

    if not isinstance(data, list) or not data:
        logger.warning("Geocoding lieferte kein Ergebnis für '%s'", address)
        return None

    try:
        first = data[0]
        lat = float(first["lat"])
        lon = float(first["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Geocoding-Antwort konnte nicht geparst werden für '%s': %s", address, exc)
        return None

    return lat, lon
