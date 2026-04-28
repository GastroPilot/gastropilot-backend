from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_manager_or_above, require_staff_or_above
from app.models.restaurant import Restaurant
from app.models.user import User
from app.models.voucher import Voucher, VoucherUsage

router = APIRouter(prefix="/vouchers", tags=["vouchers"])

ALLOWED_DISCOUNT_TYPES = {"fixed", "percentage"}
ALLOWED_SERVICE_TYPES = {"all", "breakfast", "lunch", "dinner"}


def _normalize_service_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _normalize_weekdays(value: list[int] | None) -> list[int] | None:
    if value is None:
        return None
    unique_days = sorted(set(value))
    for day in unique_days:
        if day < 0 or day > 6:
            raise ValueError("valid_weekdays must only contain numbers from 0 (Mon) to 6 (Sun)")
    return unique_days


class VoucherCreate(BaseModel):
    restaurant_id: UUID | None = None
    code: str
    name: str | None = None
    description: str | None = None
    type: str = "fixed"
    value: float
    applies_to: str = "all"
    valid_weekdays: list[int] | None = None
    valid_time_from: time | None = None
    valid_time_until: time | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    max_uses: int | None = None
    min_order_value: float | None = None
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 4:
            raise ValueError("Code must have at least 4 characters")
        return cleaned

    @field_validator("type")
    @classmethod
    def validate_discount_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_DISCOUNT_TYPES:
            raise ValueError("type must be 'fixed' or 'percentage'")
        return normalized

    @field_validator("applies_to")
    @classmethod
    def validate_applies_to(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_SERVICE_TYPES:
            raise ValueError("applies_to must be one of: all, breakfast, lunch, dinner")
        return normalized

    @field_validator("valid_weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int] | None) -> list[int] | None:
        return _normalize_weekdays(value)

    @model_validator(mode="after")
    def validate_ranges(self) -> "VoucherCreate":
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must be on or after valid_from")

        if self.max_uses is not None and self.max_uses < 1:
            raise ValueError("max_uses must be >= 1")

        if self.min_order_value is not None and self.min_order_value < 0:
            raise ValueError("min_order_value must be >= 0")

        if self.value <= 0:
            raise ValueError("value must be > 0")

        if self.type == "percentage" and self.value > 100:
            raise ValueError("percentage value must be <= 100")

        if (self.valid_time_from is None) != (self.valid_time_until is None):
            raise ValueError("valid_time_from and valid_time_until must both be set or both be null")

        if self.valid_time_from and self.valid_time_until and self.valid_time_until <= self.valid_time_from:
            raise ValueError("valid_time_until must be later than valid_time_from")

        return self


class VoucherUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    description: str | None = None
    type: str | None = None
    value: float | None = None
    applies_to: str | None = None
    valid_weekdays: list[int] | None = None
    valid_time_from: time | None = None
    valid_time_until: time | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    max_uses: int | None = None
    min_order_value: float | None = None
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) < 4:
            raise ValueError("Code must have at least 4 characters")
        return cleaned

    @field_validator("type")
    @classmethod
    def validate_discount_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in ALLOWED_DISCOUNT_TYPES:
            raise ValueError("type must be 'fixed' or 'percentage'")
        return normalized

    @field_validator("applies_to")
    @classmethod
    def validate_applies_to(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in ALLOWED_SERVICE_TYPES:
            raise ValueError("applies_to must be one of: all, breakfast, lunch, dinner")
        return normalized

    @field_validator("valid_weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int] | None) -> list[int] | None:
        return _normalize_weekdays(value)

    @model_validator(mode="after")
    def validate_ranges(self) -> "VoucherUpdate":
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must be on or after valid_from")

        if self.max_uses is not None and self.max_uses < 1:
            raise ValueError("max_uses must be >= 1")

        if self.min_order_value is not None and self.min_order_value < 0:
            raise ValueError("min_order_value must be >= 0")

        if self.value is not None and self.value <= 0:
            raise ValueError("value must be > 0")

        if self.type == "percentage" and self.value is not None and self.value > 100:
            raise ValueError("percentage value must be <= 100")

        if (
            "valid_time_from" in self.model_fields_set
            or "valid_time_until" in self.model_fields_set
        ) and ((self.valid_time_from is None) != (self.valid_time_until is None)):
            raise ValueError("valid_time_from and valid_time_until must both be set or both be null")

        if self.valid_time_from and self.valid_time_until and self.valid_time_until <= self.valid_time_from:
            raise ValueError("valid_time_until must be later than valid_time_from")

        return self


class VoucherResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    code: str
    name: str | None = None
    description: str | None = None
    type: str
    value: float
    applies_to: str
    valid_weekdays: list[int] | None = None
    valid_time_from: time | None = None
    valid_time_until: time | None = None
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
    service_type: str | None = None
    order_timestamp: datetime | None = None

    @field_validator("service_type")
    @classmethod
    def validate_service_type(cls, value: str | None) -> str | None:
        normalized = _normalize_service_type(value)
        if normalized is None:
            return None
        if normalized not in ALLOWED_SERVICE_TYPES:
            raise ValueError("service_type must be one of: all, breakfast, lunch, dinner")
        return normalized


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


async def _resolve_tenant_context_for_voucher(
    request: Request,
    current_user: User,
    db: AsyncSession,
    requested_tenant_id: UUID | None,
) -> UUID:
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
    if effective_tenant_id:
        if requested_tenant_id and requested_tenant_id != effective_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Requested restaurant_id does not match tenant context",
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
        return requested_tenant_id

    raise HTTPException(
        status_code=400,
        detail=(
            "Tenant context required (token has no tenant and no restaurant tenant "
            "could be resolved)"
        ),
    )


@router.post("", response_model=VoucherResponse, status_code=status.HTTP_201_CREATED)
async def create_voucher(
    request: Request,
    body: VoucherCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_voucher(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=body.restaurant_id,
    )
    voucher = Voucher(
        tenant_id=effective_tenant_id,
        code=body.code.upper().strip(),
        name=body.name,
        description=body.description,
        type=body.type,
        value=body.value,
        applies_to=body.applies_to,
        valid_weekdays=body.valid_weekdays,
        valid_time_from=body.valid_time_from,
        valid_time_until=body.valid_time_until,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        max_uses=body.max_uses,
        min_order_value=body.min_order_value,
        is_active=body.is_active,
        created_by_user_id=current_user.id,
    )
    db.add(voucher)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Voucher code already exists for this restaurant")
    await db.refresh(voucher)
    return voucher


@router.get("", response_model=list[VoucherResponse])
async def list_vouchers(
    request: Request,
    restaurant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_voucher(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
    )
    result = await db.execute(
        select(Voucher)
        .where(Voucher.tenant_id == effective_tenant_id)
        .order_by(Voucher.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{voucher_id}", response_model=VoucherResponse)
async def get_voucher(
    voucher_id: UUID,
    request: Request,
    restaurant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_voucher(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
    )
    result = await db.execute(
        select(Voucher).where(
            and_(
                Voucher.id == voucher_id,
                Voucher.tenant_id == effective_tenant_id,
            )
        )
    )
    voucher = result.scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")
    return voucher


@router.put("/{voucher_id}", response_model=VoucherResponse)
async def update_voucher(
    voucher_id: UUID,
    request: Request,
    body: VoucherUpdate,
    restaurant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_voucher(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
    )
    result = await db.execute(
        select(Voucher).where(
            and_(
                Voucher.id == voucher_id,
                Voucher.tenant_id == effective_tenant_id,
            )
        )
    )
    voucher = result.scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "code" and value is not None:
            value = value.upper().strip()
        setattr(voucher, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Voucher code already exists for this restaurant")
    await db.refresh(voucher)
    return voucher


@router.delete("/{voucher_id}")
async def delete_voucher(
    voucher_id: UUID,
    request: Request,
    restaurant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_voucher(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
    )
    result = await db.execute(
        select(Voucher).where(
            and_(
                Voucher.id == voucher_id,
                Voucher.tenant_id == effective_tenant_id,
            )
        )
    )
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
    if not effective_tenant_id:
        return VoucherValidateResponse(valid=False, message="Tenant context missing")

    code = body.code.upper().strip()
    result = await db.execute(
        select(Voucher).where(
            and_(
                Voucher.tenant_id == effective_tenant_id,
                Voucher.code == code,
            )
        )
    )
    voucher = result.scalar_one_or_none()

    if not voucher:
        return VoucherValidateResponse(valid=False, message="Voucher not found")

    if not voucher.is_active:
        return VoucherValidateResponse(valid=False, message="Voucher is inactive")

    now_ref = body.order_timestamp or datetime.now()
    today = now_ref.date()
    if voucher.valid_from and today < voucher.valid_from:
        return VoucherValidateResponse(valid=False, message="Voucher not yet valid")
    if voucher.valid_until and today > voucher.valid_until:
        return VoucherValidateResponse(valid=False, message="Voucher expired")

    if voucher.max_uses and voucher.used_count >= voucher.max_uses:
        return VoucherValidateResponse(valid=False, message="Voucher usage limit reached")

    if (
        body.order_value is not None
        and voucher.min_order_value
        and body.order_value < voucher.min_order_value
    ):
        return VoucherValidateResponse(
            valid=False,
            message=f"Minimum order value of {voucher.min_order_value} EUR required",
        )

    requested_service_type = _normalize_service_type(body.service_type)
    if voucher.applies_to != "all":
        if not requested_service_type:
            return VoucherValidateResponse(
                valid=False,
                message="Voucher requires service_type context",
            )
        if requested_service_type != voucher.applies_to:
            return VoucherValidateResponse(
                valid=False,
                message=f"Voucher only valid for {voucher.applies_to}",
            )

    current_weekday = now_ref.weekday()
    if voucher.valid_weekdays and current_weekday not in voucher.valid_weekdays:
        return VoucherValidateResponse(valid=False, message="Voucher is not valid on this weekday")

    current_time = now_ref.time().replace(tzinfo=None)
    if voucher.valid_time_from and current_time < voucher.valid_time_from:
        return VoucherValidateResponse(valid=False, message="Voucher is not yet valid at this time")
    if voucher.valid_time_until and current_time > voucher.valid_time_until:
        return VoucherValidateResponse(valid=False, message="Voucher has expired for this time window")

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
    request: Request,
    restaurant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_voucher(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
    )
    result = await db.execute(
        select(VoucherUsage)
        .where(
            and_(
                VoucherUsage.voucher_id == voucher_id,
                VoucherUsage.tenant_id == effective_tenant_id,
            )
        )
        .order_by(VoucherUsage.used_at.desc())
    )
    return result.scalars().all()
