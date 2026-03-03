"""Stripe billing endpoints."""

from __future__ import annotations

import json
import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_db, require_owner_or_above
from app.schemas.billing import (
    BillingPortalResponse,
    CheckoutResponse,
    CreateCheckoutRequest,
    SubscriptionPlanResponse,
    SubscriptionResponse,
)
from app.services.billing_service import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"])

PLANS = [
    SubscriptionPlanResponse(
        id="free",
        name="Free",
        price=0.0,
        features=[
            "30 Reservierungen/Monat",
            "1 Benutzer",
            "Basis-Dashboard",
        ],
        tier="free",
    ),
    SubscriptionPlanResponse(
        id="starter",
        name="Starter",
        price=49.0,
        features=[
            "Unbegrenzte Reservierungen",
            "KI-Funktionen",
            "Allergen-Management",
            "3 Benutzer",
        ],
        tier="starter",
    ),
    SubscriptionPlanResponse(
        id="professional",
        name="Professional",
        price=99.0,
        features=[
            "Alles aus Starter",
            "Bestellsystem + KDS",
            "QR-Bestellungen",
            "CRM",
            "SMS-Benachrichtigungen",
            "10 Benutzer",
        ],
        tier="professional",
    ),
    SubscriptionPlanResponse(
        id="enterprise",
        name="Enterprise",
        price=199.0,
        features=[
            "Alles aus Professional",
            "Multi-Standort",
            "API-Zugang",
            "Priority Support",
            "Unbegrenzte Benutzer",
        ],
        tier="enterprise",
    ),
]


@router.get("/billing/plans", response_model=list[SubscriptionPlanResponse])
async def list_plans():
    """List available subscription plans."""
    return PLANS


@router.post("/billing/checkout", response_model=CheckoutResponse)
async def create_checkout(
    body: CreateCheckoutRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Create a Stripe Checkout session for subscription."""
    plan = next((p for p in PLANS if p.id == body.plan_id), None)
    if not plan or plan.id == "free":
        raise HTTPException(status_code=404, detail="Plan not found")

    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")

    svc = SubscriptionService(db)
    try:
        url = await svc.create_checkout(tenant_id, body.plan_id, body.success_url, body.cancel_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    return CheckoutResponse(checkout_url=url)


@router.get("/billing/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Get current subscription status."""
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")

    svc = SubscriptionService(db)
    try:
        data = await svc.sync_subscription(tenant_id)
    except Exception:
        logger.exception("Failed to sync subscription")
        data = {"id": None, "plan": "free", "status": "inactive", "current_period_end": None}

    await db.commit()
    return SubscriptionResponse(
        id=data.get("id") or "none",
        plan=data.get("plan", "free"),
        status=data.get("status", "inactive"),
        current_period_end=data.get("current_period_end"),
    )


@router.post("/billing/portal", response_model=BillingPortalResponse)
async def create_billing_portal(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Create Stripe billing portal session."""
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")

    svc = SubscriptionService(db)
    try:
        url = await svc.create_portal(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return BillingPortalResponse(url=url)


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Stripe webhooks with signature verification."""
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")
    webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")

    if webhook_secret and sig:
        try:
            event = stripe.Webhook.construct_event(body, sig, webhook_secret)
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        try:
            event = json.loads(body)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid payload")

    event_type = event.get("type", "")
    event_data = event.get("data", {}).get("object", {})
    logger.info("Stripe webhook: %s", event_type)

    svc = SubscriptionService(db)

    if event_type == "checkout.session.completed":
        await svc.handle_checkout_completed(event_data)
    elif event_type == "customer.subscription.updated":
        await svc.handle_subscription_updated(event_data)
    elif event_type == "customer.subscription.deleted":
        await svc.handle_subscription_deleted(event_data)
    elif event_type == "invoice.payment_failed":
        await svc.handle_payment_failed(event_data)

    await db.commit()
    return {"received": True}
