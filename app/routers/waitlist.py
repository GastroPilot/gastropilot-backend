from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.dependencies import get_session, require_mitarbeiter_role, normalize_datetime_to_utc, require_reservations_module
from app.database.models import Waitlist, Restaurant, Guest, User
from app.schemas import WaitlistCreate, WaitlistRead, WaitlistUpdate

router = APIRouter(prefix="/restaurants/{restaurant_id}/waitlist", tags=["waitlist"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_wait_or_404(wait_id: int, restaurant_id: int, session: AsyncSession) -> Waitlist:
    entry = await session.get(Waitlist, wait_id)
    if not entry or entry.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waitlist entry not found")
    return entry


@router.post("/", response_model=WaitlistRead, status_code=status.HTTP_201_CREATED)
async def create_waitlist_entry(
    restaurant_id: int,
    body: WaitlistCreate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    if body.guest_id:
        guest = await session.get(Guest, body.guest_id)
        if not guest or guest.restaurant_id != restaurant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")

    desired_from = normalize_datetime_to_utc(body.desired_from) if body.desired_from else None
    desired_to = normalize_datetime_to_utc(body.desired_to) if body.desired_to else None

    entry = Waitlist(
        restaurant_id=restaurant_id,
        guest_id=body.guest_id,
        party_size=body.party_size,
        desired_from=desired_from,
        desired_to=desired_to,
        status=body.status,
        priority=body.priority,
        notes=body.notes,
    )
    try:
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Waitlist conflict")
    return entry


@router.get("/", response_model=list[WaitlistRead])
async def list_waitlist(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    res = await session.execute(select(Waitlist).where(Waitlist.restaurant_id == restaurant_id))
    return res.scalars().all()


@router.patch("/{wait_id}", response_model=WaitlistRead)
async def update_waitlist_entry(
    restaurant_id: int,
    wait_id: int,
    body: WaitlistUpdate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    entry = await _get_wait_or_404(wait_id, restaurant_id, session)

    data = body.model_dump(exclude_unset=True)
    if "guest_id" in data and data["guest_id"]:
        guest = await session.get(Guest, data["guest_id"])
        if not guest or guest.restaurant_id != restaurant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found")
    if "desired_from" in data and data["desired_from"]:
        data["desired_from"] = normalize_datetime_to_utc(data["desired_from"])
    if "desired_to" in data and data["desired_to"]:
        data["desired_to"] = normalize_datetime_to_utc(data["desired_to"])
    if "notified_at" in data and data["notified_at"]:
        data["notified_at"] = normalize_datetime_to_utc(data["notified_at"])
    if "confirmed_at" in data and data["confirmed_at"]:
        data["confirmed_at"] = normalize_datetime_to_utc(data["confirmed_at"])

    for field, value in data.items():
        setattr(entry, field, value)
    try:
        await session.commit()
        await session.refresh(entry)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Waitlist conflict")
    return entry


@router.delete("/{wait_id}", status_code=status.HTTP_200_OK)
async def delete_waitlist_entry(
    restaurant_id: int,
    wait_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    entry = await _get_wait_or_404(wait_id, restaurant_id, session)
    try:
        await session.delete(entry)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise
    return {"message": "deleted"}
