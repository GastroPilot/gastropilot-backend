"""Guest authentication endpoints."""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.models.user import GuestProfile
from app.schemas.guest_auth import (
    EmailVerifyRequest,
    GuestLoginRequest,
    GuestRegisterRequest,
    GuestTokenResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/auth", tags=["guest-auth"])

ACCESS_TOKEN_EXPIRE_MINUTES = 60


def _build_guest_tokens(guest_id: str) -> GuestTokenResponse:
    """Build access + refresh token pair for a guest."""
    access_token = create_access_token({"sub": guest_id, "role": "guest"})
    refresh_token = create_refresh_token(guest_id)
    return GuestTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/register",
    response_model=GuestTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_guest(
    body: GuestRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new guest account and return JWT tokens."""
    # Check if email already exists
    result = await db.execute(select(GuestProfile).where(GuestProfile.email == body.email))
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Email already registered",
        )

    verification_token = secrets.token_urlsafe(32)

    guest = GuestProfile(
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        phone=body.phone,
        password_hash=hash_password(body.password),
        email_verified=False,
        email_verification_token=verification_token,
    )
    db.add(guest)
    await db.commit()
    await db.refresh(guest)

    # TODO: Send verification email via notifications service
    logger.info("Guest registered: %s (verification pending)", body.email)

    return _build_guest_tokens(str(guest.id))


@router.post("/login", response_model=GuestTokenResponse)
async def login_guest(
    body: GuestLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Login with email and password, return JWT tokens."""
    result = await db.execute(select(GuestProfile).where(GuestProfile.email == body.email))
    guest = result.scalar_one_or_none()

    if not guest or not guest.password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(body.password, guest.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return _build_guest_tokens(str(guest.id))


@router.post("/verify-email")
async def verify_email(
    body: EmailVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify guest email with token."""
    result = await db.execute(
        select(GuestProfile).where(GuestProfile.email_verification_token == body.token)
    )
    guest = result.scalar_one_or_none()

    if not guest:
        raise HTTPException(status_code=400, detail="Invalid verification token")

    guest.email_verified = True
    guest.email_verification_token = None
    await db.commit()

    return {"message": "Email verified successfully"}


@router.post("/refresh", response_model=GuestTokenResponse)
async def refresh_guest_token(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Refresh guest access token."""
    token = body.get("refresh_token")
    if not token:
        raise HTTPException(status_code=400, detail="refresh_token required")

    payload = verify_token(token, token_type="refresh")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    guest_id = payload.get("user_id") or payload.get("sub")
    if not guest_id:
        raise HTTPException(status_code=401, detail="Token missing subject")

    result = await db.execute(select(GuestProfile).where(GuestProfile.id == guest_id))
    guest = result.scalar_one_or_none()
    if not guest:
        raise HTTPException(status_code=401, detail="Guest not found")

    return _build_guest_tokens(str(guest.id))


@router.post("/forgot-password")
async def forgot_password(
    body: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send password reset email."""
    result = await db.execute(select(GuestProfile).where(GuestProfile.email == body.email))
    guest = result.scalar_one_or_none()

    # Always return success to prevent email enumeration
    if guest:
        reset_token = secrets.token_urlsafe(32)
        guest.email_verification_token = reset_token
        await db.commit()

        from app.core.config import settings

        try:
            from shared.events import event_publisher

            reset_url = f"{settings.GUEST_PORTAL_URL}" f"/auth/reset-password?token={reset_token}"
            await event_publisher.publish(
                "password_reset.requested",
                {
                    "guest_email": guest.email,
                    "guest_name": guest.first_name,
                    "reset_url": reset_url,
                },
            )
        except Exception:
            logger.warning(
                "Could not publish password reset event for: %s",
                body.email,
            )
        logger.info("Password reset requested for: %s", body.email)

    return {"message": "If the email exists, a reset link was sent"}


@router.post("/reset-password")
async def reset_password(
    body: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db),
):
    """Reset password with token."""
    result = await db.execute(
        select(GuestProfile).where(GuestProfile.email_verification_token == body.token)
    )
    guest = result.scalar_one_or_none()

    if not guest:
        raise HTTPException(status_code=400, detail="Invalid reset token")

    guest.password_hash = hash_password(body.new_password)
    guest.email_verification_token = None
    await db.commit()

    return {"message": "Password reset successfully"}
