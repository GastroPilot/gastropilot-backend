from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from datetime import datetime

from app.dependencies import get_session, require_mitarbeiter_role, normalize_datetime_to_utc
from app.database.models import Guest, Restaurant, User
from app.schemas import GuestCreate, GuestRead, GuestUpdate

router = APIRouter(prefix="/restaurants/{restaurant_id}/guests", tags=["guests"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_guest_or_404(guest_id: int, restaurant_id: int, session: AsyncSession) -> Guest:
    guest = await session.get(Guest, guest_id)
    if not guest or guest.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")
    return guest


@router.post("/", response_model=GuestRead, status_code=status.HTTP_201_CREATED)
async def create_guest(
    restaurant_id: int,
    guest_data: GuestCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)

    payload = guest_data.model_dump()
    if payload.get("birthday"):
        payload["birthday"] = normalize_datetime_to_utc(payload["birthday"])

    guest = Guest(restaurant_id=restaurant_id, **payload)
    try:
        session.add(guest)
        await session.commit()
        await session.refresh(guest)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Guest already exists")
    return guest


@router.get("/", response_model=list[GuestRead])
async def list_guests(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    result = await session.execute(select(Guest).where(Guest.restaurant_id == restaurant_id))
    return result.scalars().all()


@router.get("/{guest_id}", response_model=GuestRead)
async def get_guest(
    restaurant_id: int,
    guest_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    guest = await _get_guest_or_404(guest_id, restaurant_id, session)
    return guest


@router.patch("/{guest_id}", response_model=GuestRead)
async def update_guest(
    restaurant_id: int,
    guest_id: int,
    guest_data: GuestUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    guest = await _get_guest_or_404(guest_id, restaurant_id, session)

    update_data = guest_data.model_dump(exclude_unset=True)
    if "birthday" in update_data and update_data["birthday"]:
        update_data["birthday"] = normalize_datetime_to_utc(update_data["birthday"])
    for field, value in update_data.items():
        setattr(guest, field, value)

    try:
        await session.commit()
        await session.refresh(guest)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Guest already exists")

    return guest


@router.delete("/{guest_id}", status_code=status.HTTP_200_OK)
async def delete_guest(
    restaurant_id: int,
    guest_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    guest = await _get_guest_or_404(guest_id, restaurant_id, session)

    try:
        await session.delete(guest)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise

    return {"message": "deleted"}
