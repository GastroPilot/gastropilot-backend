from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.dependencies import get_session, require_mitarbeiter_role, require_reservations_module
from app.database.models import Message, Restaurant, Reservation, Guest, User
from app.schemas import MessageCreate, MessageRead, MessageUpdate

router = APIRouter(prefix="/restaurants/{restaurant_id}/messages", tags=["messages"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_message_or_404(message_id: int, restaurant_id: int, session: AsyncSession) -> Message:
    msg = await session.get(Message, message_id)
    if not msg or msg.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return msg


@router.post("/", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
async def create_message(
    restaurant_id: int,
    body: MessageCreate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    if body.reservation_id:
        res = await session.get(Reservation, body.reservation_id)
        if not res or res.restaurant_id != restaurant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    if body.guest_id:
        guest = await session.get(Guest, body.guest_id)
        if not guest or guest.restaurant_id != restaurant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")

    msg = Message(
        restaurant_id=restaurant_id,
        reservation_id=body.reservation_id,
        guest_id=body.guest_id,
        direction=body.direction,
        channel=body.channel,
        address=body.address,
        body=body.body,
        status=body.status,
    )
    try:
        session.add(msg)
        await session.commit()
        await session.refresh(msg)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Message conflict")
    return msg


@router.get("/", response_model=list[MessageRead])
async def list_messages(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    res = await session.execute(select(Message).where(Message.restaurant_id == restaurant_id))
    return res.scalars().all()


@router.patch("/{message_id}", response_model=MessageRead)
async def update_message(
    restaurant_id: int,
    message_id: int,
    body: MessageUpdate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    msg = await _get_message_or_404(message_id, restaurant_id, session)
    data = body.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(msg, field, value)
    try:
        await session.commit()
        await session.refresh(msg)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Message conflict")
    return msg


@router.delete("/{message_id}", status_code=status.HTTP_200_OK)
async def delete_message(
    restaurant_id: int,
    message_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    msg = await _get_message_or_404(message_id, restaurant_id, session)
    try:
        await session.delete(msg)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise
    return {"message": "deleted"}
