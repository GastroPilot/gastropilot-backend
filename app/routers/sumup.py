"""
SumUp Router für Terminal-Integration.

Endpoints für:
- Reader-Verwaltung (Terminals)
- Zahlungsabwicklung
- Status-Abfragen
"""
import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime

from app.dependencies import (
    get_session,
    get_current_user,
    require_mitarbeiter_role,
    require_schichtleiter_role,
    User,
)
from app.database.models import Restaurant, Order, OrderItem, SumUpPayment
from app.services.sumup_service import SumUpService
from app.settings import SUMUP_API_KEY, SUMUP_MERCHANT_CODE, SUMUP_TEST_MODE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/restaurants/{restaurant_id}/sumup", tags=["sumup"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    """Holt ein Restaurant oder wirft 404."""
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


def _get_sumup_service(restaurant: Restaurant) -> SumUpService:
    """Erstellt einen SumUp Service für ein Restaurant."""
    # SumUp API Key wird serverseitig über Environment Variables verwaltet
    # Restaurant-spezifische API Keys werden nicht mehr unterstützt (Sicherheit)
    if not SUMUP_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SumUp API Key nicht konfiguriert. Bitte kontaktieren Sie den Administrator."
        )
    return SumUpService(SUMUP_API_KEY)


# Schemas

class ReaderRead(BaseModel):
    """Reader-Objekt."""
    id: str
    name: str
    status: str
    device: dict
    metadata: Optional[dict] = None
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = False


class ReaderCreate(BaseModel):
    """Request zum Erstellen eines Readers."""
    pairing_code: str = Field(..., min_length=8, max_length=9, description="8-9 stelliger Pairing-Code vom Terminal")
    name: str = Field(..., max_length=500, description="Benutzerdefinierter Name für das Terminal")
    metadata: Optional[dict] = None


class ReaderStatusRead(BaseModel):
    """Reader-Status."""
    battery_level: Optional[float] = None
    battery_temperature: Optional[int] = None
    connection_type: Optional[str] = None
    firmware_version: Optional[str] = None
    last_activity: Optional[str] = None
    state: Optional[str] = None  # IDLE, WAITING_FOR_CARD, etc.
    status: str  # ONLINE, OFFLINE


class PaymentRequest(BaseModel):
    """Request zum Starten einer Zahlung."""
    reader_id: Optional[str] = Field(None, description="Reader ID (erforderlich im Produktionsmodus)")
    amount: float = Field(..., gt=0, description="Betrag in EUR")
    currency: str = Field(default="EUR", max_length=3)
    description: Optional[str] = None
    tip_rates: Optional[list[float]] = Field(None, description="Liste von Trinkgeld-Sätzen (z.B. [0.05, 0.10, 0.15])")
    tip_timeout: Optional[int] = Field(None, ge=30, le=120, description="Timeout für Trinkgeld-Auswahl in Sekunden")


class PaymentResponse(BaseModel):
    """Response nach Zahlungsstart."""
    payment_id: int
    checkout_id: Optional[str] = None  # Checkout ID für weitere Verarbeitung
    client_transaction_id: str
    reader_id: Optional[str] = None  # Optional, da Zahlung ohne Reader-ID möglich ist
    amount: float
    currency: str
    status: str
    message: str


# Reader Endpoints

@router.get("/readers", response_model=list[ReaderRead])
async def list_readers(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Listet alle Reader (Terminals) für ein Restaurant."""
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    
    if not restaurant.sumup_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SumUp ist für dieses Restaurant nicht aktiviert"
        )
    
    # Merchant Code wird serverseitig über Environment Variables verwaltet
    if not SUMUP_MERCHANT_CODE:
        logger.error("SUMUP_MERCHANT_CODE nicht konfiguriert")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SumUp Merchant Code nicht konfiguriert. Bitte kontaktieren Sie den Administrator."
        )
    
    try:
        async with _get_sumup_service(restaurant) as sumup:
            readers = await sumup.list_readers(SUMUP_MERCHANT_CODE)
            return readers
    except httpx.HTTPStatusError as e:
        logger.error(f"SumUp API Error listing readers: {e.response.status_code} - {e.response.text}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"SumUp API Fehler: {e.response.status_code}"
        )
    except Exception as e:
        logger.error(f"Error listing SumUp readers: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Laden der SumUp Reader: {str(e)}"
        )


@router.post("/readers", response_model=ReaderRead, status_code=status.HTTP_201_CREATED)
async def create_reader(
    restaurant_id: int,
    reader_data: ReaderCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Erstellt einen neuen Reader (paart ein Terminal)."""
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    
    if not restaurant.sumup_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SumUp ist für dieses Restaurant nicht aktiviert"
        )
    
    if not SUMUP_MERCHANT_CODE:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SumUp Merchant Code nicht konfiguriert. Bitte kontaktieren Sie den Administrator."
        )
    
    async with _get_sumup_service(restaurant) as sumup:
        reader = await sumup.create_reader(
            merchant_code=SUMUP_MERCHANT_CODE,
            pairing_code=reader_data.pairing_code,
            name=reader_data.name,
            metadata=reader_data.metadata,
        )
        return reader


@router.get("/readers/{reader_id}", response_model=ReaderRead)
async def get_reader(
    restaurant_id: int,
    reader_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Holt einen einzelnen Reader."""
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    
    if not restaurant.sumup_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SumUp ist für dieses Restaurant nicht aktiviert"
        )
    
    if not SUMUP_MERCHANT_CODE:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SumUp Merchant Code nicht konfiguriert. Bitte kontaktieren Sie den Administrator."
        )
    
    async with _get_sumup_service(restaurant) as sumup:
        reader = await sumup.get_reader(SUMUP_MERCHANT_CODE, reader_id)
        return reader


@router.get("/readers/{reader_id}/status", response_model=ReaderStatusRead)
async def get_reader_status(
    restaurant_id: int,
    reader_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Holt den Status eines Readers (Batterie, Verbindung, aktueller Zustand)."""
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    
    if not restaurant.sumup_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SumUp ist für dieses Restaurant nicht aktiviert"
        )
    
    if not SUMUP_MERCHANT_CODE:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SumUp Merchant Code nicht konfiguriert. Bitte kontaktieren Sie den Administrator."
        )
    
    async with _get_sumup_service(restaurant) as sumup:
        status_data = await sumup.get_reader_status(SUMUP_MERCHANT_CODE, reader_id)
        return status_data.get("data", {})


# Payment Endpoints

@router.post("/orders/{order_id}/pay", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def start_payment(
    restaurant_id: int,
    order_id: int,
    payment_data: PaymentRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """
    Startet eine Zahlung für eine Bestellung über SumUp Terminal.
    
    Im Testmodus (SUMUP_TEST_MODE=true):
    - Verwendet Checkout ohne Reader (/v0.1/checkouts)
    
    Im Produktionsmodus (SUMUP_TEST_MODE=false):
    - Verwendet Reader Checkout (/v0.1/merchants/{merchant_code}/readers/{reader_id}/checkout)
    - Reader ID ist erforderlich
    """
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    
    if not restaurant.sumup_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SumUp ist für dieses Restaurant nicht aktiviert"
        )
    
    if not SUMUP_MERCHANT_CODE:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SumUp Merchant Code nicht konfiguriert. Bitte kontaktieren Sie den Administrator."
        )
    
    # Bestellung prüfen
    order = await session.get(Order, order_id)
    if not order or order.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    
    if order.payment_status == "paid":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bestellung ist bereits bezahlt"
        )
    
    # Betrag bestimmen (aus Payment-Request oder Order-Total)
    amount = payment_data.amount or order.total
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Betrag muss größer als 0 sein"
        )
    
    # Im Produktionsmodus: Reader ID prüfen
    reader_id = None
    if not SUMUP_TEST_MODE:
        reader_id = payment_data.reader_id or restaurant.sumup_default_reader_id
        if not reader_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reader ID ist im Produktionsmodus erforderlich. Bitte geben Sie eine Reader ID an oder konfigurieren Sie eine Standard-Reader-ID für das Restaurant."
            )
    
    # Order-Items laden für SumUp
    order_items_result = await session.execute(
        select(OrderItem).where(OrderItem.order_id == order_id)
    )
    order_items = order_items_result.scalars().all()
    
    # Order-Items in SumUp-Format konvertieren
    # SumUp erwartet im Receipt-Format: name, description, price (NETTO - ohne MwSt), quantity, total_price (NETTO)
    sumup_items = []
    for item in order_items:
        # Berechne Netto-Preise (SumUp erwartet Preise ohne MwSt im Receipt)
        # unit_price ist inkl. MwSt, wir müssen Netto berechnen
        net_unit_price = item.unit_price / (1 + item.tax_rate)
        net_total_price = item.total_price / (1 + item.tax_rate)
        
        sumup_items.append({
            "name": item.item_name,
            "description": item.item_description or "",
            "quantity": item.quantity,
            "price": round(net_unit_price, 2),  # Netto-Preis ohne MwSt (wie SumUp Receipt erwartet)
            "total_price": round(net_total_price, 2),  # Netto-Gesamtpreis ohne MwSt
            "unit_price": item.unit_price,  # Brutto für unsere interne Nachverfolgbarkeit
            "tax_rate": item.tax_rate,
            "category": item.category or "",
        })
    
    # Webhook URL für Rückmeldung (return_url im Checkout)
    # SumUp sendet die Response an diese URL nach der Zahlung
    from app.settings import SUMUP_WEBHOOK_URL
    return_url = SUMUP_WEBHOOK_URL
    
    if not return_url:
        logger.warning(
            f"SUMUP_WEBHOOK_URL nicht gesetzt - Webhooks werden nicht empfangen. "
            f"Bitte setzen Sie SUMUP_WEBHOOK_URL in der .env Datei (z.B. https://api.example.com/v1/webhooks/sumup)"
        )
    else:
        # Stelle sicher, dass die URL den korrekten Webhook-Endpoint enthält
        if "/webhooks/sumup" not in return_url:
            logger.warning(
                f"SUMUP_WEBHOOK_URL scheint nicht den korrekten Webhook-Endpoint zu enthalten: {return_url}. "
                f"Erwartet: .../webhooks/sumup"
            )
    
    try:
        async with _get_sumup_service(restaurant) as sumup:
            import uuid
            checkout_reference = f"order_{order.id}_{uuid.uuid4().hex[:8]}"
            
            # Beschreibung mit Order-Nummer erstellen
            description = payment_data.description or f"Bestellung {order.order_number or order.id}"
            if order_items:
                items_summary = ", ".join([
                    f"{item.item_name} x{item.quantity}"
                    for item in order_items[:5]
                ])
                if len(order_items) > 5:
                    items_summary += f" und {len(order_items) - 5} weitere"
                description = f"{description} - {items_summary}"
            
            checkout_id = None
            client_transaction_id = None
            checkout_status = "PENDING"
            checkout_response = None
            
            if SUMUP_TEST_MODE:
                # TESTMODUS: Checkout ohne Reader erstellen
                logger.info(
                    f"[TESTMODUS] Erstelle SumUp Checkout für Order {order.id} "
                    f"(Betrag: {amount} {payment_data.currency}, "
                    f"return_url: {return_url or 'NICHT GESETZT'})"
                )
                
                checkout_response = await sumup.create_checkout(
                    merchant_code=SUMUP_MERCHANT_CODE,
                    amount=amount,
                    currency=payment_data.currency,
                    checkout_reference=checkout_reference,
                    description=description,
                    return_url=return_url,
                    items=sumup_items if sumup_items else None,
                )
                
                checkout_id = checkout_response.get("id") or checkout_response.get("checkout_id")
                if not checkout_id:
                    logger.error(f"SumUp Checkout Response hat keine 'id' oder 'checkout_id': {checkout_response}")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"SumUp hat keine checkout_id zurückgegeben. Response: {checkout_response}"
                    )
                
                client_transaction_id = checkout_response.get("client_transaction_id") or checkout_id
                checkout_status = checkout_response.get("status", "PENDING")
                
            else:
                # PRODUKTIONSMODUS: Reader Checkout erstellen
                logger.info(
                    f"[PRODUKTIONSMODUS] Erstelle SumUp Reader Checkout für Order {order.id} "
                    f"(Betrag: {amount} {payment_data.currency}, Reader: {reader_id}, "
                    f"return_url: {return_url or 'NICHT GESETZT'})"
                )
                
                checkout_response = await sumup.create_reader_checkout(
                    merchant_code=SUMUP_MERCHANT_CODE,
                    reader_id=reader_id,
                    amount=amount,
                    currency=payment_data.currency,
                    description=description,
                    return_url=return_url,
                    tip_rates=payment_data.tip_rates,
                    tip_timeout=payment_data.tip_timeout,
                )
                
                # Reader Checkout gibt client_transaction_id zurück
                client_transaction_id = checkout_response.get("client_transaction_id")
                if not client_transaction_id:
                    logger.error(f"SumUp Reader Checkout Response hat keine 'client_transaction_id': {checkout_response}")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"SumUp hat keine client_transaction_id zurückgegeben. Response: {checkout_response}"
                    )
                
                # Für Reader Checkout verwenden wir client_transaction_id als checkout_id
                checkout_id = client_transaction_id
                checkout_status = "PENDING"  # Reader Checkout startet immer mit PENDING
            
            logger.info(f"Checkout erstellt - ID: {checkout_id}, Reference: {checkout_reference}, Modus: {'TEST' if SUMUP_TEST_MODE else 'PRODUKTION'}")
            
            # Für Terminal-Zahlungen wird der Checkout NICHT sofort verarbeitet
            # Der Checkout bleibt im Status "PENDING" und wird vom Terminal verarbeitet
            # Die tatsächliche Zahlung erfolgt über das Terminal, danach kommt ein Webhook
            
            # Status auf unser internes Format mappen
            if checkout_status == "PAID":
                payment_status = "successful"
                transaction_id = checkout_response.get("transaction_id")
                transaction_code = checkout_response.get("transaction_code")
            elif checkout_status == "FAILED":
                payment_status = "failed"
                transaction_id = checkout_response.get("transaction_id")
                transaction_code = checkout_response.get("transaction_code")
            elif checkout_status == "EXPIRED":
                payment_status = "canceled"
                transaction_id = None
                transaction_code = None
            else:
                # PENDING - Checkout wurde erstellt, wartet auf Terminal-Zahlung
                payment_status = "processing"
                transaction_id = None
                transaction_code = None
            
            # SumUpPayment-Eintrag erstellen
            payment_metadata = {
                "order_items": sumup_items,
                "order_number": order.order_number,
                "checkout_reference": checkout_reference,
                "test_mode": SUMUP_TEST_MODE,
            }
            
            sumup_payment = SumUpPayment(
                order_id=order_id,
                restaurant_id=restaurant_id,
                checkout_id=checkout_id,
                client_transaction_id=client_transaction_id,
                transaction_id=transaction_id,
                transaction_code=transaction_code,
                reader_id=reader_id if not SUMUP_TEST_MODE else None,
                amount=amount,
                currency=payment_data.currency,
                status=payment_status,
                webhook_data=payment_metadata,
            )
            session.add(sumup_payment)
            await session.flush()
            
            # Order-Status wird NICHT beim Checkout-Erstellen aktualisiert
            # Der Status wird erst durch den Webhook aktualisiert, wenn die Zahlung abgeschlossen ist
            # Nur wenn die Zahlung bereits erfolgreich ist (z.B. bei sofortiger Verarbeitung),
            # wird der Status aktualisiert
            if payment_status == "successful":
                order.payment_status = "paid"
                order.payment_method = "sumup_card"
                from datetime import datetime, timezone
                order.paid_at = datetime.now(timezone.utc)
            # Bei "processing" oder "failed" wird der Order-Status NICHT geändert
            # Der Webhook wird den Status später aktualisieren
            
            await session.commit()
            await session.refresh(sumup_payment)
            
            # Status-Message basierend auf Ergebnis
            if payment_status == "successful":
                message = f"Zahlung erfolgreich verarbeitet. Transaction: {transaction_code or checkout_id}"
            elif payment_status == "failed":
                message = "Zahlung konnte nicht verarbeitet werden. Bitte versuchen Sie es erneut."
            else:
                if SUMUP_TEST_MODE:
                    message = f"Checkout wurde erstellt (Checkout ID: {checkout_id}). Bitte führen Sie die Zahlung durch. Der Status wird automatisch aktualisiert."
                else:
                    message = f"Reader Checkout wurde erstellt (Transaction ID: {client_transaction_id}). Bitte führen Sie die Zahlung am Terminal durch. Der Status wird automatisch aktualisiert."
            
            return PaymentResponse(
                payment_id=sumup_payment.id,
                checkout_id=checkout_id,
                client_transaction_id=client_transaction_id,
                reader_id=reader_id if not SUMUP_TEST_MODE else None,
                amount=amount,
                currency=payment_data.currency,
                status=payment_status,
                message=message,
            )
            
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Error starting SumUp payment: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Starten der Zahlung: {str(e)}"
        )


@router.post("/readers/{reader_id}/terminate", status_code=status.HTTP_204_NO_CONTENT)
async def terminate_payment(
    restaurant_id: int,
    reader_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Bricht eine laufende Zahlung am Terminal ab."""
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    
    if not restaurant.sumup_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SumUp ist für dieses Restaurant nicht aktiviert"
        )
    
    if not SUMUP_MERCHANT_CODE:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SumUp Merchant Code nicht konfiguriert. Bitte kontaktieren Sie den Administrator."
        )
    
    try:
        async with _get_sumup_service(restaurant) as sumup:
            await sumup.terminate_reader_checkout(SUMUP_MERCHANT_CODE, reader_id)
    except Exception as e:
        logger.error(f"Error terminating SumUp payment: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abbrechen der Zahlung: {str(e)}"
        )


# Payment History & Failed Payments

class SumUpPaymentRead(BaseModel):
    """SumUp Payment Response."""
    id: int
    order_id: int
    restaurant_id: int
    checkout_id: Optional[str] = None
    client_transaction_id: Optional[str] = None
    transaction_code: Optional[str] = None
    transaction_id: Optional[str] = None
    amount: float
    currency: str
    status: str  # pending, processing, successful, failed, canceled
    initiated_at: datetime
    completed_at: Optional[datetime] = None
    created_at_utc: datetime
    
    # Order Info (optional, falls mit Order geladen)
    order: Optional[dict] = None
    
    class Config:
        from_attributes = True


@router.get("/payments/failed", response_model=list[SumUpPaymentRead])
async def get_failed_payments(
    restaurant_id: int,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """
    Ruft fehlgeschlagene SumUp-Zahlungen für ein Restaurant ab.
    
    Zeigt alle Zahlungen mit Status "failed" oder "canceled" an.
    """
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    
    if not restaurant.sumup_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SumUp ist für dieses Restaurant nicht aktiviert"
        )
    
    # Fehlgeschlagene Zahlungen abrufen
    result = await session.execute(
        select(SumUpPayment)
        .where(
            SumUpPayment.restaurant_id == restaurant_id,
            SumUpPayment.status.in_(["failed", "canceled"])
        )
        .order_by(SumUpPayment.created_at_utc.desc())
        .limit(limit)
    )
    failed_payments = result.scalars().all()
    
    # Order-Informationen laden
    payments_with_orders = []
    for payment in failed_payments:
        order = await session.get(Order, payment.order_id)
        payment_dict = {
            "id": payment.id,
            "order_id": payment.order_id,
            "restaurant_id": payment.restaurant_id,
            "checkout_id": payment.checkout_id,
            "client_transaction_id": payment.client_transaction_id,
            "transaction_code": payment.transaction_code,
            "transaction_id": payment.transaction_id,
            "amount": payment.amount,
            "currency": payment.currency,
            "status": payment.status,
            "initiated_at": payment.initiated_at,
            "completed_at": payment.completed_at,
            "created_at_utc": payment.created_at_utc,
            "order": {
                "id": order.id if order else None,
                "order_number": order.order_number if order else None,
                "total": order.total if order else None,
                "status": order.status if order else None,
            } if order else None,
        }
        payments_with_orders.append(SumUpPaymentRead(**payment_dict))
    
    return payments_with_orders


@router.get("/payments", response_model=list[SumUpPaymentRead])
async def get_payments(
    restaurant_id: int,
    status: Optional[str] = None,  # Filter nach Status (failed, canceled, successful, etc.)
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """
    Ruft SumUp-Zahlungen für ein Restaurant ab.
    
    Optional kann nach Status gefiltert werden.
    """
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    
    if not restaurant.sumup_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SumUp ist für dieses Restaurant nicht aktiviert"
        )
    
    # Query bauen
    query = select(SumUpPayment).where(
        SumUpPayment.restaurant_id == restaurant_id
    )
    
    if status:
        query = query.where(SumUpPayment.status == status)
    
    query = query.order_by(SumUpPayment.created_at_utc.desc()).limit(limit)
    
    result = await session.execute(query)
    payments = result.scalars().all()
    
    # Order-Informationen laden
    payments_with_orders = []
    for payment in payments:
        order = await session.get(Order, payment.order_id)
        payment_dict = {
            "id": payment.id,
            "order_id": payment.order_id,
            "restaurant_id": payment.restaurant_id,
            "checkout_id": payment.checkout_id,
            "client_transaction_id": payment.client_transaction_id,
            "transaction_code": payment.transaction_code,
            "transaction_id": payment.transaction_id,
            "amount": payment.amount,
            "currency": payment.currency,
            "status": payment.status,
            "initiated_at": payment.initiated_at,
            "completed_at": payment.completed_at,
            "created_at_utc": payment.created_at_utc,
            "order": {
                "id": order.id if order else None,
                "order_number": order.order_number if order else None,
                "total": order.total if order else None,
                "status": order.status if order else None,
            } if order else None,
        }
        payments_with_orders.append(SumUpPaymentRead(**payment_dict))
    
    return payments_with_orders


@router.get("/orders/{order_id}/payments", response_model=list[SumUpPaymentRead])
async def get_order_payments(
    restaurant_id: int,
    order_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """
    Ruft alle SumUp-Zahlungen für eine bestimmte Bestellung ab.
    
    Zeigt alle Zahlungsversuche (erfolgreich, fehlgeschlagen, abgebrochen) für diese Order.
    """
    restaurant = await _get_restaurant_or_404(restaurant_id, session)
    
    if not restaurant.sumup_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SumUp ist für dieses Restaurant nicht aktiviert"
        )
    
    # Bestellung prüfen
    order = await session.get(Order, order_id)
    if not order or order.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    
    # Alle Zahlungen für diese Order abrufen
    result = await session.execute(
        select(SumUpPayment)
        .where(SumUpPayment.order_id == order_id)
        .order_by(SumUpPayment.created_at_utc.desc())
    )
    payments = result.scalars().all()
    
    # Payment-Informationen formatieren
    payments_list = []
    for payment in payments:
        payment_dict = {
            "id": payment.id,
            "order_id": payment.order_id,
            "restaurant_id": payment.restaurant_id,
            "checkout_id": payment.checkout_id,
            "client_transaction_id": payment.client_transaction_id,
            "transaction_code": payment.transaction_code,
            "transaction_id": payment.transaction_id,
            "amount": payment.amount,
            "currency": payment.currency,
            "status": payment.status,
            "initiated_at": payment.initiated_at,
            "completed_at": payment.completed_at,
            "created_at_utc": payment.created_at_utc,
            "order": {
                "id": order.id,
                "order_number": order.order_number,
                "total": order.total,
                "status": order.status,
            },
        }
        payments_list.append(SumUpPaymentRead(**payment_dict))
    
    return payments_list
