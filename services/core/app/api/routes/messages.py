from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_staff_or_above
from app.models.reservation import Guest, Reservation
from app.models.restaurant import Restaurant
from app.models.user import User
from app.models.waitlist import Message

router = APIRouter(prefix="/messages", tags=["messages"])


class MessageCreate(BaseModel):
    restaurant_id: UUID | None = None
    reservation_id: UUID | None = None
    guest_id: UUID | None = None
    direction: str
    channel: str
    address: str
    body: str
    status: str = "queued"


class MessageUpdate(BaseModel):
    direction: str | None = None
    channel: str | None = None
    address: str | None = None
    body: str | None = None
    status: str | None = None


class MessageResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    reservation_id: UUID | None = None
    guest_id: UUID | None = None
    direction: str
    channel: str
    address: str
    body: str
    status: str
    created_at: datetime
    model_config = {"from_attributes": True}


async def _resolve_tenant_context_for_message(
    request: Request,
    current_user: User,
    db: AsyncSession,
    requested_tenant_id: UUID | None,
    reservation_id: UUID | None,
    guest_id: UUID | None,
) -> UUID:
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id

    reservation_tenant_id: UUID | None = None
    if reservation_id:
        reservation_result = await db.execute(
            select(Reservation.tenant_id).where(Reservation.id == reservation_id)
        )
        reservation_tenant_id = reservation_result.scalar_one_or_none()
        if reservation_tenant_id is None:
            raise HTTPException(status_code=404, detail="Reservation not found")

    guest_tenant_id: UUID | None = None
    if guest_id:
        guest_result = await db.execute(select(Guest.tenant_id).where(Guest.id == guest_id))
        guest_tenant_id = guest_result.scalar_one_or_none()
        if guest_tenant_id is None:
            raise HTTPException(status_code=404, detail="Guest not found")

    reference_tenant_id = reservation_tenant_id or guest_tenant_id
    if reservation_tenant_id and guest_tenant_id and reservation_tenant_id != guest_tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Reservation and guest belong to different tenants",
        )

    if effective_tenant_id:
        if requested_tenant_id and requested_tenant_id != effective_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Requested restaurant_id does not match tenant context",
            )
        if reference_tenant_id and reference_tenant_id != effective_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Referenced entities do not belong to tenant context",
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
        if reference_tenant_id and reference_tenant_id != requested_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Referenced entities do not belong to requested restaurant",
            )
        return requested_tenant_id

    if reference_tenant_id:
        return reference_tenant_id

    raise HTTPException(
        status_code=400,
        detail=(
            "Tenant context required (token has no tenant and no entity/restaurant tenant "
            "could be resolved)"
        ),
    )


async def _resolve_effective_tenant_id(
    request: Request,
    current_user: User,
    db: AsyncSession,
) -> UUID:
    return await _resolve_tenant_context_for_message(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=None,
        reservation_id=None,
        guest_id=None,
    )


@router.post("", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def create_message(
    request: Request,
    body: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_message(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=body.restaurant_id,
        reservation_id=body.reservation_id,
        guest_id=body.guest_id,
    )
    msg = Message(
        tenant_id=effective_tenant_id,
        reservation_id=body.reservation_id,
        guest_id=body.guest_id,
        direction=body.direction,
        channel=body.channel,
        address=body.address,
        body=body.body,
        status=body.status,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


@router.get("", response_model=list[MessageResponse])
async def list_messages(
    request: Request,
    restaurant_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_message(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
        reservation_id=None,
        guest_id=None,
    )
    result = await db.execute(
        select(Message)
        .where(Message.tenant_id == effective_tenant_id)
        .order_by(Message.created_at.desc())
    )
    return result.scalars().all()


@router.patch("/{message_id}", response_model=MessageResponse)
async def update_message(
    request: Request,
    message_id: UUID,
    body: MessageUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_effective_tenant_id(
        request=request,
        current_user=current_user,
        db=db,
    )
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.tenant_id == effective_tenant_id,
        )
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(msg, field, value)

    await db.commit()
    await db.refresh(msg)
    return msg


@router.delete("/{message_id}")
async def delete_message(
    request: Request,
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_effective_tenant_id(
        request=request,
        current_user=current_user,
        db=db,
    )
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.tenant_id == effective_tenant_id,
        )
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    await db.delete(msg)
    await db.commit()
    return {"message": "deleted"}
