from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from datetime import date as date_type

from app.dependencies import get_session, get_current_user, require_schichtleiter_role
from app.database.models import TableDayConfig, Table, Restaurant, User, ReservationTableDayConfig
from app.schemas import TableDayConfigCreate, TableDayConfigRead, TableDayConfigUpdate

router = APIRouter(prefix="/restaurants/{restaurant_id}/table-day-configs", tags=["table_day_configs"])


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


@router.get("/by-date/{date}", response_model=list[TableDayConfigRead])
async def get_table_day_configs_by_date(
    restaurant_id: int,
    date: date_type,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Holt alle tages-spezifischen Tabellenkonfigurationen für ein bestimmtes Datum."""
    await _get_restaurant_or_404(restaurant_id, session)
    
    result = await session.execute(
        select(TableDayConfig).where(
            TableDayConfig.restaurant_id == restaurant_id,
            TableDayConfig.date == date
        )
    )
    return result.scalars().all()


@router.get("/{config_id}", response_model=TableDayConfigRead)
async def get_table_day_config(
    restaurant_id: int,
    config_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Holt eine einzelne tages-spezifische Tabellenkonfiguration."""
    await _get_restaurant_or_404(restaurant_id, session)
    
    config = await session.get(TableDayConfig, config_id)
    if not config or config.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table day config not found")
    return config


@router.post("/", response_model=TableDayConfigRead, status_code=status.HTTP_201_CREATED)
async def create_or_update_table_day_config(
    restaurant_id: int,
    config_data: TableDayConfigCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Erstellt oder aktualisiert eine tages-spezifische Tabellenkonfiguration (Schichtleiter oder höher).
    Unterstützt temporäre Tische (table_id=None) und versteckte Tische (is_hidden=True)."""
    await _get_restaurant_or_404(restaurant_id, session)
    
    if config_data.table_id is not None:
        table = await _get_table_or_404(config_data.table_id, restaurant_id, session)
    elif config_data.is_temporary:
        if not config_data.number or not config_data.capacity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Temporäre Tische benötigen 'number' und 'capacity'"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="table_id oder is_temporary muss gesetzt sein"
        )
    
    if config_data.is_temporary and config_data.table_id is None:
        result = await session.execute(
            select(TableDayConfig).where(
                TableDayConfig.restaurant_id == restaurant_id,
                TableDayConfig.table_id.is_(None),
                TableDayConfig.date == config_data.date,
                TableDayConfig.is_temporary == True,
                TableDayConfig.number == config_data.number
            )
        )
    else:
        result = await session.execute(
            select(TableDayConfig).where(
                TableDayConfig.restaurant_id == restaurant_id,
                TableDayConfig.table_id == config_data.table_id,
                TableDayConfig.date == config_data.date
            )
        )
    existing_config = result.scalar_one_or_none()
    
    if existing_config:
        update_data = config_data.model_dump(exclude={"table_id", "date"}, exclude_unset=False)
        for field, value in update_data.items():
            if field in config_data.model_dump(exclude={"table_id", "date"}, exclude_unset=True):
                setattr(existing_config, field, value)
        config = existing_config
    else:
        config_data_dict = config_data.model_dump(exclude={"table_id", "date"}, exclude_unset=True)
        
        if config_data.table_id is not None:
            table = await session.get(Table, config_data.table_id)
            if table:
                if "position_x" not in config_data_dict:
                    config_data_dict["position_x"] = table.position_x
                if "position_y" not in config_data_dict:
                    config_data_dict["position_y"] = table.position_y
                if "width" not in config_data_dict:
                    config_data_dict["width"] = table.width
                if "height" not in config_data_dict:
                    config_data_dict["height"] = table.height
                if "is_active" not in config_data_dict:
                    config_data_dict["is_active"] = table.is_active
                if "rotation" not in config_data_dict:
                    config_data_dict["rotation"] = table.rotation
                if "is_joinable" not in config_data_dict:
                    config_data_dict["is_joinable"] = table.is_joinable
        
        config = TableDayConfig(
            restaurant_id=restaurant_id,
            table_id=config_data.table_id,
            date=config_data.date,
            **config_data_dict
        )
        session.add(config)
    
    try:
        await session.commit()
        await session.refresh(config)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Table day config conflict")
    return config


@router.patch("/{config_id}", response_model=TableDayConfigRead)
async def update_table_day_config(
    restaurant_id: int,
    config_id: int,
    config_data: TableDayConfigUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Aktualisiert eine tages-spezifische Tabellenkonfiguration (Schichtleiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)
    
    config = await session.get(TableDayConfig, config_id)
    if not config or config.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table day config not found")
    
    update_data = config_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)
    
    try:
        await session.commit()
        await session.refresh(config)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Table day config conflict")
    return config


@router.delete("/by-date/{date}/table/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_table_day_config(
    restaurant_id: int,
    date: date_type,
    table_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Löscht eine tages-spezifische Tabellenkonfiguration (Schichtleiter oder höher). 
    Dadurch wird die Standardkonfiguration wieder verwendet."""
    await _get_restaurant_or_404(restaurant_id, session)
    
    result = await session.execute(
        select(TableDayConfig).where(
            TableDayConfig.restaurant_id == restaurant_id,
            TableDayConfig.table_id == table_id,
            TableDayConfig.date == date
        )
    )
    config = result.scalar_one_or_none()
    
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table day config not found")
    
    try:
        await session.delete(config)
        await session.commit()
    except Exception:
        await session.rollback()
        raise


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_table_day_config_by_id(
    restaurant_id: int,
    config_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Löscht eine tages-spezifische Tabellenkonfiguration per ID (Schichtleiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)
    
    config = await session.get(TableDayConfig, config_id)
    if not config or config.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table day config not found")
    
    try:
        await session.delete(config)
        await session.commit()
    except Exception:
        await session.rollback()
        raise


@router.delete("/by-date/{date}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_table_day_configs_for_date(
    restaurant_id: int,
    date: date_type,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Löscht alle tages-spezifischen Tabellenkonfigurationen für ein bestimmtes Datum (Schichtleiter oder höher).
    Dies setzt die Tischanordnung für diesen Tag auf die Standard-Anordnung zurück.
    Löscht auch alle temporären Tische und deren Reservierungszuordnungen."""
    await _get_restaurant_or_404(restaurant_id, session)
    
    result = await session.execute(
        select(TableDayConfig).where(
            TableDayConfig.restaurant_id == restaurant_id,
            TableDayConfig.date == date
        )
    )
    configs = result.scalars().all()
    
    if not configs:
        return
    
    try:
        for config in configs:
            rt_result = await session.execute(
                select(ReservationTableDayConfig).where(
                    ReservationTableDayConfig.table_day_config_id == config.id
                )
            )
            rt_configs = rt_result.scalars().all()
            
            for rt_config in rt_configs:
                await session.delete(rt_config)
            
            await session.delete(config)
        
        await session.commit()
    except Exception:
        await session.rollback()
        raise

