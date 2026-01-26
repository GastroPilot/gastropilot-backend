from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Area,
    BlockAssignment,
    ReservationTable,
    ReservationTableDayConfig,
    Restaurant,
    Table,
    TableDayConfig,
    User,
)
from app.dependencies import get_session, require_mitarbeiter_role
from app.schemas import AreaCreate, AreaRead, AreaUpdate

router = APIRouter(prefix="/restaurants/{restaurant_id}/areas", tags=["areas"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_area_or_404(area_id: int, restaurant_id: int, session: AsyncSession) -> Area:
    area = await session.get(Area, area_id)
    if not area or area.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area not found")
    return area


@router.post("/", response_model=AreaRead, status_code=status.HTTP_201_CREATED)
async def create_area(
    restaurant_id: int,
    area_in: AreaCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    area = Area(restaurant_id=restaurant_id, name=area_in.name.strip())
    try:
        session.add(area)
        await session.commit()
        await session.refresh(area)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Area name already exists")
    return area


@router.get("/", response_model=list[AreaRead])
async def list_areas(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    result = await session.execute(select(Area).where(Area.restaurant_id == restaurant_id))
    return result.scalars().all()


@router.patch("/{area_id}", response_model=AreaRead)
async def update_area(
    restaurant_id: int,
    area_id: int,
    area_in: AreaUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    area = await _get_area_or_404(area_id, restaurant_id, session)
    if area_in.name is not None:
        area.name = area_in.name.strip()
    try:
        await session.commit()
        await session.refresh(area)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Area name already exists")
    return area


@router.delete("/{area_id}", status_code=status.HTTP_200_OK)
async def delete_area(
    restaurant_id: int,
    area_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    area = await _get_area_or_404(area_id, restaurant_id, session)
    try:
        result = await session.execute(
            select(Table.id).where(
                Table.restaurant_id == restaurant_id,
                Table.area_id == area_id,
            )
        )
        table_ids = result.scalars().all()
        if table_ids:
            result = await session.execute(
                select(TableDayConfig.id).where(TableDayConfig.table_id.in_(table_ids))
            )
            table_day_config_ids = result.scalars().all()
            if table_day_config_ids:
                await session.execute(
                    delete(ReservationTableDayConfig).where(
                        ReservationTableDayConfig.table_day_config_id.in_(table_day_config_ids)
                    )
                )
            await session.execute(
                delete(TableDayConfig).where(TableDayConfig.table_id.in_(table_ids))
            )
            await session.execute(
                delete(ReservationTable).where(ReservationTable.table_id.in_(table_ids))
            )
            await session.execute(
                delete(BlockAssignment).where(BlockAssignment.table_id.in_(table_ids))
            )
            await session.execute(delete(Table).where(Table.id.in_(table_ids)))
        await session.delete(area)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise
    return {"message": "deleted"}
