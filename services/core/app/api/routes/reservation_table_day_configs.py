from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_staff_or_above
from app.models.table_config import ReservationTableDayConfig, TableDayConfig
from app.models.user import User

router = APIRouter(prefix="/reservation-table-day-configs", tags=["reservation-table-day-configs"])


class RTDCCreate(BaseModel):
    reservation_id: UUID
    table_day_config_id: UUID
    start_at: datetime
    end_at: datetime


class RTDCResponse(BaseModel):
    reservation_id: UUID
    table_day_config_id: UUID
    tenant_id: UUID
    start_at: datetime
    end_at: datetime
    model_config = {"from_attributes": True}


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@router.post("", response_model=RTDCResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update(
    request: Request,
    body: RTDCCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
    start = _normalize_utc(body.start_at)
    end = _normalize_utc(body.end_at)
    if end <= start:
        raise HTTPException(status_code=400, detail="end_at must be after start_at")

    # Validate table_day_config is temporary
    tdc_result = await db.execute(
        select(TableDayConfig).where(TableDayConfig.id == body.table_day_config_id)
    )
    tdc = tdc_result.scalar_one_or_none()
    if not tdc:
        raise HTTPException(status_code=404, detail="TableDayConfig not found")
    if not tdc.is_temporary:
        raise HTTPException(status_code=400, detail="Only temporary table configs can be linked")

    # Prefer tenant from linked table-day-config when request context has no tenant
    resolved_tenant_id = effective_tenant_id or tdc.tenant_id
    if resolved_tenant_id != tdc.tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Tenant context does not match table-day-config tenant",
        )

    # Upsert
    result = await db.execute(
        select(ReservationTableDayConfig).where(
            and_(
                ReservationTableDayConfig.reservation_id == body.reservation_id,
                ReservationTableDayConfig.table_day_config_id == body.table_day_config_id,
            )
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.start_at = start
        existing.end_at = end
        await db.commit()
        await db.refresh(existing)
        return existing

    rtdc = ReservationTableDayConfig(
        reservation_id=body.reservation_id,
        table_day_config_id=body.table_day_config_id,
        tenant_id=resolved_tenant_id,
        start_at=start,
        end_at=end,
    )
    db.add(rtdc)
    await db.commit()
    await db.refresh(rtdc)
    return rtdc


@router.get("", response_model=list[RTDCResponse])
async def list_all(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(ReservationTableDayConfig))
    return result.scalars().all()


@router.delete("")
async def delete_mapping(
    reservation_id: UUID = Query(...),
    table_day_config_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(
        select(ReservationTableDayConfig).where(
            and_(
                ReservationTableDayConfig.reservation_id == reservation_id,
                ReservationTableDayConfig.table_day_config_id == table_day_config_id,
            )
        )
    )
    rtdc = result.scalar_one_or_none()
    if not rtdc:
        raise HTTPException(status_code=404, detail="Mapping not found")
    await db.delete(rtdc)
    await db.commit()
    return {"message": "deleted"}


@router.get("/by-reservation/{reservation_id}", response_model=list[RTDCResponse])
async def list_by_reservation(
    reservation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(
        select(ReservationTableDayConfig).where(
            ReservationTableDayConfig.reservation_id == reservation_id
        )
    )
    return result.scalars().all()


@router.get("/by-table-day-config/{table_day_config_id}", response_model=list[RTDCResponse])
async def list_by_table_day_config(
    table_day_config_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(
        select(ReservationTableDayConfig).where(
            ReservationTableDayConfig.table_day_config_id == table_day_config_id
        )
    )
    return result.scalars().all()
