from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Block, Restaurant, User
from app.dependencies import (
    get_session,
    normalize_datetime_to_utc,
    require_mitarbeiter_role,
    require_reservations_module,
)
from app.schemas import BlockCreate, BlockRead, BlockUpdate

router = APIRouter(prefix="/restaurants/{restaurant_id}/blocks", tags=["blocks"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_block_or_404(block_id: int, restaurant_id: int, session: AsyncSession) -> Block:
    blk = await session.get(Block, block_id)
    if not blk or blk.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Block not found")
    return blk


@router.post("/", response_model=BlockRead, status_code=status.HTTP_201_CREATED)
async def create_block(
    restaurant_id: int,
    body: BlockCreate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)

    start_at = normalize_datetime_to_utc(body.start_at)
    end_at = normalize_datetime_to_utc(body.end_at)
    if start_at >= end_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="End time must be after start time"
        )

    blk = Block(
        restaurant_id=restaurant_id,
        start_at=start_at,
        end_at=end_at,
        reason=body.reason,
        created_by_user_id=current_user.id,
    )
    try:
        session.add(blk)
        await session.commit()
        await session.refresh(blk)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Block conflict")
    return blk


@router.get("/", response_model=list[BlockRead])
async def list_blocks(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    res = await session.execute(select(Block).where(Block.restaurant_id == restaurant_id))
    return res.scalars().all()


@router.patch("/{block_id}", response_model=BlockRead)
async def update_block(
    restaurant_id: int,
    block_id: int,
    body: BlockUpdate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    blk = await _get_block_or_404(block_id, restaurant_id, session)

    data = body.model_dump(exclude_unset=True)
    if "start_at" in data:
        data["start_at"] = normalize_datetime_to_utc(data["start_at"])
    if "end_at" in data:
        data["end_at"] = normalize_datetime_to_utc(data["end_at"])
    if "start_at" in data and "end_at" in data and data["start_at"] >= data["end_at"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="End time must be after start time"
        )

    for field, value in data.items():
        setattr(blk, field, value)
    try:
        await session.commit()
        await session.refresh(blk)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Block conflict")
    return blk


@router.delete("/{block_id}", status_code=status.HTTP_200_OK)
async def delete_block(
    restaurant_id: int,
    block_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_reservations_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    blk = await _get_block_or_404(block_id, restaurant_id, session)
    try:
        await session.delete(blk)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise
    return {"message": "deleted"}
