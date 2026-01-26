"""
Upsell Packages API - Upsell-Pakete für Reservierungen.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Restaurant, UpsellPackage
from app.dependencies import User, get_session, require_schichtleiter_role
from app.schemas import (
    UpsellPackageAvailabilityRequest,
    UpsellPackageAvailabilityResponse,
    UpsellPackageCreate,
    UpsellPackageRead,
    UpsellPackageUpdate,
)

router = APIRouter(prefix="/restaurants/{restaurant_id}/upsell-packages", tags=["upsell-packages"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    """Lädt Restaurant oder wirft 404."""
    result = await session.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_package_or_404(
    package_id: int, restaurant_id: int, session: AsyncSession
) -> UpsellPackage:
    """Lädt Upsell-Paket oder wirft 404."""
    result = await session.execute(
        select(UpsellPackage).where(
            UpsellPackage.id == package_id, UpsellPackage.restaurant_id == restaurant_id
        )
    )
    package = result.scalar_one_or_none()
    if not package:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Upsell package not found"
        )
    return package


def _is_package_available(
    package: UpsellPackage, request_date: date, request_time: str, party_size: int
) -> bool:
    """Prüft ob ein Paket für die gegebene Reservierung verfügbar ist."""
    # Prüfe Aktivität
    if not package.is_active:
        return False

    # Prüfe Datumsbereich
    today = date.today()
    if package.available_from_date and request_date < package.available_from_date:
        return False
    if package.available_until_date and request_date > package.available_until_date:
        return False

    # Prüfe Gästeanzahl
    if package.min_party_size and party_size < package.min_party_size:
        return False
    if package.max_party_size and party_size > package.max_party_size:
        return False

    # Prüfe Wochentag
    if package.available_weekdays:
        weekday = request_date.weekday()  # 0 = Montag, 6 = Sonntag
        if weekday not in package.available_weekdays:
            return False

    # Prüfe Zeit
    if package.available_times:
        weekday_name = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ][request_date.weekday()]
        times_for_day = package.available_times.get(weekday_name, [])
        if times_for_day and request_time not in times_for_day:
            return False

    return True


@router.post("/", response_model=UpsellPackageRead, status_code=status.HTTP_201_CREATED)
async def create_upsell_package(
    restaurant_id: int,
    package_data: UpsellPackageCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Erstellt ein neues Upsell-Paket."""
    restaurant = await _get_restaurant_or_404(restaurant_id, session)

    package = UpsellPackage(
        restaurant_id=restaurant_id,
        name=package_data.name,
        description=package_data.description,
        price=package_data.price,
        is_active=package_data.is_active,
        available_from_date=package_data.available_from_date,
        available_until_date=package_data.available_until_date,
        min_party_size=package_data.min_party_size,
        max_party_size=package_data.max_party_size,
        available_times=package_data.available_times,
        available_weekdays=package_data.available_weekdays,
        image_url=package_data.image_url,
        display_order=package_data.display_order,
    )

    session.add(package)
    await session.commit()
    await session.refresh(package)

    return package


@router.get("/", response_model=list[UpsellPackageRead])
async def list_upsell_packages(
    restaurant_id: int,
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Listet alle Upsell-Pakete eines Restaurants."""
    await _get_restaurant_or_404(restaurant_id, session)

    query = select(UpsellPackage).where(UpsellPackage.restaurant_id == restaurant_id)
    if not include_inactive:
        query = query.where(UpsellPackage.is_active == True)

    query = query.order_by(UpsellPackage.display_order.asc(), UpsellPackage.created_at_utc.desc())

    result = await session.execute(query)
    packages = result.scalars().all()

    return packages


@router.get("/{package_id}", response_model=UpsellPackageRead)
async def get_upsell_package(
    restaurant_id: int,
    package_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Holt ein Upsell-Paket."""
    return await _get_package_or_404(package_id, restaurant_id, session)


@router.put("/{package_id}", response_model=UpsellPackageRead)
async def update_upsell_package(
    restaurant_id: int,
    package_id: int,
    package_data: UpsellPackageUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Aktualisiert ein Upsell-Paket."""
    package = await _get_package_or_404(package_id, restaurant_id, session)

    update_data = package_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(package, field, value)

    await session.commit()
    await session.refresh(package)

    return package


@router.delete("/{package_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upsell_package(
    restaurant_id: int,
    package_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Löscht ein Upsell-Paket."""
    package = await _get_package_or_404(package_id, restaurant_id, session)

    await session.delete(package)
    await session.commit()

    return None


@router.post("/availability", response_model=UpsellPackageAvailabilityResponse)
async def get_available_packages(
    restaurant_id: int,
    availability_data: UpsellPackageAvailabilityRequest,
    session: AsyncSession = Depends(get_session),
):
    """Gibt verfügbare Upsell-Pakete für eine Reservierung zurück (öffentlicher Endpoint)."""
    await _get_restaurant_or_404(restaurant_id, session)

    # Lade alle aktiven Pakete
    result = await session.execute(
        select(UpsellPackage)
        .where(UpsellPackage.restaurant_id == restaurant_id, UpsellPackage.is_active == True)
        .order_by(UpsellPackage.display_order.asc())
    )
    all_packages = result.scalars().all()

    # Filtere nach Verfügbarkeit
    available_packages = [
        package
        for package in all_packages
        if _is_package_available(
            package, availability_data.date, availability_data.time, availability_data.party_size
        )
    ]

    return UpsellPackageAvailabilityResponse(
        packages=[UpsellPackageRead.model_validate(p) for p in available_packages]
    )
