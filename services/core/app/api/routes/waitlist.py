from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_staff_or_above
from app.models.reservation import Guest
from app.models.restaurant import Restaurant
from app.models.user import User
from app.models.waitlist import Waitlist

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


class WaitlistCreate(BaseModel):
    restaurant_id: UUID | None = None
    guest_id: UUID | None = None
    party_size: int
    desired_from: datetime | None = None
    desired_to: datetime | None = None
    status: str = "waiting"
    priority: int | None = None
    notes: str | None = None


class WaitlistUpdate(BaseModel):
    guest_id: UUID | None = None
    party_size: int | None = None
    desired_from: datetime | None = None
    desired_to: datetime | None = None
    status: str | None = None
    priority: int | None = None
    notified_at: datetime | None = None
    confirmed_at: datetime | None = None
    notes: str | None = None


class WaitlistResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    guest_id: UUID | None = None
    party_size: int
    desired_from: datetime | None = None
    desired_to: datetime | None = None
    status: str
    priority: int | None = None
    notified_at: datetime | None = None
    confirmed_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


def _normalize_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


async def _resolve_tenant_context_for_waitlist(
    request: Request,
    current_user: User,
    db: AsyncSession,
    requested_tenant_id: UUID | None,
    guest_id: UUID | None,
) -> UUID:
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id

    guest_tenant_id: UUID | None = None
    if guest_id:
        guest_result = await db.execute(select(Guest.tenant_id).where(Guest.id == guest_id))
        guest_tenant_id = guest_result.scalar_one_or_none()
        if guest_tenant_id is None:
            raise HTTPException(status_code=404, detail="Guest not found")

    if effective_tenant_id:
        if requested_tenant_id and requested_tenant_id != effective_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Requested restaurant_id does not match tenant context",
            )
        if guest_tenant_id and guest_tenant_id != effective_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Guest does not belong to tenant context",
            )
        return effective_tenant_id

    if current_user.role != "platform_admin":
        raise HTTPException(status_code=403, detail="User has no tenant context")

    if requested_tenant_id:
        restaurant_result = await db.execute(
            select(Restaurant.id).where(Restaurant.id == requested_tenant_id)
        )
        if restaurant_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Restaurant not found")
        if guest_tenant_id and guest_tenant_id != requested_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Guest does not belong to requested restaurant",
            )
        return requested_tenant_id

    if guest_tenant_id:
        return guest_tenant_id

    raise HTTPException(
        status_code=400,
        detail=(
            "Tenant context required (token has no tenant and no guest/restaurant tenant "
            "could be resolved)"
        ),
    )


@router.post("", response_model=WaitlistResponse, status_code=status.HTTP_201_CREATED)
async def create_entry(
    request: Request,
    body: WaitlistCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_waitlist(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=body.restaurant_id,
        guest_id=body.guest_id,
    )
    entry = Waitlist(
        tenant_id=effective_tenant_id,
        guest_id=body.guest_id,
        party_size=body.party_size,
        desired_from=_normalize_utc(body.desired_from),
        desired_to=_normalize_utc(body.desired_to),
        status=body.status,
        priority=body.priority,
        notes=body.notes,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.get("", response_model=list[WaitlistResponse])
async def list_entries(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Waitlist).order_by(Waitlist.created_at))
    return result.scalars().all()


@router.patch("/{wait_id}", response_model=WaitlistResponse)
async def update_entry(
    wait_id: UUID,
    body: WaitlistUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Waitlist).where(Waitlist.id == wait_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")

    update_data = body.model_dump(exclude_unset=True)
    dt_fields = ("desired_from", "desired_to", "notified_at", "confirmed_at")
    for field, value in update_data.items():
        if field in dt_fields:
            value = _normalize_utc(value)
        setattr(entry, field, value)

    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/{wait_id}")
async def delete_entry(
    wait_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Waitlist).where(Waitlist.id == wait_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    await db.delete(entry)
    await db.commit()
    return {"message": "deleted"}
