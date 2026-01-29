from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
    verify_token,
)
from app.database.models import RefreshToken, User
from app.dependencies import (
    get_current_user,
    get_session,
    require_restaurantinhaber_role,
)
from app.schemas import (
    LoginRequest,
    NFCLoginRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.settings import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    USE_HTTPONLY_COOKIES,
)
from app.utils.cookies import clear_auth_cookies, set_auth_cookies

router = APIRouter(prefix="/auth", tags=["auth"])

# Reservierte Bedienernummern für Servecta
SERVECTA_OPERATOR_NUMBERS = ["0000", "0001"]


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: LoginRequest, response: Response, session: AsyncSession = Depends(get_session)
):
    """Login mit Bedienernummer und PIN.

    When USE_HTTPONLY_COOKIES is enabled, tokens are also set as HttpOnly cookies
    for improved security against XSS attacks.
    """
    result = await session.execute(
        select(User).where(User.operator_number == login_data.operator_number)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator number or PIN"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
        )

    if not verify_password(login_data.pin, user.pin_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator number or PIN"
        )
    user.last_login_at_utc = datetime.now(UTC)

    access_token = create_access_token(
        data={
            "user_id": user.id,
            "sub": str(user.id),
            "operator_number": user.operator_number,
            "role": user.role,
        }
    )
    refresh_token = create_refresh_token(user.id)

    # Persist refresh token hash (rotation-friendly)
    payload = verify_token(refresh_token, token_type="refresh")
    if not payload or "exp" not in payload:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not issue refresh token",
        )
    expires_at = datetime.fromtimestamp(payload["exp"], tz=UTC)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=expires_at,
        )
    )
    await session.commit()

    # Set HttpOnly cookies if enabled
    if USE_HTTPONLY_COOKIES:
        set_auth_cookies(response, access_token, refresh_token)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/login-nfc", response_model=TokenResponse)
async def login_nfc(login_data: NFCLoginRequest, session: AsyncSession = Depends(get_session)):
    """Login mit NFC-Tag-ID (ohne PIN)."""
    result = await session.execute(select(User).where(User.nfc_tag_id == login_data.nfc_tag_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid NFC tag ID")

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
        )
    user.last_login_at_utc = datetime.now(UTC)

    access_token = create_access_token(
        data={
            "user_id": user.id,
            "sub": str(user.id),
            "operator_number": user.operator_number,
            "role": user.role,
        }
    )
    refresh_token = create_refresh_token(user.id)

    # Persist refresh token hash (rotation-friendly)
    payload = verify_token(refresh_token, token_type="refresh")
    if not payload or "exp" not in payload:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not issue refresh token",
        )
    expires_at = datetime.fromtimestamp(payload["exp"], tz=UTC)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=expires_at,
        )
    )
    await session.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserRead)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Gibt Informationen über den aktuellen User zurück."""
    return current_user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    refresh_token_cookie: str | None = Cookie(default=None, alias="refresh_token"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Logout: Revokes the current refresh token and clears auth cookies.

    This endpoint:
    1. Revokes the refresh token in the database (if found)
    2. Clears all authentication cookies
    """
    # Try to revoke refresh token if available
    if refresh_token_cookie:
        token_hash = hash_refresh_token(refresh_token_cookie)
        result = await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        db_token = result.scalar_one_or_none()
        if db_token and db_token.revoked_at is None:
            db_token.revoked_at = datetime.now(UTC)
            await session.commit()

    # Clear cookies
    clear_auth_cookies(response)

    return None


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_session),
):
    """Erneuert Access/Refresh Token, wenn der Refresh Token gültig und nicht widerrufen ist."""
    payload = verify_token(body.refresh_token, token_type="refresh")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("user_id") or payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = datetime.now(UTC)
    token_hash = hash_refresh_token(body.refresh_token)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    db_token = result.scalar_one_or_none()

    # Ensure expires_at is timezone-aware for comparison
    expires_at = db_token.expires_at if db_token else None
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    if (
        db_token is None
        or db_token.revoked_at is not None
        or (expires_at is not None and expires_at <= now)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is not valid",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await session.get(User, int(user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # Rotate: revoke old, issue new refresh token
    db_token.revoked_at = now

    # First commit the revocation to prevent race conditions
    await session.commit()

    new_refresh_token = create_refresh_token(user.id)
    new_payload = verify_token(new_refresh_token, token_type="refresh")
    if not new_payload or "exp" not in new_payload:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not issue new refresh token",
        )
    new_expires_at = datetime.fromtimestamp(new_payload["exp"], tz=UTC)

    # Create new token with unique hash check
    new_token_hash = hash_refresh_token(new_refresh_token)

    # Check if token hash already exists (edge case protection)
    existing_check = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == new_token_hash)
    )
    if existing_check.scalar_one_or_none() is not None:
        # Extremely rare: regenerate token if hash collision
        new_refresh_token = create_refresh_token(user.id)
        new_payload = verify_token(new_refresh_token, token_type="refresh")
        if not new_payload or "exp" not in new_payload:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not issue new refresh token",
            )
        new_expires_at = datetime.fromtimestamp(new_payload["exp"], tz=UTC)
        new_token_hash = hash_refresh_token(new_refresh_token)

    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=new_token_hash,
            expires_at=new_expires_at,
            rotated_from_id=db_token.id,
        )
    )

    access_token = create_access_token(
        data={
            "user_id": user.id,
            "sub": str(user.id),
            "operator_number": user.operator_number,
            "role": user.role,
        }
    )

    await session.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/operators", response_model=list[UserRead])
async def list_operators(
    session: AsyncSession = Depends(get_session),
    current_user=Depends(require_restaurantinhaber_role),
):
    """Listet alle Bediener auf (Servecta und Restaurantinhaber).
    Restaurantinhaber sehen keine Servecta-Benutzer."""
    result = await session.execute(select(User).order_by(User.operator_number))
    all_users = result.scalars().all()

    # Restaurantinhaber dürfen Servecta-Benutzer nicht sehen
    if current_user.role == "restaurantinhaber":
        all_users = [u for u in all_users if u.role != "servecta"]

    return all_users


@router.post("/create-operator", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_operator(
    operator_data: UserCreate,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(require_restaurantinhaber_role),
):
    """Erstellt einen neuen Bediener (Servecta und Restaurantinhaber).
    Restaurantinhaber können keine Servecta-Rolle vergeben."""
    # Prüfe ob Bedienernummer bereits existiert
    result = await session.execute(
        select(User).where(User.operator_number == operator_data.operator_number)
    )
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Operator number already exists"
        )

    # Prüfe ob Bedienernummer reserviert ist (0000, 0001 für Servecta)
    if operator_data.operator_number in SERVECTA_OPERATOR_NUMBERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Operator number {operator_data.operator_number} is reserved for Servecta",
        )

    # Restaurantinhaber können keine Servecta-Rolle vergeben
    if current_user.role == "restaurantinhaber" and operator_data.role == "servecta":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Restaurantinhaber cannot create Servecta users",
        )

    # Prüfe ob NFC-Tag-ID bereits existiert (falls gesetzt)
    if operator_data.nfc_tag_id:
        result_nfc = await session.execute(
            select(User).where(User.nfc_tag_id == operator_data.nfc_tag_id)
        )
        existing_user_nfc = result_nfc.scalar_one_or_none()
        if existing_user_nfc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="NFC tag ID already exists"
            )

    user = User(
        operator_number=operator_data.operator_number,
        pin_hash=hash_password(operator_data.pin),
        nfc_tag_id=operator_data.nfc_tag_id,
        first_name=operator_data.first_name,
        last_name=operator_data.last_name,
        role=operator_data.role,
        is_active=True,
    )

    session.add(user)
    await session.commit()
    await session.refresh(user)

    return user


@router.patch("/operators/{operator_id}", response_model=UserRead)
async def update_operator(
    operator_id: int,
    operator_data: UserUpdate,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(require_restaurantinhaber_role),
):
    """Aktualisiert einen Bediener (Servecta und Restaurantinhaber).
    Restaurantinhaber können keine Servecta-Benutzer bearbeiten."""
    user = await session.get(User, operator_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operator not found")

    # Restaurantinhaber können keine Servecta-Benutzer bearbeiten
    if current_user.role == "restaurantinhaber" and user.role == "servecta":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Restaurantinhaber cannot edit Servecta users",
        )

    # Prüfe ob Bedienernummer geändert wird und bereits existiert
    update_data = operator_data.model_dump(exclude_unset=True)
    if "operator_number" in update_data:
        # Prüfe nur, wenn die Bedienernummer tatsächlich geändert wird
        if update_data["operator_number"] != user.operator_number:
            # Prüfe ob die neue Bedienernummer reserviert ist
            if update_data["operator_number"] in SERVECTA_OPERATOR_NUMBERS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Operator number {update_data['operator_number']} is reserved for Servecta",
                )
            # Prüfe ob die neue Bedienernummer bereits existiert
            result = await session.execute(
                select(User).where(
                    User.operator_number == update_data["operator_number"], User.id != operator_id
                )
            )
            existing_user = result.scalar_one_or_none()
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Operator number already exists"
                )

    # Restaurantinhaber können keine Servecta-Rolle vergeben
    if "role" in update_data:
        if current_user.role == "restaurantinhaber" and update_data["role"] == "servecta":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Restaurantinhaber cannot assign Servecta role",
            )
        # Verhindere, dass Servecta-Rolle entfernt wird, wenn Bedienernummer 0000 oder 0001 ist
        if user.operator_number in SERVECTA_OPERATOR_NUMBERS and update_data["role"] != "servecta":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Servecta operator numbers must have servecta role",
            )

    # Prüfe ob NFC-Tag-ID geändert wird und bereits existiert
    if "nfc_tag_id" in update_data and update_data["nfc_tag_id"]:
        result_nfc = await session.execute(
            select(User).where(User.nfc_tag_id == update_data["nfc_tag_id"], User.id != operator_id)
        )
        existing_user_nfc = result_nfc.scalar_one_or_none()
        if existing_user_nfc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="NFC tag ID already exists"
            )

    # PIN hashen, falls geändert
    if "pin" in update_data:
        update_data["pin_hash"] = hash_password(update_data.pop("pin"))

    for field, value in update_data.items():
        setattr(user, field, value)

    await session.commit()
    await session.refresh(user)

    return user


@router.delete("/operators/{operator_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_operator(
    operator_id: int,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(require_restaurantinhaber_role),
):
    """Löscht einen Bediener (Servecta und Restaurantinhaber).
    Restaurantinhaber können keine Servecta-Benutzer löschen."""
    user = await session.get(User, operator_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operator not found")

    # Restaurantinhaber können keine Servecta-Benutzer löschen
    if current_user.role == "restaurantinhaber" and user.role == "servecta":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Restaurantinhaber cannot delete Servecta users",
        )

    # Verhindere Löschen von Servecta-Bedienernummern
    if user.operator_number in SERVECTA_OPERATOR_NUMBERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Servecta operator numbers cannot be deleted",
        )

    await session.delete(user)
    await session.commit()
