from __future__ import annotations
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_db, require_staff_or_above
from app.models.user import User
from app.services.billing_service import BillingService, CheckoutResult, OrderLineItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

_billing = BillingService(
    stripe_secret_key=settings.STRIPE_SECRET_KEY or None,
    sumup_api_key=settings.SUMUP_API_KEY or None,
)


class CheckoutRequest(BaseModel):
    order_id: UUID
    total_cents: int
    currency: str = "EUR"
    items: list[dict] = []
    success_url: str
    cancel_url: str


class CheckoutResponse(BaseModel):
    provider: str
    checkout_id: str
    checkout_url: str | None = None
    status: str


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    body: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    """Erstellt eine Zahlungssession bei Stripe oder SumUp."""
    # Restaurant-Settings für Provider-Auswahl laden
    from app.models.restaurant import Restaurant
    result = await db.execute(
        select(Restaurant).where(Restaurant.id == current_user.tenant_id)
    )
    restaurant = result.scalar_one_or_none()
    restaurant_settings = restaurant.settings or {} if restaurant else {}

    line_items = [
        OrderLineItem(
            name=item.get("name", "Artikel"),
            quantity=item.get("quantity", 1),
            unit_price_cents=item.get("unit_price_cents", 0),
        )
        for item in body.items
    ]

    try:
        result = await _billing.create_checkout(
            order_id=body.order_id,
            total_cents=body.total_cents,
            currency=body.currency,
            items=line_items,
            restaurant_settings=restaurant_settings,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return CheckoutResponse(
        provider=result.provider,
        checkout_id=result.checkout_id,
        checkout_url=result.checkout_url,
        status=result.status,
    )


@router.get("/checkout/{checkout_id}/status")
async def get_checkout_status(
    checkout_id: str,
    provider: str = "sumup",
    current_user: User = Depends(require_staff_or_above),
):
    """Fragt den aktuellen Status einer Zahlungssession ab."""
    try:
        status_value = await _billing.get_checkout_status(checkout_id, provider)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"checkout_id": checkout_id, "provider": provider, "status": status_value}


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Stripe Webhook-Empfänger."""
    import hmac
    import hashlib

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET

    if webhook_secret:
        try:
            parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
            timestamp = parts.get("t", "")
            signature = parts.get("v1", "")
            signed_payload = f"{timestamp}.{payload.decode()}"
            expected = hmac.new(
                webhook_secret.encode(),
                signed_payload.encode(),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise HTTPException(status_code=400, detail="Ungültige Signatur")
        except Exception:
            raise HTTPException(status_code=400, detail="Webhook-Validierung fehlgeschlagen")

    import json
    event = json.loads(payload)
    logger.info("Stripe Webhook empfangen: %s", event.get("type"))
    # TODO: Event-Verarbeitung (payment_intent.succeeded etc.)
    return {"received": True}


@router.post("/webhook/sumup")
async def sumup_webhook(request: Request):
    """SumUp Webhook-Empfänger."""
    payload = await request.json()
    logger.info("SumUp Webhook empfangen: %s", payload.get("event_type"))
    # TODO: Event-Verarbeitung (checkout.completed etc.)
    return {"received": True}
