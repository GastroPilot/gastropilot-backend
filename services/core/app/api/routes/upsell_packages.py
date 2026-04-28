from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_manager_or_above, require_staff_or_above
from app.models.restaurant import Restaurant
from app.models.upsell import UpsellPackage
from app.models.user import User

router = APIRouter(prefix="/upsell-packages", tags=["upsell-packages"])

ALLOWED_PACKAGE_TYPES = {"addon", "bundle_deal"}
ALLOWED_PRICING_MODES = {"fixed_price", "fixed_discount", "percentage_discount"}
ALLOWED_SERVICE_PERIODS = {"all", "breakfast", "lunch", "dinner"}


class ComponentRule(BaseModel):
    key: str
    label: str
    required: bool = True
    quantity: int = Field(default=1, ge=1)
    category_ids: list[str] | None = None
    item_ids: list[str] | None = None
    surcharge_allowed: bool = False

    @field_validator("key", "label")
    @classmethod
    def validate_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned


class UpsellPackageCreate(BaseModel):
    restaurant_id: UUID | None = None
    name: str
    description: str | None = None
    price: float
    is_active: bool = True
    available_from_date: date | None = None
    available_until_date: date | None = None
    min_party_size: int | None = None
    max_party_size: int | None = None
    available_times: dict | None = None
    available_weekdays: list[int] | None = None
    image_url: str | None = None
    display_order: int = 0

    package_type: str = "addon"
    pricing_mode: str = "fixed_price"
    service_period: str = "all"
    valid_time_from: time | None = None
    valid_time_until: time | None = None
    component_rules: list[ComponentRule] | None = None
    allow_main_item_surcharge: bool = False
    main_item_base_price: float | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be empty")
        return cleaned

    @field_validator("package_type")
    @classmethod
    def validate_package_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_PACKAGE_TYPES:
            raise ValueError("package_type must be 'addon' or 'bundle_deal'")
        return normalized

    @field_validator("pricing_mode")
    @classmethod
    def validate_pricing_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_PRICING_MODES:
            raise ValueError(
                "pricing_mode must be 'fixed_price', 'fixed_discount' or 'percentage_discount'"
            )
        return normalized

    @field_validator("service_period")
    @classmethod
    def validate_service_period(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_SERVICE_PERIODS:
            raise ValueError("service_period must be one of: all, breakfast, lunch, dinner")
        return normalized

    @field_validator("available_weekdays")
    @classmethod
    def validate_available_weekdays(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        normalized = sorted(set(value))
        for day in normalized:
            if day < 0 or day > 6:
                raise ValueError("available_weekdays must only contain numbers from 0 (Mon) to 6 (Sun)")
        return normalized


class UpsellPackageUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: float | None = None
    is_active: bool | None = None
    available_from_date: date | None = None
    available_until_date: date | None = None
    min_party_size: int | None = None
    max_party_size: int | None = None
    available_times: dict | None = None
    available_weekdays: list[int] | None = None
    image_url: str | None = None
    display_order: int | None = None

    package_type: str | None = None
    pricing_mode: str | None = None
    service_period: str | None = None
    valid_time_from: time | None = None
    valid_time_until: time | None = None
    component_rules: list[ComponentRule] | None = None
    allow_main_item_surcharge: bool | None = None
    main_item_base_price: float | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be empty")
        return cleaned

    @field_validator("package_type")
    @classmethod
    def validate_package_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in ALLOWED_PACKAGE_TYPES:
            raise ValueError("package_type must be 'addon' or 'bundle_deal'")
        return normalized

    @field_validator("pricing_mode")
    @classmethod
    def validate_pricing_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in ALLOWED_PRICING_MODES:
            raise ValueError(
                "pricing_mode must be 'fixed_price', 'fixed_discount' or 'percentage_discount'"
            )
        return normalized

    @field_validator("service_period")
    @classmethod
    def validate_service_period(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in ALLOWED_SERVICE_PERIODS:
            raise ValueError("service_period must be one of: all, breakfast, lunch, dinner")
        return normalized

    @field_validator("available_weekdays")
    @classmethod
    def validate_available_weekdays(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        normalized = sorted(set(value))
        for day in normalized:
            if day < 0 or day > 6:
                raise ValueError("available_weekdays must only contain numbers from 0 (Mon) to 6 (Sun)")
        return normalized


class UpsellPackageResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None = None
    price: float
    is_active: bool
    available_from_date: date | None = None
    available_until_date: date | None = None
    min_party_size: int | None = None
    max_party_size: int | None = None
    available_times: dict | None = None
    available_weekdays: list[int] | None = None
    image_url: str | None = None
    display_order: int

    package_type: str
    pricing_mode: str
    service_period: str
    valid_time_from: time | None = None
    valid_time_until: time | None = None
    component_rules: list[ComponentRule] | None = None
    allow_main_item_surcharge: bool
    main_item_base_price: float | None = None

    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class AvailabilityRequest(BaseModel):
    restaurant_id: UUID | None = None
    date: date
    party_size: int
    time: str | None = None
    service_period: str | None = None

    @field_validator("service_period")
    @classmethod
    def validate_service_period(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in ALLOWED_SERVICE_PERIODS:
            raise ValueError("service_period must be one of: all, breakfast, lunch, dinner")
        return normalized


def _parse_time(value: str | None) -> time | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="time must match HH:MM format") from exc


def _normalize_weekdays(value: list | None) -> set[int]:
    if not value:
        return set()
    normalized: set[int] = set()
    for raw_day in value:
        try:
            day = int(raw_day)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6:
            normalized.add(day)
    return normalized


def _validate_component_rules(component_rules: list[ComponentRule] | None) -> None:
    if component_rules is None:
        return

    keys_seen: set[str] = set()
    for rule in component_rules:
        if rule.key in keys_seen:
            raise HTTPException(status_code=422, detail=f"Duplicate component key: {rule.key}")
        keys_seen.add(rule.key)

        if (not rule.category_ids) and (not rule.item_ids):
            raise HTTPException(
                status_code=422,
                detail=f"Component '{rule.key}' must define category_ids or item_ids",
            )


def _assert_package_config(
    *,
    package_type: str,
    pricing_mode: str,
    price: float,
    available_from_date: date | None,
    available_until_date: date | None,
    min_party_size: int | None,
    max_party_size: int | None,
    valid_time_from: time | None,
    valid_time_until: time | None,
    allow_main_item_surcharge: bool,
    main_item_base_price: float | None,
    component_rules: list[ComponentRule] | None,
) -> None:
    if price <= 0:
        raise HTTPException(status_code=422, detail="price must be > 0")

    if pricing_mode == "percentage_discount" and price > 100:
        raise HTTPException(status_code=422, detail="percentage discount must be <= 100")

    if available_from_date and available_until_date and available_until_date < available_from_date:
        raise HTTPException(
            status_code=422,
            detail="available_until_date must be on or after available_from_date",
        )

    if min_party_size is not None and min_party_size < 1:
        raise HTTPException(status_code=422, detail="min_party_size must be >= 1")

    if max_party_size is not None and max_party_size < 1:
        raise HTTPException(status_code=422, detail="max_party_size must be >= 1")

    if (
        min_party_size is not None
        and max_party_size is not None
        and max_party_size < min_party_size
    ):
        raise HTTPException(
            status_code=422,
            detail="max_party_size must be >= min_party_size",
        )

    if (valid_time_from is None) != (valid_time_until is None):
        raise HTTPException(
            status_code=422,
            detail="valid_time_from and valid_time_until must both be set or both be null",
        )

    if valid_time_from and valid_time_until and valid_time_until <= valid_time_from:
        raise HTTPException(
            status_code=422,
            detail="valid_time_until must be later than valid_time_from",
        )

    if allow_main_item_surcharge:
        if main_item_base_price is None:
            raise HTTPException(
                status_code=422,
                detail="main_item_base_price is required when allow_main_item_surcharge is enabled",
            )
        if main_item_base_price < 0:
            raise HTTPException(
                status_code=422,
                detail="main_item_base_price must be >= 0",
            )

    if package_type == "bundle_deal" and not component_rules:
        raise HTTPException(
            status_code=422,
            detail="bundle_deal requires at least one component rule",
        )


async def _resolve_tenant_context_for_upsell(
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


@router.post("", response_model=UpsellPackageResponse, status_code=status.HTTP_201_CREATED)
async def create_package(
    request: Request,
    body: UpsellPackageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_upsell(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=body.restaurant_id,
    )

    _validate_component_rules(body.component_rules)
    _assert_package_config(
        package_type=body.package_type,
        pricing_mode=body.pricing_mode,
        price=body.price,
        available_from_date=body.available_from_date,
        available_until_date=body.available_until_date,
        min_party_size=body.min_party_size,
        max_party_size=body.max_party_size,
        valid_time_from=body.valid_time_from,
        valid_time_until=body.valid_time_until,
        allow_main_item_surcharge=body.allow_main_item_surcharge,
        main_item_base_price=body.main_item_base_price,
        component_rules=body.component_rules,
    )

    package = UpsellPackage(
        tenant_id=effective_tenant_id,
        name=body.name,
        description=body.description,
        price=body.price,
        is_active=body.is_active,
        available_from_date=body.available_from_date,
        available_until_date=body.available_until_date,
        min_party_size=body.min_party_size,
        max_party_size=body.max_party_size,
        available_times=body.available_times,
        available_weekdays=body.available_weekdays,
        image_url=body.image_url,
        display_order=body.display_order,
        package_type=body.package_type,
        pricing_mode=body.pricing_mode,
        service_period=body.service_period,
        valid_time_from=body.valid_time_from,
        valid_time_until=body.valid_time_until,
        component_rules=[rule.model_dump(mode="json") for rule in body.component_rules]
        if body.component_rules
        else None,
        allow_main_item_surcharge=body.allow_main_item_surcharge,
        main_item_base_price=body.main_item_base_price,
    )
    db.add(package)
    await db.commit()
    await db.refresh(package)
    return package


@router.get("", response_model=list[UpsellPackageResponse])
async def list_packages(
    request: Request,
    restaurant_id: UUID | None = None,
    package_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_upsell(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
    )
    query = select(UpsellPackage).where(UpsellPackage.tenant_id == effective_tenant_id)
    if package_type:
        normalized_type = package_type.strip().lower()
        if normalized_type not in ALLOWED_PACKAGE_TYPES:
            raise HTTPException(status_code=422, detail="Invalid package_type")
        query = query.where(UpsellPackage.package_type == normalized_type)

    query = query.order_by(UpsellPackage.display_order, UpsellPackage.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{package_id}", response_model=UpsellPackageResponse)
async def get_package(
    request: Request,
    package_id: UUID,
    restaurant_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_upsell(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
    )
    result = await db.execute(
        select(UpsellPackage).where(
            UpsellPackage.id == package_id,
            UpsellPackage.tenant_id == effective_tenant_id,
        )
    )
    package = result.scalar_one_or_none()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    return package


@router.put("/{package_id}", response_model=UpsellPackageResponse)
async def update_package(
    request: Request,
    package_id: UUID,
    body: UpsellPackageUpdate,
    restaurant_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_upsell(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
    )
    result = await db.execute(
        select(UpsellPackage).where(
            UpsellPackage.id == package_id,
            UpsellPackage.tenant_id == effective_tenant_id,
        )
    )
    package = result.scalar_one_or_none()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")

    payload = body.model_dump(exclude_unset=True)
    if "component_rules" in payload and payload["component_rules"] is not None:
        component_rules = [ComponentRule.model_validate(rule) for rule in payload["component_rules"]]
        _validate_component_rules(component_rules)
        payload["component_rules"] = [rule.model_dump(mode="json") for rule in component_rules]

    for field, value in payload.items():
        setattr(package, field, value)

    _assert_package_config(
        package_type=package.package_type,
        pricing_mode=package.pricing_mode,
        price=package.price,
        available_from_date=package.available_from_date,
        available_until_date=package.available_until_date,
        min_party_size=package.min_party_size,
        max_party_size=package.max_party_size,
        valid_time_from=package.valid_time_from,
        valid_time_until=package.valid_time_until,
        allow_main_item_surcharge=package.allow_main_item_surcharge,
        main_item_base_price=package.main_item_base_price,
        component_rules=[ComponentRule.model_validate(rule) for rule in package.component_rules]
        if package.component_rules
        else None,
    )

    await db.commit()
    await db.refresh(package)
    return package


@router.delete("/{package_id}")
async def delete_package(
    request: Request,
    package_id: UUID,
    restaurant_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_upsell(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
    )
    result = await db.execute(
        select(UpsellPackage).where(
            UpsellPackage.id == package_id,
            UpsellPackage.tenant_id == effective_tenant_id,
        )
    )
    package = result.scalar_one_or_none()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    await db.delete(package)
    await db.commit()
    return {"message": "deleted"}


@router.post("/availability", response_model=list[UpsellPackageResponse])
async def check_availability(
    request: Request,
    body: AvailabilityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_upsell(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=body.restaurant_id,
    )
    result = await db.execute(
        select(UpsellPackage)
        .where(
            UpsellPackage.tenant_id == effective_tenant_id,
            UpsellPackage.is_active.is_(True),
        )
        .order_by(UpsellPackage.display_order)
    )
    packages = result.scalars().all()

    available: list[UpsellPackage] = []
    weekday = body.date.weekday()
    service_period = body.service_period
    requested_time = _parse_time(body.time)

    for pkg in packages:
        if pkg.available_from_date and body.date < pkg.available_from_date:
            continue
        if pkg.available_until_date and body.date > pkg.available_until_date:
            continue
        if pkg.min_party_size and body.party_size < pkg.min_party_size:
            continue
        if pkg.max_party_size and body.party_size > pkg.max_party_size:
            continue
        normalized_weekdays = _normalize_weekdays(pkg.available_weekdays)
        if normalized_weekdays and weekday not in normalized_weekdays:
            continue

        if service_period and pkg.service_period != "all" and pkg.service_period != service_period:
            continue

        if requested_time:
            if pkg.valid_time_from and requested_time < pkg.valid_time_from:
                continue
            if pkg.valid_time_until and requested_time > pkg.valid_time_until:
                continue

            # Legacy fallback for historical available_times payloads.
            if pkg.available_times:
                weekday_name = [
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                ][weekday]
                allowed_times = pkg.available_times.get(weekday_name, [])
                if allowed_times and body.time not in allowed_times:
                    continue

        available.append(pkg)

    return available
