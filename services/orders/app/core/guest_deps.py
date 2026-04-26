"""Guest authentication helpers for orders service.

Spiegelt absichtlich ``services/core/app/core/guest_deps.py`` – wir teilen
keinen Code zwischen Services, daher ist hier eine schlanke Variante, die
nur den JWT prüft. Die DB-Auflösung des Guest-Profile-Datensatzes erfolgt
nicht; wir reichen lediglich die ID weiter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from shared.auth import verify_token
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session_factories

security = HTTPBearer(auto_error=False)


async def get_guest_db() -> AsyncSession:  # type: ignore[misc]
    """DB-Session für Guest-Queries.

    Guest-JWTs tragen keine ``tenant_id``. Da Guests legitim Daten über
    Tenant-Grenzen hinweg lesen können (z.B. eigene Orders bei mehreren
    Restaurants), nutzen wir die Admin-Engine, die RLS umgeht. Tenant-
    Isolation muss in den Endpoints selbst erzwungen werden, indem
    explizit nach Guest-Eigentum gefiltert wird.
    """
    _, session_factory_admin = get_session_factories()
    async with session_factory_admin() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@dataclass
class GuestIdentity:
    """Lightweight Guest-Identity ohne DB-Lookup."""

    id: uuid.UUID
    raw_payload: dict


def _extract_guest_payload(
    credentials: HTTPAuthorizationCredentials | None,
    access_token: str | None,
) -> dict | None:
    header_token = credentials.credentials if credentials else None
    token = header_token or access_token
    if not token:
        return None

    payload = verify_token(token)
    if not payload:
        return None

    if payload.get("role") != "guest":
        return None

    return payload


async def get_current_guest(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    access_token: str | None = Cookie(default=None),
) -> GuestIdentity:
    """Validiert den Guest-JWT und gibt eine ``GuestIdentity`` zurück."""
    payload = _extract_guest_payload(credentials, access_token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    guest_id_str = payload.get("sub")
    if not guest_id_str:
        raise HTTPException(status_code=401, detail="Token missing subject")

    try:
        guest_id = uuid.UUID(guest_id_str)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid guest id in token") from None

    # Optionaler Hinweis fürs Logging – zur Tenant-Auswertung nutzen wir die DB.
    request.state.guest_id = guest_id  # type: ignore[attr-defined]
    return GuestIdentity(id=guest_id, raw_payload=payload)
