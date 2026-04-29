from __future__ import annotations

import re
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
ALLOWED_OFFER_KINDS = {"discount", "voucher"}
ALLOWED_OFFER_SCOPES = {"public", "individual"}
UUID_IN_TEXT_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


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
    kind: str = "discount"
    scope: str = "public"
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

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_OFFER_KINDS:
            raise ValueError("kind must be 'discount' or 'voucher'")
        return normalized

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_OFFER_SCOPES:
            raise ValueError("scope must be 'public' or 'individual'")
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
        if self.kind == "voucher" and self.type == "percentage":
            raise ValueError("voucher kind only supports fixed EUR values")
        if self.scope == "individual" and not _extract_uuid_from_text(self.code):
            raise ValueError(
                "individual offers require a code containing a UUID"
            )

        if (self.valid_time_from is None) != (self.valid_time_until is None):
            raise ValueError("valid_time_from and valid_time_until must both be set or both be null")

        if self.valid_time_from and self.valid_time_until and self.valid_time_until <= self.valid_time_from:
            raise ValueError("valid_time_until must be later than valid_time_from")

        return self


class VoucherUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    description: str | None = None
    kind: str | None = None
    scope: str | None = None
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

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in ALLOWED_OFFER_KINDS:
            raise ValueError("kind must be 'discount' or 'voucher'")
        return normalized

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in ALLOWED_OFFER_SCOPES:
            raise ValueError("scope must be 'public' or 'individual'")
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
        if self.kind == "voucher" and self.type == "percentage":
            raise ValueError("voucher kind only supports fixed EUR values")

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
    kind: str = "discount"
    scope: str = "public"
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
    remaining_value: float | None = None
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
    voucher_kind: str | None = None
    voucher_scope: str | None = None
    discount_value: float | None = None
    discount_amount: float | None = None
    remaining_value: float | None = None
    message: str | None = None


class VoucherRedeemRequest(BaseModel):
    code: str
    order_value: float | None = None
    service_type: str | None = None
    order_timestamp: datetime | None = None
    reservation_id: UUID | None = None
    used_by_email: str | None = None

    @field_validator("service_type")
    @classmethod
    def validate_service_type(cls, value: str | None) -> str | None:
        normalized = _normalize_service_type(value)
        if normalized is None:
            return None
        if normalized not in ALLOWED_SERVICE_TYPES:
            raise ValueError("service_type must be one of: all, breakfast, lunch, dinner")
        return normalized


class VoucherRedeemResponse(BaseModel):
    redeemed: bool
    voucher_id: UUID | None = None
    voucher_kind: str | None = None
    voucher_scope: str | None = None
    discount_type: str | None = None
    discount_value: float | None = None
    discount_amount: float | None = None
    used_count: int | None = None
    max_uses: int | None = None
    remaining_value: float | None = None
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


def _normalize_voucher_kind(kind: str | None) -> str:
    normalized = (kind or "").strip().lower()
    if normalized in ALLOWED_OFFER_KINDS:
        return normalized
    return "discount"


def _normalize_offer_scope(scope: str | None) -> str:
    normalized = (scope or "").strip().lower()
    if normalized in ALLOWED_OFFER_SCOPES:
        return normalized
    return "public"


def _extract_uuid_from_text(value: str | None) -> UUID | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        match = UUID_IN_TEXT_PATTERN.search(raw)
        if not match:
            return None
        try:
            return UUID(match.group(0))
        except ValueError:
            return None


def _resolve_effective_max_uses(kind: str, scope: str, max_uses: int | None) -> int | None:
    if scope == "individual" and max_uses is None:
        return 1
    return max_uses


def _resolve_voucher_remaining_value(voucher: Voucher) -> float | None:
    if _normalize_voucher_kind(voucher.kind) != "voucher":
        return None
    if voucher.remaining_value is None:
        return float(voucher.value)
    return max(0.0, float(voucher.remaining_value))


def _evaluate_voucher_for_context(
    voucher: Voucher,
    order_value: float | None,
    service_type: str | None,
    now_ref: datetime,
) -> tuple[bool, str | None, float | None]:
    normalized_kind = _normalize_voucher_kind(voucher.kind)
    if not voucher.is_active:
        return False, "Voucher is inactive", None

    today = now_ref.date()
    if voucher.valid_from and today < voucher.valid_from:
        return False, "Voucher not yet valid", None
    if voucher.valid_until and today > voucher.valid_until:
        return False, "Voucher expired", None

    remaining_value = _resolve_voucher_remaining_value(voucher)
    if normalized_kind == "voucher" and (remaining_value is None or remaining_value <= 0):
        return False, "Voucher balance exhausted", None

    if (
        normalized_kind != "voucher"
        and voucher.max_uses
        and voucher.used_count >= voucher.max_uses
    ):
        return False, "Voucher usage limit reached", None

    if order_value is not None and voucher.min_order_value and order_value < voucher.min_order_value:
        return (
            False,
            f"Minimum order value of {voucher.min_order_value} EUR required",
            None,
        )

    requested_service_type = _normalize_service_type(service_type)
    if voucher.applies_to != "all":
        if not requested_service_type:
            return False, "Voucher requires service_type context", None
        if requested_service_type != voucher.applies_to:
            return False, f"Voucher only valid for {voucher.applies_to}", None

    current_weekday = now_ref.weekday()
    if voucher.valid_weekdays and current_weekday not in voucher.valid_weekdays:
        return False, "Voucher is not valid on this weekday", None

    current_time = now_ref.time().replace(tzinfo=None)
    if voucher.valid_time_from and current_time < voucher.valid_time_from:
        return False, "Voucher is not yet valid at this time", None
    if voucher.valid_time_until and current_time > voucher.valid_time_until:
        return False, "Voucher has expired for this time window", None

    discount_amount = voucher.value
    if voucher.type == "percentage" and order_value is not None:
        discount_amount = round(order_value * voucher.value / 100, 2)
    elif voucher.type == "fixed" and order_value is not None:
        if normalized_kind == "voucher" and remaining_value is not None:
            discount_amount = min(order_value, remaining_value)
        else:
            discount_amount = min(order_value, voucher.value)

    return True, None, discount_amount


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
    normalized_kind = _normalize_voucher_kind(body.kind)
    normalized_scope = _normalize_offer_scope(body.scope)
    voucher = Voucher(
        tenant_id=effective_tenant_id,
        code=body.code.upper().strip(),
        name=body.name,
        description=body.description,
        kind=normalized_kind,
        scope=normalized_scope,
        type=body.type,
        value=body.value,
        applies_to=body.applies_to,
        valid_weekdays=body.valid_weekdays,
        valid_time_from=body.valid_time_from,
        valid_time_until=body.valid_time_until,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        max_uses=_resolve_effective_max_uses(normalized_kind, normalized_scope, body.max_uses),
        remaining_value=body.value if normalized_kind == "voucher" else None,
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


@router.get("/{voucher_id:uuid}", response_model=VoucherResponse)
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


@router.put("/{voucher_id:uuid}", response_model=VoucherResponse)
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

    previous_kind = _normalize_voucher_kind(voucher.kind)
    previous_value = float(voucher.value)
    previous_remaining_value = _resolve_voucher_remaining_value(voucher)
    payload = body.model_dump(exclude_unset=True)
    if "kind" in payload and payload["kind"] is not None:
        payload["kind"] = _normalize_voucher_kind(payload["kind"])
    if "scope" in payload and payload["scope"] is not None:
        payload["scope"] = _normalize_offer_scope(payload["scope"])
    effective_kind = _normalize_voucher_kind(payload.get("kind") or voucher.kind)
    effective_scope = _normalize_offer_scope(payload.get("scope") or voucher.scope)
    effective_type = payload.get("type") or voucher.type
    effective_code = payload.get("code") or voucher.code
    if effective_kind == "voucher":
        if effective_type == "percentage":
            raise HTTPException(
                status_code=422,
                detail="voucher kind only supports fixed EUR values",
            )
    if effective_scope == "individual":
        if "max_uses" not in payload or payload.get("max_uses") is None:
            payload["max_uses"] = _resolve_effective_max_uses(
                effective_kind,
                effective_scope,
                voucher.max_uses,
            )
    if effective_scope == "individual" and not _extract_uuid_from_text(effective_code):
        raise HTTPException(
            status_code=422,
            detail="individual offers require a code containing a UUID",
        )
    for field, value in payload.items():
        if field == "code" and value is not None:
            value = value.upper().strip()
        setattr(voucher, field, value)

    if _normalize_voucher_kind(voucher.kind) == "voucher":
        if previous_kind != "voucher":
            voucher.remaining_value = float(voucher.value)
        elif "value" in payload:
            consumed_amount = max(0.0, previous_value - (previous_remaining_value or 0.0))
            voucher.remaining_value = max(0.0, round(float(voucher.value) - consumed_amount, 2))
        elif voucher.remaining_value is None:
            voucher.remaining_value = float(voucher.value)
        if voucher.remaining_value > float(voucher.value):
            voucher.remaining_value = float(voucher.value)
    else:
        voucher.remaining_value = None

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Voucher code already exists for this restaurant")
    await db.refresh(voucher)
    return voucher


@router.delete("/{voucher_id:uuid}")
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

    now_ref = body.order_timestamp or datetime.now()
    is_valid, message, discount_amount = _evaluate_voucher_for_context(
        voucher=voucher,
        order_value=body.order_value,
        service_type=body.service_type,
        now_ref=now_ref,
    )
    if not is_valid:
        return VoucherValidateResponse(valid=False, message=message)

    return VoucherValidateResponse(
        valid=True,
        voucher_id=voucher.id,
        voucher_kind=_normalize_voucher_kind(voucher.kind),
        voucher_scope=_normalize_offer_scope(voucher.scope),
        discount_type=voucher.type,
        discount_value=voucher.value,
        discount_amount=discount_amount,
        remaining_value=_resolve_voucher_remaining_value(voucher),
    )


@router.post("/redeem", response_model=VoucherRedeemResponse)
async def redeem_voucher(
    request: Request,
    body: VoucherRedeemRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_voucher(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=None,
    )

    code = body.code.upper().strip()
    result = await db.execute(
        select(Voucher)
        .where(
            and_(
                Voucher.tenant_id == effective_tenant_id,
                Voucher.code == code,
            )
        )
        .with_for_update()
    )
    voucher = result.scalar_one_or_none()
    if not voucher:
        return VoucherRedeemResponse(redeemed=False, message="Voucher not found")

    now_ref = body.order_timestamp or datetime.now()
    is_valid, message, discount_amount = _evaluate_voucher_for_context(
        voucher=voucher,
        order_value=body.order_value,
        service_type=body.service_type,
        now_ref=now_ref,
    )
    if not is_valid or discount_amount is None:
        return VoucherRedeemResponse(redeemed=False, message=message or "Voucher is not redeemable")

    normalized_kind = _normalize_voucher_kind(voucher.kind)
    voucher.used_count += 1
    if normalized_kind == "voucher":
        remaining_before = _resolve_voucher_remaining_value(voucher) or 0.0
        remaining_after = max(0.0, round(remaining_before - float(discount_amount), 2))
        voucher.remaining_value = remaining_after
        if remaining_after <= 0:
            voucher.is_active = False
    elif voucher.max_uses and voucher.used_count >= voucher.max_uses:
        voucher.is_active = False
    usage = VoucherUsage(
        voucher_id=voucher.id,
        reservation_id=body.reservation_id,
        tenant_id=effective_tenant_id,
        used_by_email=body.used_by_email or current_user.email,
        discount_amount=discount_amount,
    )
    db.add(usage)
    await db.commit()
    await db.refresh(voucher)

    return VoucherRedeemResponse(
        redeemed=True,
        voucher_id=voucher.id,
        voucher_kind=_normalize_voucher_kind(voucher.kind),
        voucher_scope=_normalize_offer_scope(voucher.scope),
        discount_type=voucher.type,
        discount_value=voucher.value,
        discount_amount=discount_amount,
        used_count=voucher.used_count,
        max_uses=voucher.max_uses,
        remaining_value=_resolve_voucher_remaining_value(voucher),
        message="Voucher redeemed",
    )


@router.get("/{voucher_id:uuid}/usage", response_model=list[VoucherUsageResponse])
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
