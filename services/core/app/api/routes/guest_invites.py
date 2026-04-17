"""Guest invite endpoints for reservation companions."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_staff_or_above
from app.core.guest_deps import _get_guest_db, get_current_guest
from app.models.reservation import Reservation, ReservationInvite
from app.models.restaurant import Restaurant
from app.models.user import GuestProfile, User
from app.schemas.guest_invite import (
    AcceptInviteRequest,
    CreateInviteResponse,
    GuestInviteResponse,
    InvitedGuestProfile,
    InviteDetailsResponse,
    InviteReservationInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["guest-invites"])

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://gpilot.app")


# ─── Helpers ──────────────────────────────────────────────────────────


def _build_invite_response(invite: ReservationInvite) -> GuestInviteResponse:
    invited_guest = None
    if invite.status == "accepted" and invite.guest_first_name:
        invited_guest = InvitedGuestProfile(
            first_name=invite.guest_first_name,
            last_name=invite.guest_last_name or "",
            allergen_ids=invite.guest_allergen_ids or [],
        )
    return GuestInviteResponse(
        id=invite.id,
        reservation_id=invite.reservation_id,
        invite_token=invite.invite_token,
        status=invite.status,
        invited_guest=invited_guest,
        created_at=invite.created_at,
        updated_at=invite.updated_at,
    )


async def _get_reservation_for_guest(
    session: AsyncSession, reservation_id: str, guest: GuestProfile
) -> Reservation:
    """Prüft ob die Reservierung dem Gast gehört."""
    result = await session.execute(
        select(Reservation).where(
            and_(
                Reservation.id == reservation_id,
                Reservation.guest_email == guest.email,
                Reservation.status.in_(["pending", "confirmed"]),
            )
        )
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return reservation


# ─── Booker Endpoints (Auth erforderlich) ─────────────────────────────


@router.post(
    "/public/me/reservations/{reservation_id}/invites",
    response_model=CreateInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invite(
    reservation_id: str,
    guest: GuestProfile = Depends(get_current_guest),
    session: AsyncSession = Depends(_get_guest_db),
):
    """Erstellt eine neue Einladung für eine Reservierung."""
    reservation = await _get_reservation_for_guest(session, reservation_id, guest)

    # Max Einladungen prüfen
    max_invites = reservation.party_size - 1
    count_result = await session.execute(
        select(func.count()).select_from(ReservationInvite).where(
            and_(
                ReservationInvite.reservation_id == reservation.id,
                ReservationInvite.status != "declined",
            )
        )
    )
    current_count = count_result.scalar() or 0
    if current_count >= max_invites:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Maximum {max_invites} invites allowed",
        )

    invite = ReservationInvite(
        tenant_id=reservation.tenant_id,
        reservation_id=reservation.id,
        inviter_guest_profile_id=guest.id,
        inviter_name=f"{guest.first_name} {guest.last_name}".strip(),
    )
    session.add(invite)
    await session.commit()
    await session.refresh(invite)

    invite_url = f"{APP_BASE_URL}/invite/{invite.invite_token}"

    return CreateInviteResponse(
        invite_token=invite.invite_token,
        invite_url=invite_url,
    )


@router.get(
    "/public/me/reservations/{reservation_id}/invites",
    response_model=list[GuestInviteResponse],
)
async def list_invites(
    reservation_id: str,
    guest: GuestProfile = Depends(get_current_guest),
    session: AsyncSession = Depends(_get_guest_db),
):
    """Listet alle Einladungen einer Reservierung (für den Booker)."""
    reservation = await _get_reservation_for_guest(session, reservation_id, guest)

    result = await session.execute(
        select(ReservationInvite)
        .where(ReservationInvite.reservation_id == reservation.id)
        .order_by(ReservationInvite.created_at)
    )
    invites = result.scalars().all()
    return [_build_invite_response(inv) for inv in invites]


@router.delete(
    "/public/me/reservations/{reservation_id}/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invite(
    reservation_id: str,
    invite_id: str,
    guest: GuestProfile = Depends(get_current_guest),
    session: AsyncSession = Depends(_get_guest_db),
):
    """Widerruft eine ausstehende Einladung."""
    await _get_reservation_for_guest(session, reservation_id, guest)

    result = await session.execute(
        select(ReservationInvite).where(
            and_(
                ReservationInvite.id == invite_id,
                ReservationInvite.reservation_id == reservation_id,
                ReservationInvite.status == "pending",
            )
        )
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    await session.delete(invite)
    await session.commit()


# ─── Public Endpoints (Token-basiert, kein Auth nötig) ────────────────


@router.get("/public/invites/{token}", response_model=InviteDetailsResponse)
async def get_invite_details(
    token: str,
    session: AsyncSession = Depends(_get_guest_db),
):
    """Zeigt Reservierungsdetails für eine Einladung (öffentlich via Token)."""
    result = await session.execute(
        select(ReservationInvite).where(ReservationInvite.invite_token == token)
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invite token")

    # Reservierung laden
    res_result = await session.execute(
        select(Reservation).where(Reservation.id == invite.reservation_id)
    )
    reservation = res_result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    # Restaurant laden
    rest_result = await session.execute(
        select(Restaurant).where(Restaurant.id == reservation.tenant_id)
    )
    restaurant = rest_result.scalar_one_or_none()

    start_local = reservation.start_at
    date_str = start_local.strftime("%Y-%m-%d")
    time_str = start_local.strftime("%H:%M")

    return InviteDetailsResponse(
        reservation=InviteReservationInfo(
            restaurant_name=restaurant.name if restaurant else "Restaurant",
            restaurant_slug=restaurant.slug if restaurant else "",
            date=date_str,
            time=time_str,
            party_size=reservation.party_size,
            host_name=invite.inviter_name,
        ),
        invite_status=invite.status,
    )


@router.post("/public/invites/{token}/accept")
async def accept_invite(
    token: str,
    body: AcceptInviteRequest,
    session: AsyncSession = Depends(_get_guest_db),
):
    """Einladung annehmen und Gästeprofil teilen (kein Auth nötig)."""
    result = await session.execute(
        select(ReservationInvite).where(ReservationInvite.invite_token == token)
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invite token")

    if invite.status == "accepted":
        raise HTTPException(status_code=409, detail="Already accepted")

    if invite.status == "declined":
        raise HTTPException(status_code=409, detail="Invite was declined")

    # Reservierung prüfen — muss noch aktiv sein
    res_result = await session.execute(
        select(Reservation).where(
            and_(
                Reservation.id == invite.reservation_id,
                Reservation.status.in_(["pending", "confirmed"]),
            )
        )
    )
    reservation = res_result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=410, detail="Reservation is no longer active")

    invite.status = "accepted"
    invite.guest_first_name = body.first_name
    invite.guest_last_name = body.last_name
    invite.guest_allergen_ids = body.allergen_ids
    invite.accepted_at = datetime.now(UTC)

    await session.commit()

    return {"success": True}


@router.post("/public/invites/{token}/decline")
async def decline_invite(
    token: str,
    session: AsyncSession = Depends(_get_guest_db),
):
    """Einladung ablehnen (kein Auth nötig)."""
    result = await session.execute(
        select(ReservationInvite).where(ReservationInvite.invite_token == token)
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invite token")

    if invite.status != "pending":
        raise HTTPException(status_code=409, detail="Invite is not pending")

    invite.status = "declined"
    invite.declined_at = datetime.now(UTC)
    await session.commit()

    return {"success": True}


# ─── Staff Endpoints (Tenant-scoped, Auth erforderlich) ───────────────


@router.get("/reservations/{reservation_id}/invites", response_model=list[GuestInviteResponse])
async def staff_list_invites(
    reservation_id: str,
    user: User = Depends(require_staff_or_above),
    db: AsyncSession = Depends(get_db),
):
    """Listet alle Einladungen einer Reservierung (für Staff/Manager)."""
    # Prüfe ob Reservierung existiert (RLS filtert nach Tenant)
    res_result = await db.execute(
        select(Reservation).where(Reservation.id == reservation_id)
    )
    if not res_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Reservation not found")

    result = await db.execute(
        select(ReservationInvite)
        .where(ReservationInvite.reservation_id == reservation_id)
        .order_by(ReservationInvite.created_at)
    )
    invites = result.scalars().all()
    return [_build_invite_response(inv) for inv in invites]
