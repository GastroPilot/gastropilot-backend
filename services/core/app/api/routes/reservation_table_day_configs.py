from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_staff_or_above
from app.models.reservation import Reservation
from app.models.restaurant import Restaurant
from app.models.table_config import ReservationTableDayConfig, TableDayConfig
from app.models.user import User

router = APIRouter(prefix="/reservation-table-day-configs", tags=["reservation-table-day-configs"])


class RTDCCreate(BaseModel):
    restaurant_id: UUID | None = None
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


async def _resolve_tenant_context_for_rtdc(
    request: Request,
    current_user: User,
    db: AsyncSession,
    requested_tenant_id: UUID | None,
    reservation_id: UUID | None,
    table_day_config_id: UUID | None,
) -> UUID:
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id

    reservation_tenant_id: UUID | None = None
    if reservation_id:
        reservation_result = await db.execute(
            select(Reservation.tenant_id).where(Reservation.id == reservation_id)
        )
        reservation_tenant_id = reservation_result.scalar_one_or_none()
        if reservation_tenant_id is None:
            raise HTTPException(status_code=404, detail="Reservation not found")

    config_tenant_id: UUID | None = None
    if table_day_config_id:
        config_result = await db.execute(
            select(TableDayConfig.tenant_id).where(TableDayConfig.id == table_day_config_id)
        )
        config_tenant_id = config_result.scalar_one_or_none()
        if config_tenant_id is None:
            raise HTTPException(status_code=404, detail="TableDayConfig not found")

    reference_tenant_id = reservation_tenant_id or config_tenant_id
    if reservation_tenant_id and config_tenant_id and reservation_tenant_id != config_tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Reservation and table-day-config belong to different tenants",
        )

    if effective_tenant_id:
        if requested_tenant_id and requested_tenant_id != effective_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Requested restaurant_id does not match tenant context",
            )
        if reference_tenant_id and reference_tenant_id != effective_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Referenced entities do not belong to tenant context",
            )
        return effective_tenant_id

    if current_user.role != "platform_admin":
        raise HTTPException(status_code=403, detail="User has no tenant context")

    if requested_tenant_id:
        restaurant_result = await db.execute(
            select(Restaurant.id).where(Restaurant.id == requested_tenant_id)
        )
        if restaurant_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Restaurant not found")
        if reference_tenant_id and reference_tenant_id != requested_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Referenced entities do not belong to requested restaurant",
            )
        return requested_tenant_id

    if reference_tenant_id:
        return reference_tenant_id

    raise HTTPException(
        status_code=400,
        detail=(
            "Tenant context required (token has no tenant and no entity/restaurant tenant "
            "could be resolved)"
        ),
    )


@router.post("", response_model=RTDCResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update(
    request: Request,
    body: RTDCCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_rtdc(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=body.restaurant_id,
        reservation_id=body.reservation_id,
        table_day_config_id=body.table_day_config_id,
    )
    start = _normalize_utc(body.start_at)
    end = _normalize_utc(body.end_at)
    if end <= start:
        raise HTTPException(status_code=400, detail="end_at must be after start_at")

    # Validate table_day_config is temporary and belongs to resolved tenant.
    tdc_result = await db.execute(
        select(TableDayConfig).where(
            TableDayConfig.id == body.table_day_config_id,
            TableDayConfig.tenant_id == effective_tenant_id,
        )
    )
    tdc = tdc_result.scalar_one_or_none()
    if not tdc:
        raise HTTPException(status_code=404, detail="TableDayConfig not found")
    if not tdc.is_temporary:
        raise HTTPException(status_code=400, detail="Only temporary table configs can be linked")

    # Upsert
    result = await db.execute(
        select(ReservationTableDayConfig).where(
            and_(
                ReservationTableDayConfig.reservation_id == body.reservation_id,
                ReservationTableDayConfig.table_day_config_id == body.table_day_config_id,
                ReservationTableDayConfig.tenant_id == effective_tenant_id,
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
        tenant_id=effective_tenant_id,
        start_at=start,
        end_at=end,
    )
    db.add(rtdc)
    await db.commit()
    await db.refresh(rtdc)
    return rtdc


@router.get("", response_model=list[RTDCResponse])
async def list_all(
    request: Request,
    restaurant_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_rtdc(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
        reservation_id=None,
        table_day_config_id=None,
    )
    result = await db.execute(
        select(ReservationTableDayConfig).where(
            ReservationTableDayConfig.tenant_id == effective_tenant_id
        )
    )
    return result.scalars().all()


@router.delete("")
async def delete_mapping(
    request: Request,
    reservation_id: UUID = Query(...),
    table_day_config_id: UUID = Query(...),
    restaurant_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_rtdc(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
        reservation_id=reservation_id,
        table_day_config_id=table_day_config_id,
    )
    result = await db.execute(
        select(ReservationTableDayConfig).where(
            and_(
                ReservationTableDayConfig.reservation_id == reservation_id,
                ReservationTableDayConfig.table_day_config_id == table_day_config_id,
                ReservationTableDayConfig.tenant_id == effective_tenant_id,
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
    request: Request,
    reservation_id: UUID,
    restaurant_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_rtdc(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
        reservation_id=reservation_id,
        table_day_config_id=None,
    )
    result = await db.execute(
        select(ReservationTableDayConfig).where(
            ReservationTableDayConfig.reservation_id == reservation_id,
            ReservationTableDayConfig.tenant_id == effective_tenant_id,
        )
    )
    return result.scalars().all()


@router.get("/by-table-day-config/{table_day_config_id}", response_model=list[RTDCResponse])
async def list_by_table_day_config(
    request: Request,
    table_day_config_id: UUID,
    restaurant_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_rtdc(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
        reservation_id=None,
        table_day_config_id=table_day_config_id,
    )
    result = await db.execute(
        select(ReservationTableDayConfig).where(
            ReservationTableDayConfig.table_day_config_id == table_day_config_id,
            ReservationTableDayConfig.tenant_id == effective_tenant_id,
        )
    )
    return result.scalars().all()
