from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_staff_or_above
from app.models.user import User
from app.models.waitlist import Message

router = APIRouter(prefix="/messages", tags=["messages"])


class MessageCreate(BaseModel):
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


@router.post("/", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def create_message(
    request: Request,
    body: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
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


@router.get("/", response_model=list[MessageResponse])
async def list_messages(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Message).order_by(Message.created_at.desc()))
    return result.scalars().all()


@router.patch("/{message_id}", response_model=MessageResponse)
async def update_message(
    message_id: UUID,
    body: MessageUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Message).where(Message.id == message_id))
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
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Message).where(Message.id == message_id))
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    await db.delete(msg)
    await db.commit()
    return {"message": "deleted"}
