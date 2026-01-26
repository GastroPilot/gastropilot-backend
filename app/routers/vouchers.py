"""
Voucher API - Gutschein-Verwaltung.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Restaurant, Voucher
from app.dependencies import User, get_session, require_schichtleiter_role
from app.schemas import (
    VoucherCreate,
    VoucherRead,
    VoucherUpdate,
    VoucherValidateRequest,
    VoucherValidateResponse,
)

router = APIRouter(prefix="/restaurants/{restaurant_id}/vouchers", tags=["vouchers"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    """Lädt Restaurant oder wirft 404."""
    result = await session.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_voucher_or_404(
    voucher_id: int, restaurant_id: int, session: AsyncSession
) -> Voucher:
    """Lädt Voucher oder wirft 404."""
    result = await session.execute(
        select(Voucher).where(Voucher.id == voucher_id, Voucher.restaurant_id == restaurant_id)
    )
    voucher = result.scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voucher not found")
    return voucher


def _calculate_discount(voucher: Voucher, reservation_amount: float) -> float:
    """Berechnet den Rabattbetrag basierend auf Gutschein-Typ."""
    if voucher.type == "fixed":
        # Fester Betrag, aber nicht mehr als der Reservierungsbetrag
        return min(voucher.value, reservation_amount)
    elif voucher.type == "percentage":
        # Prozentualer Rabatt
        discount = reservation_amount * (voucher.value / 100)
        return min(discount, reservation_amount)
    return 0.0


@router.post("/", response_model=VoucherRead, status_code=status.HTTP_201_CREATED)
async def create_voucher(
    restaurant_id: int,
    voucher_data: VoucherCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Erstellt einen neuen Gutschein."""
    restaurant = await _get_restaurant_or_404(restaurant_id, session)

    # Prüfe ob Code bereits existiert
    result = await session.execute(select(Voucher).where(Voucher.code == voucher_data.code.upper()))
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ein Gutschein mit diesem Code existiert bereits",
        )

    voucher = Voucher(
        restaurant_id=restaurant_id,
        code=voucher_data.code.upper(),  # Immer Großbuchstaben
        name=voucher_data.name,
        description=voucher_data.description,
        type=voucher_data.type,
        value=voucher_data.value,
        valid_from=voucher_data.valid_from,
        valid_until=voucher_data.valid_until,
        max_uses=voucher_data.max_uses,
        min_order_value=voucher_data.min_order_value,
        is_active=voucher_data.is_active,
        created_by_user_id=current_user.id,
    )

    session.add(voucher)
    await session.commit()
    await session.refresh(voucher)

    return voucher


@router.get("/", response_model=list[VoucherRead])
async def list_vouchers(
    restaurant_id: int,
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Listet alle Gutscheine eines Restaurants."""
    await _get_restaurant_or_404(restaurant_id, session)

    query = select(Voucher).where(Voucher.restaurant_id == restaurant_id)
    if not include_inactive:
        query = query.where(Voucher.is_active == True)

    query = query.order_by(Voucher.created_at_utc.desc())

    result = await session.execute(query)
    vouchers = result.scalars().all()

    return vouchers


@router.get("/{voucher_id}", response_model=VoucherRead)
async def get_voucher(
    restaurant_id: int,
    voucher_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Holt einen Gutschein."""
    return await _get_voucher_or_404(voucher_id, restaurant_id, session)


@router.put("/{voucher_id}", response_model=VoucherRead)
async def update_voucher(
    restaurant_id: int,
    voucher_id: int,
    voucher_data: VoucherUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Aktualisiert einen Gutschein."""
    voucher = await _get_voucher_or_404(voucher_id, restaurant_id, session)

    update_data = voucher_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(voucher, field, value)

    await session.commit()
    await session.refresh(voucher)

    return voucher


@router.delete("/{voucher_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voucher(
    restaurant_id: int,
    voucher_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Löscht einen Gutschein."""
    voucher = await _get_voucher_or_404(voucher_id, restaurant_id, session)

    await session.delete(voucher)
    await session.commit()

    return None


@router.post("/validate", response_model=VoucherValidateResponse)
async def validate_voucher(
    restaurant_id: int,
    validation_data: VoucherValidateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Validiert einen Gutschein-Code (öffentlicher Endpoint)."""
    await _get_restaurant_or_404(restaurant_id, session)

    # Suche Gutschein
    result = await session.execute(
        select(Voucher).where(
            Voucher.code == validation_data.code.upper(), Voucher.restaurant_id == restaurant_id
        )
    )
    voucher = result.scalar_one_or_none()

    if not voucher:
        return VoucherValidateResponse(valid=False, message="Gutschein-Code nicht gefunden")

    # Prüfe Aktivität
    if not voucher.is_active:
        return VoucherValidateResponse(valid=False, message="Dieser Gutschein ist nicht mehr aktiv")

    # Prüfe Gültigkeitszeitraum
    today = date.today()
    if voucher.valid_from and today < voucher.valid_from:
        return VoucherValidateResponse(
            valid=False,
            message=f"Dieser Gutschein ist erst ab {voucher.valid_from.strftime('%d.%m.%Y')} gültig",
        )

    if voucher.valid_until and today > voucher.valid_until:
        return VoucherValidateResponse(
            valid=False,
            message=f"Dieser Gutschein ist abgelaufen (gültig bis {voucher.valid_until.strftime('%d.%m.%Y')})",
        )

    # Prüfe maximale Nutzungen
    if voucher.max_uses and voucher.used_count >= voucher.max_uses:
        return VoucherValidateResponse(
            valid=False, message="Dieser Gutschein wurde bereits zu oft verwendet"
        )

    # Prüfe Mindestbestellwert
    if voucher.min_order_value and validation_data.reservation_amount:
        if validation_data.reservation_amount < voucher.min_order_value:
            return VoucherValidateResponse(
                valid=False,
                message=f"Mindestbestellwert von {voucher.min_order_value:.2f} € nicht erreicht",
            )

    # Berechne Rabattbetrag
    reservation_amount = validation_data.reservation_amount or 0.0
    discount_amount = _calculate_discount(voucher, reservation_amount)

    return VoucherValidateResponse(
        valid=True,
        voucher=VoucherRead.model_validate(voucher),
        discount_amount=discount_amount,
        message="Gutschein ist gültig",
    )
