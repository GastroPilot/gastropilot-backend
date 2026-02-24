from __future__ import annotations

from datetime import date as date_type
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_manager_or_above, require_staff_or_above
from app.models.restaurant import Table
from app.models.table_config import ReservationTableDayConfig, TableDayConfig
from app.models.user import User

router = APIRouter(prefix="/table-day-configs", tags=["table-day-configs"])


# --- Schemas ---


class TableDayConfigCreate(BaseModel):
    table_id: UUID | None = None
    date: date_type
    is_hidden: bool = False
    is_temporary: bool = False
    number: str | None = None
    capacity: int | None = None
    shape: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    width: float | None = None
    height: float | None = None
    is_active: bool | None = None
    color: str | None = None
    join_group_id: int | None = None
    is_joinable: bool | None = None
    rotation: int | None = None
    notes: str | None = None


class TableDayConfigUpdate(BaseModel):
    is_hidden: bool | None = None
    is_temporary: bool | None = None
    number: str | None = None
    capacity: int | None = None
    shape: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    width: float | None = None
    height: float | None = None
    is_active: bool | None = None
    color: str | None = None
    join_group_id: int | None = None
    is_joinable: bool | None = None
    rotation: int | None = None
    notes: str | None = None


class TableDayConfigResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    table_id: UUID | None = None
    date: date_type
    is_hidden: bool
    is_temporary: bool
    number: str | None = None
    capacity: int | None = None
    shape: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    width: float | None = None
    height: float | None = None
    is_active: bool | None = None
    color: str | None = None
    join_group_id: int | None = None
    is_joinable: bool | None = None
    rotation: int | None = None
    notes: str | None = None
    model_config = {"from_attributes": True}


@router.get("/by-date/{date}", response_model=list[TableDayConfigResponse])
async def list_configs_by_date(
    date: date_type,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(TableDayConfig).where(TableDayConfig.date == date))
    return result.scalars().all()


@router.get("/{config_id}", response_model=TableDayConfigResponse)
async def get_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(TableDayConfig).where(TableDayConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    return config


@router.post("/", response_model=TableDayConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update_config(
    request: Request,
    body: TableDayConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id

    if body.is_temporary and not body.number:
        raise HTTPException(status_code=400, detail="Temporary tables require a number")
    if body.is_temporary and body.capacity is None:
        raise HTTPException(status_code=400, detail="Temporary tables require a capacity")

    # Upsert: check if config already exists for this table+date
    if body.table_id:
        result = await db.execute(
            select(TableDayConfig).where(
                and_(
                    TableDayConfig.tenant_id == effective_tenant_id,
                    TableDayConfig.table_id == body.table_id,
                    TableDayConfig.date == body.date,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            for field, value in body.model_dump(
                exclude_none=True, exclude={"table_id", "date"}
            ).items():
                setattr(existing, field, value)
            await db.commit()
            await db.refresh(existing)
            return existing

    # Inherit properties from permanent table if linking to one
    config_data = body.model_dump(exclude_none=True)
    if body.table_id and not body.is_temporary:
        table_result = await db.execute(select(Table).where(Table.id == body.table_id))
        table = table_result.scalar_one_or_none()
        if table:
            for field in (
                "position_x",
                "position_y",
                "width",
                "height",
                "is_active",
                "rotation",
                "is_joinable",
            ):
                if field not in config_data:
                    val = getattr(table, field, None)
                    if val is not None:
                        config_data[field] = val

    config = TableDayConfig(tenant_id=effective_tenant_id, **config_data)
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


@router.patch("/{config_id}", response_model=TableDayConfigResponse)
async def update_config(
    config_id: UUID,
    body: TableDayConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    result = await db.execute(select(TableDayConfig).where(TableDayConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(config, field, value)

    await db.commit()
    await db.refresh(config)
    return config


@router.delete("/by-date/{date}/table/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config_by_date_table(
    date: date_type,
    table_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    result = await db.execute(
        select(TableDayConfig).where(
            and_(TableDayConfig.date == date, TableDayConfig.table_id == table_id)
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    # Cascade: remove linked reservation configs
    await db.execute(
        select(ReservationTableDayConfig).where(
            ReservationTableDayConfig.table_day_config_id == config.id
        )
    )
    await db.delete(config)
    await db.commit()


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    result = await db.execute(select(TableDayConfig).where(TableDayConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    await db.delete(config)
    await db.commit()


@router.delete("/by-date/{date}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_configs_by_date(
    date: date_type,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    result = await db.execute(select(TableDayConfig).where(TableDayConfig.date == date))
    configs = result.scalars().all()
    for config in configs:
        await db.delete(config)
    await db.commit()
