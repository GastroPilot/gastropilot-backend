from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from app.dependencies import get_session, get_current_user, require_schichtleiter_role, require_servecta_role, normalize_datetime_to_utc
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
from app.schemas import TableCreate, TableRead, TableUpdate

router = APIRouter(prefix="/restaurants/{restaurant_id}/tables", tags=["tables"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_table_or_404(table_id: int, restaurant_id: int, session: AsyncSession) -> Table:
    table = await session.get(Table, table_id)
    if not table or table.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")
    return table


async def _validate_area(area_id: int | None, restaurant_id: int, session: AsyncSession) -> None:
    """Ensure an area belongs to the same restaurant before assigning it."""
    if area_id is None:
        return
    area = await session.get(Area, area_id)
    if not area or area.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area not found")


@router.post("/", response_model=TableRead, status_code=status.HTTP_201_CREATED)
async def create_table(
    restaurant_id: int,
    table_data: TableCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role)
):
    """Erstellt einen neuen Tisch (Schichtleiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)
    await _validate_area(table_data.area_id, restaurant_id, session)
    
    result = await session.execute(
        select(Table).where(
            Table.restaurant_id == restaurant_id,
            Table.number == table_data.number
        )
    )
    existing_table = result.scalar_one_or_none()
    if existing_table:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Table number already exists"
        )
    
    table = Table(
        restaurant_id=restaurant_id,
        **table_data.model_dump()
    )
    try:
        session.add(table)
        await session.commit()
        await session.refresh(table)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Table conflict")
    return table


@router.get("/", response_model=list[TableRead])
async def list_tables(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Listet alle Tische eines Restaurants."""
    await _get_restaurant_or_404(restaurant_id, session)
    result = await session.execute(
        select(Table).where(Table.restaurant_id == restaurant_id).order_by(Table.number)
    )
    return result.scalars().all()


@router.get("/{table_id}", response_model=TableRead)
async def get_table(
    restaurant_id: int,
    table_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Holt einen einzelnen Tisch."""
    await _get_restaurant_or_404(restaurant_id, session)
    return await _get_table_or_404(table_id, restaurant_id, session)


@router.patch("/{table_id}", response_model=TableRead)
async def update_table(
    restaurant_id: int,
    table_id: int,
    table_data: TableUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role)
):
    """Aktualisiert einen Tisch (Schichtleiter oder höher). Synchronisiert Status und Farbe mit Tischen in derselben Gruppe."""
    await _get_restaurant_or_404(restaurant_id, session)
    table = await _get_table_or_404(table_id, restaurant_id, session)
    
    update_data = table_data.model_dump(exclude_unset=True)
    
    if "number" in update_data:
        result = await session.execute(
            select(Table).where(
                Table.restaurant_id == restaurant_id,
                Table.number == update_data["number"],
                Table.id != table_id
            )
        )
        existing_table = result.scalar_one_or_none()
        if existing_table:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Table number already exists"
            )

    if "area_id" in update_data:
        await _validate_area(update_data.get("area_id"), restaurant_id, session)
    
    sync_fields = {"is_active"}
    fields_to_sync = {field: value for field, value in update_data.items() if field in sync_fields}
    
    for field, value in update_data.items():
        setattr(table, field, value)
    
    if fields_to_sync and table.join_group_id is not None:
        result = await session.execute(
            select(Table).where(
                Table.restaurant_id == restaurant_id,
                Table.join_group_id == table.join_group_id,
                Table.id != table_id
            )
        )
        group_tables = result.scalars().all()
        
        for group_table in group_tables:
            for field, value in fields_to_sync.items():
                setattr(group_table, field, value)
    
    try:
        await session.commit()
        await session.refresh(table)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Table conflict")
    return table


@router.delete("/orphans", status_code=status.HTTP_200_OK)
async def delete_orphan_tables(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_servecta_role),
):
    """Löscht alle Tische ohne Area (Schichtleiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)

    result = await session.execute(
        select(Table.id).where(
            Table.restaurant_id == restaurant_id,
            Table.area_id.is_(None),
        )
    )
    table_ids = result.scalars().all()
    if not table_ids:
        return {"message": "deleted", "deleted_tables": 0}

    try:
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
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise

    return {"message": "deleted", "deleted_tables": len(table_ids)}


@router.delete("/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_table(
    restaurant_id: int,
    table_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role)
):
    """Löscht einen Tisch (Schichtleiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)
    table = await _get_table_or_404(table_id, restaurant_id, session)
    
    try:
        await session.delete(table)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise
