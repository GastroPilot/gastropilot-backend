from datetime import UTC, datetime

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.auth import verify_token
from app.database.instance import async_session
from app.database.models import User
from app.services.license_service import license_service
from app.utils.cookies import get_token_from_cookie_or_header

security = HTTPBearer(auto_error=False)  # Don't auto-error to allow cookie fallback


async def get_session():
    """
    FastAPI-Dependency: liefert eine AsyncSession für Request-Handler.

    - Keine impliziten Commits. Für Mutationen explizit `async with session.begin():` nutzen.
    - Rollback auf Fehler, damit nachfolgende Handler sauber weiterarbeiten.
    """
    async with async_session() as session:
        try:
            yield session
        except Exception:
            try:
                await session.rollback()
            except Exception:
                pass
            raise


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    access_token: str | None = Cookie(default=None),
) -> User:
    """
    Holt den aktuellen User aus dem JWT-Token.

    Supports both:
    - HttpOnly cookies (when USE_HTTPONLY_COOKIES=true)
    - Authorization header (Bearer token)

    Cookies take precedence when USE_HTTPONLY_COOKIES is enabled.
    """
    # Get token from cookie or header
    header_token = credentials.credentials if credentials else None
    token = get_token_from_cookie_or_header(access_token, header_token)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user_id",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == int(user_id)))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
            )

        return user


async def require_servecta_role(
    current_user: User = Depends(get_current_user),
) -> User:
    """Stellt sicher, dass der User die Rolle 'servecta' hat."""
    if current_user.role != "servecta":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions: servecta role required",
        )
    return current_user


async def require_restaurantinhaber_role(
    current_user: User = Depends(get_current_user),
) -> User:
    """Stellt sicher, dass der User die Rolle 'restaurantinhaber' oder 'servecta' hat."""
    if current_user.role not in ["restaurantinhaber", "servecta"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions: restaurantinhaber or servecta role required",
        )
    return current_user


async def require_schichtleiter_role(
    current_user: User = Depends(get_current_user),
) -> User:
    """Stellt sicher, dass der User die Rolle 'schichtleiter', 'restaurantinhaber' oder 'servecta' hat."""
    if current_user.role not in ["schichtleiter", "restaurantinhaber", "servecta"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions: schichtleiter, restaurantinhaber or servecta role required",
        )
    return current_user


async def require_mitarbeiter_role(
    current_user: User = Depends(get_current_user),
) -> User:
    """Stellt sicher, dass der User die Rolle 'mitarbeiter' oder höher hat."""
    if current_user.role not in ["mitarbeiter", "schichtleiter", "restaurantinhaber", "servecta"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions: mitarbeiter role or higher required",
        )
    return current_user


async def require_reservations_module(
    current_user: User = Depends(get_current_user),
) -> User:
    """Stellt sicher, dass das Reservierungsmodul aktiviert ist."""
    await license_service.ensure_initialized()
    if not license_service.is_feature_enabled("reservations_module"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Reservations module is not licensed"
        )
    return current_user


async def require_orders_module(
    current_user: User = Depends(get_current_user),
) -> User:
    """Stellt sicher, dass das Bestellmodul aktiviert ist."""
    await license_service.ensure_initialized()
    if not license_service.is_feature_enabled("orders_module"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Orders module is not licensed"
        )
    return current_user


# Kombinierte Dependencies für häufig verwendete Kombinationen
async def require_reservations_module_with_role(
    current_user: User = Depends(require_reservations_module),
) -> User:
    """Stellt sicher, dass das Reservierungsmodul aktiviert ist und der User authentifiziert ist."""
    return current_user


async def require_orders_module_with_role(
    current_user: User = Depends(require_orders_module),
) -> User:
    """Stellt sicher, dass das Bestellmodul aktiviert ist und der User authentifiziert ist."""
    return current_user


def normalize_datetime_to_utc(dt: datetime) -> datetime:
    """Konvertiert ein datetime-Objekt zu UTC (wenn es noch nicht in UTC ist)."""
    if dt.tzinfo is None:
        # Naive datetime: assume it's local time and convert to UTC
        return dt.replace(tzinfo=UTC)
    # Aware datetime: convert to UTC
    return dt.astimezone(UTC)


# License/Module Dependencies


async def require_reservations_module():
    """
    Dependency: Prüft, ob das Reservierungsmodul aktiviert ist.
    Wirft HTTPException 403 wenn nicht aktiviert.
    """
    await license_service.ensure_initialized()
    if not license_service.is_feature_enabled("reservations_module"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reservations module is not enabled for this license",
        )


async def require_orders_module():
    """
    Dependency: Prüft, ob das Bestellmodul aktiviert ist.
    Wirft HTTPException 403 wenn nicht aktiviert.
    """
    await license_service.ensure_initialized()
    if not license_service.is_feature_enabled("orders_module"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Orders module is not enabled for this license",
        )
