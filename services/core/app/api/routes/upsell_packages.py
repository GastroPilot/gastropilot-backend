from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_manager_or_above, require_staff_or_above
from app.models.upsell import UpsellPackage
from app.models.user import User

router = APIRouter(prefix="/upsell-packages", tags=["upsell-packages"])


class UpsellPackageCreate(BaseModel):
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
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class AvailabilityRequest(BaseModel):
    date: date
    party_size: int
    time: str | None = None


@router.post("/", response_model=UpsellPackageResponse, status_code=status.HTTP_201_CREATED)
async def create_package(
    request: Request,
    body: UpsellPackageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
    package = UpsellPackage(tenant_id=effective_tenant_id, **body.model_dump())
    db.add(package)
    await db.commit()
    await db.refresh(package)
    return package


@router.get("/", response_model=list[UpsellPackageResponse])
async def list_packages(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(UpsellPackage).order_by(UpsellPackage.display_order))
    return result.scalars().all()


@router.get("/{package_id}", response_model=UpsellPackageResponse)
async def get_package(
    package_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(UpsellPackage).where(UpsellPackage.id == package_id))
    package = result.scalar_one_or_none()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    return package


@router.put("/{package_id}", response_model=UpsellPackageResponse)
async def update_package(
    package_id: UUID,
    body: UpsellPackageUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    result = await db.execute(select(UpsellPackage).where(UpsellPackage.id == package_id))
    package = result.scalar_one_or_none()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(package, field, value)

    await db.commit()
    await db.refresh(package)
    return package


@router.delete("/{package_id}")
async def delete_package(
    package_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    result = await db.execute(select(UpsellPackage).where(UpsellPackage.id == package_id))
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
):
    """Public endpoint: returns available upsell packages for given date/party."""
    result = await db.execute(
        select(UpsellPackage)
        .where(UpsellPackage.is_active.is_(True))
        .order_by(UpsellPackage.display_order)
    )
    packages = result.scalars().all()

    available = []
    weekday = body.date.weekday()

    for pkg in packages:
        if pkg.available_from_date and body.date < pkg.available_from_date:
            continue
        if pkg.available_until_date and body.date > pkg.available_until_date:
            continue
        if pkg.min_party_size and body.party_size < pkg.min_party_size:
            continue
        if pkg.max_party_size and body.party_size > pkg.max_party_size:
            continue
        if pkg.available_weekdays and weekday not in pkg.available_weekdays:
            continue
        if body.time and pkg.available_times:
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
