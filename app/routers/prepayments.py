"""
Prepayment API - Vorauszahlungen für Reservierungen.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from typing import Optional

from app.dependencies import get_session
from app.database.models import Reservation, ReservationPrepayment, Restaurant
from app.schemas import PrepaymentCreate, PrepaymentRead
from app.services.sumup_service import SumUpService
from app.settings import SUMUP_API_KEY, SUMUP_MERCHANT_CODE, SUMUP_TEST_MODE, RESERVATION_WIDGET_URL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/restaurants/{restaurant_id}/reservations/{reservation_id}/prepayment", tags=["prepayments"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    """Lädt Restaurant oder wirft 404."""
    result = await session.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_reservation_or_404(reservation_id: int, restaurant_id: int, session: AsyncSession) -> Reservation:
    """Lädt Reservierung oder wirft 404."""
    result = await session.execute(
        select(Reservation).where(
            Reservation.id == reservation_id,
            Reservation.restaurant_id == restaurant_id
        )
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    return reservation


def _get_sumup_service() -> SumUpService:
    """Erstellt einen SumUp Service."""
    if not SUMUP_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SumUp API Key nicht konfiguriert"
        )
    return SumUpService(SUMUP_API_KEY)


@router.post("/", response_model=PrepaymentRead, status_code=status.HTTP_201_CREATED)
async def create_prepayment(
    restaurant_id: int,
    reservation_id: int,
    prepayment_data: PrepaymentCreate,
    session: AsyncSession = Depends(get_session),
):
    """
    Erstellt eine Vorauszahlung für eine Reservierung.
    
    Öffentlicher Endpoint - keine Authentifizierung erforderlich.
    """
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    reservation = await _get_reservation_or_404(reservation_id, restaurant_id, session)
    
    # Prüfe ob bereits eine Vorauszahlung existiert
    result = await session.execute(
        select(ReservationPrepayment).where(
            ReservationPrepayment.reservation_id == reservation_id,
            ReservationPrepayment.status.in_(["pending", "processing"])
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Eine Vorauszahlung für diese Reservierung ist bereits in Bearbeitung"
        )
    
    # Prüfe ob Reservierung bereits abgeschlossen/storniert ist
    if reservation.status in ["canceled", "completed", "no_show"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vorauszahlung nicht möglich für Reservierungen mit diesem Status"
        )
    
    # Validiere Betrag
    if prepayment_data.amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Betrag muss größer als 0 sein"
        )
    
    # Erstelle Prepayment-Eintrag
    prepayment = ReservationPrepayment(
        reservation_id=reservation_id,
        restaurant_id=restaurant_id,
        amount=prepayment_data.amount,
        currency=prepayment_data.currency,
        payment_provider=prepayment_data.payment_provider,
        status="pending",
    )
    
    session.add(prepayment)
    await session.flush()
    
    # Starte Payment je nach Provider
    if prepayment_data.payment_provider == "sumup":
        if not SUMUP_MERCHANT_CODE:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SumUp Merchant Code nicht konfiguriert"
            )
        
        sumup_service = _get_sumup_service()
        
        try:
            # Checkout-Referenz
            checkout_reference = f"RES-{reservation.confirmation_code}-PREPAY-{prepayment.id}"
            
            # Return-URL für nach Zahlung
            return_url = f"{RESERVATION_WIDGET_URL}/{restaurant.slug}/manage/{reservation.confirmation_code}?prepayment=success"
            
            # Beschreibung
            description = f"Vorauszahlung für Reservierung {reservation.confirmation_code} bei {restaurant.name}"
            
            if SUMUP_TEST_MODE:
                # Testmodus: Checkout ohne Reader
                checkout_response = await sumup_service.create_checkout(
                    merchant_code=SUMUP_MERCHANT_CODE,
                    amount=prepayment_data.amount,
                    currency=prepayment_data.currency,
                    checkout_reference=checkout_reference,
                    description=description,
                    return_url=return_url,
                )
                
                checkout_id = checkout_response.get("id") or checkout_response.get("checkout_id")
                client_transaction_id = checkout_response.get("client_transaction_id") or checkout_id
                checkout_status = checkout_response.get("status", "PENDING")
                
                # Update Prepayment
                prepayment.payment_id = checkout_id
                prepayment.transaction_id = client_transaction_id
                prepayment.payment_data = checkout_response
                
                # Status basierend auf Checkout-Status
                if checkout_status == "PAID":
                    prepayment.status = "completed"
                    prepayment.completed_at_utc = datetime.now(timezone.utc)
                elif checkout_status == "FAILED":
                    prepayment.status = "failed"
                else:
                    prepayment.status = "processing"
                
            else:
                # Produktionsmodus: Hier könnte man einen Reader-basierten Checkout verwenden
                # Für jetzt verwenden wir auch Checkout ohne Reader (Online-Zahlung)
                checkout_response = await sumup_service.create_checkout(
                    merchant_code=SUMUP_MERCHANT_CODE,
                    amount=prepayment_data.amount,
                    currency=prepayment_data.currency,
                    checkout_reference=checkout_reference,
                    description=description,
                    return_url=return_url,
                )
                
                checkout_id = checkout_response.get("id") or checkout_response.get("checkout_id")
                client_transaction_id = checkout_response.get("client_transaction_id") or checkout_id
                
                prepayment.payment_id = checkout_id
                prepayment.transaction_id = client_transaction_id
                prepayment.payment_data = checkout_response
                prepayment.status = "processing"
            
            await session.commit()
            await session.refresh(prepayment)
            
            logger.info(f"Prepayment created for reservation {reservation_id}: {checkout_id}")
            
            return prepayment
            
        except Exception as e:
            await session.rollback()
            logger.error(f"Error creating prepayment: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Fehler beim Erstellen der Vorauszahlung: {str(e)}"
            )
    
    else:
        # Andere Payment-Provider (z.B. Stripe) könnten hier implementiert werden
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment-Provider '{prepayment_data.payment_provider}' wird noch nicht unterstützt"
        )


@router.get("/", response_model=PrepaymentRead)
async def get_prepayment(
    restaurant_id: int,
    reservation_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Holt die Vorauszahlung für eine Reservierung (öffentlicher Endpoint)."""
    await _get_restaurant_or_404(restaurant_id, session)
    await _get_reservation_or_404(reservation_id, restaurant_id, session)
    
    result = await session.execute(
        select(ReservationPrepayment).where(
            ReservationPrepayment.reservation_id == reservation_id,
            ReservationPrepayment.restaurant_id == restaurant_id
        ).order_by(ReservationPrepayment.created_at_utc.desc())
    )
    prepayment = result.scalar_one_or_none()
    
    if not prepayment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Keine Vorauszahlung für diese Reservierung gefunden"
        )
    
    return prepayment


@router.get("/checkout-url")
async def get_checkout_url(
    restaurant_id: int,
    reservation_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    Gibt die Checkout-URL für die Vorauszahlung zurück.
    
    Öffentlicher Endpoint - keine Authentifizierung erforderlich.
    """
    await _get_restaurant_or_404(restaurant_id, session)
    reservation = await _get_reservation_or_404(reservation_id, restaurant_id, session)
    
    result = await session.execute(
        select(ReservationPrepayment).where(
            ReservationPrepayment.reservation_id == reservation_id,
            ReservationPrepayment.restaurant_id == restaurant_id,
            ReservationPrepayment.status.in_(["pending", "processing"])
        ).order_by(ReservationPrepayment.created_at_utc.desc())
    )
    prepayment = result.scalar_one_or_none()
    
    if not prepayment or not prepayment.payment_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Keine aktive Vorauszahlung gefunden"
        )
    
    # SumUp Checkout-URL
    if prepayment.payment_provider == "sumup":
        checkout_url = f"https://checkout.sumup.com/checkout/{prepayment.payment_id}"
        return {
            "checkout_url": checkout_url,
            "payment_id": prepayment.payment_id,
            "status": prepayment.status,
        }
    
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Checkout-URL für Provider '{prepayment.payment_provider}' nicht verfügbar"
    )
