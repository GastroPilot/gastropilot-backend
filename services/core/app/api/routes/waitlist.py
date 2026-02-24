from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_staff_or_above
from app.models.waitlist import Waitlist
from app.models.user import User

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


class WaitlistCreate(BaseModel):
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


@router.post("/", response_model=WaitlistResponse, status_code=status.HTTP_201_CREATED)
async def create_entry(
    request: Request,
    body: WaitlistCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
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


@router.get("/", response_model=list[WaitlistResponse])
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
