"""Guest authentication dependencies."""

from __future__ import annotations

import uuid

from fastapi import Cookie, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session_factories
from .security import verify_token

security = HTTPBearer(auto_error=False)


async def _get_guest_db():
    """DB session without RLS tenant context for guest-scoped queries."""
    session_factory_app, _ = get_session_factories()
    async with session_factory_app() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def _extract_guest_token(
    credentials: HTTPAuthorizationCredentials | None,
    access_token: str | None,
) -> dict | None:
    """Extract and verify a guest JWT token.

    Prefer the Authorization header over the cookie, because the cookie
    might carry a staff token from the dashboard on the same localhost domain.
    """
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
    credentials: HTTPAuthorizationCredentials | None = Depends(
        security
    ),
    access_token: str | None = Cookie(default=None),
    session: AsyncSession = Depends(_get_guest_db),
):
    """Extract guest from JWT, verify role='guest'."""
    from app.models.user import GuestProfile

    payload = _extract_guest_token(credentials, access_token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    guest_id = payload.get("sub")
    if not guest_id:
        raise HTTPException(
            status_code=401, detail="Token missing subject"
        )

    result = await session.execute(
        select(GuestProfile).where(
            GuestProfile.id == uuid.UUID(guest_id)
        )
    )
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(
            status_code=401, detail="Guest not found"
        )

    return guest


async def get_optional_guest(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        security
    ),
    access_token: str | None = Cookie(default=None),
    session: AsyncSession = Depends(_get_guest_db),
):
    """Same as get_current_guest but returns None if no auth."""
    from app.models.user import GuestProfile

    payload = _extract_guest_token(credentials, access_token)
    if not payload:
        return None

    guest_id = payload.get("sub")
    if not guest_id:
        return None

    result = await session.execute(
        select(GuestProfile).where(
            GuestProfile.id == uuid.UUID(guest_id)
        )
    )
    return result.scalar_one_or_none()
