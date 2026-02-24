from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_manager_or_above, require_staff_or_above
from app.models.voucher import Voucher, VoucherUsage
from app.models.user import User

router = APIRouter(prefix="/vouchers", tags=["vouchers"])


class VoucherCreate(BaseModel):
    code: str
    name: str | None = None
    description: str | None = None
    type: str = "fixed"
    value: float
    valid_from: date | None = None
    valid_until: date | None = None
    max_uses: int | None = None
    min_order_value: float | None = None
    is_active: bool = True

class VoucherUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    description: str | None = None
    type: str | None = None
    value: float | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    max_uses: int | None = None
    min_order_value: float | None = None
    is_active: bool | None = None

class VoucherResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    code: str
    name: str | None = None
    description: str | None = None
    type: str
    value: float
    valid_from: date | None = None
    valid_until: date | None = None
    max_uses: int | None = None
    used_count: int
    min_order_value: float | None = None
    is_active: bool
    created_by_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class VoucherValidateRequest(BaseModel):
    code: str
    order_value: float | None = None

class VoucherValidateResponse(BaseModel):
    valid: bool
    voucher_id: UUID | None = None
    discount_type: str | None = None
    discount_value: float | None = None
    discount_amount: float | None = None
    message: str | None = None

class VoucherUsageResponse(BaseModel):
    id: UUID
    voucher_id: UUID
    reservation_id: UUID | None = None
    used_by_email: str | None = None
    discount_amount: float
    used_at: datetime
    model_config = {"from_attributes": True}


@router.post("/", response_model=VoucherResponse, status_code=status.HTTP_201_CREATED)
async def create_voucher(
    request: Request,
    body: VoucherCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
    voucher = Voucher(
        tenant_id=effective_tenant_id,
        code=body.code.upper().strip(),
        name=body.name,
        description=body.description,
        type=body.type,
        value=body.value,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        max_uses=body.max_uses,
        min_order_value=body.min_order_value,
        is_active=body.is_active,
        created_by_user_id=current_user.id,
    )
    db.add(voucher)
    await db.commit()
    await db.refresh(voucher)
    return voucher


@router.get("/", response_model=list[VoucherResponse])
async def list_vouchers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Voucher).order_by(Voucher.created_at.desc()))
    return result.scalars().all()


@router.get("/{voucher_id}", response_model=VoucherResponse)
async def get_voucher(
    voucher_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(Voucher).where(Voucher.id == voucher_id))
    voucher = result.scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")
    return voucher


@router.put("/{voucher_id}", response_model=VoucherResponse)
async def update_voucher(
    voucher_id: UUID,
    body: VoucherUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    result = await db.execute(select(Voucher).where(Voucher.id == voucher_id))
    voucher = result.scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "code" and value is not None:
            value = value.upper().strip()
        setattr(voucher, field, value)

    await db.commit()
    await db.refresh(voucher)
    return voucher


@router.delete("/{voucher_id}")
async def delete_voucher(
    voucher_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    result = await db.execute(select(Voucher).where(Voucher.id == voucher_id))
    voucher = result.scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")
    await db.delete(voucher)
    await db.commit()
    return {"message": "deleted"}


@router.post("/validate", response_model=VoucherValidateResponse)
async def validate_voucher(
    request: Request,
    body: VoucherValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint to validate a voucher code."""
    effective_tenant_id = getattr(request.state, "tenant_id", None)

    result = await db.execute(
        select(Voucher).where(Voucher.code == body.code.upper().strip())
    )
    voucher = result.scalar_one_or_none()

    if not voucher:
        return VoucherValidateResponse(valid=False, message="Voucher not found")

    if not voucher.is_active:
        return VoucherValidateResponse(valid=False, message="Voucher is inactive")

    today = date.today()
    if voucher.valid_from and today < voucher.valid_from:
        return VoucherValidateResponse(valid=False, message="Voucher not yet valid")
    if voucher.valid_until and today > voucher.valid_until:
        return VoucherValidateResponse(valid=False, message="Voucher expired")

    if voucher.max_uses and voucher.used_count >= voucher.max_uses:
        return VoucherValidateResponse(valid=False, message="Voucher usage limit reached")

    if body.order_value is not None and voucher.min_order_value and body.order_value < voucher.min_order_value:
        return VoucherValidateResponse(
            valid=False,
            message=f"Minimum order value of {voucher.min_order_value} EUR required",
        )

    discount_amount = voucher.value
    if voucher.type == "percentage" and body.order_value is not None:
        discount_amount = round(body.order_value * voucher.value / 100, 2)

    return VoucherValidateResponse(
        valid=True,
        voucher_id=voucher.id,
        discount_type=voucher.type,
        discount_value=voucher.value,
        discount_amount=discount_amount,
    )


@router.get("/{voucher_id}/usage", response_model=list[VoucherUsageResponse])
async def get_voucher_usage(
    voucher_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(
        select(VoucherUsage).where(VoucherUsage.voucher_id == voucher_id).order_by(VoucherUsage.used_at.desc())
    )
    return result.scalars().all()
