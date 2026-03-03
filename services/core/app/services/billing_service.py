from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

import httpx
import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.models.restaurant import Restaurant

logger = logging.getLogger(__name__)

stripe.api_key = getattr(app_settings, "STRIPE_SECRET_KEY", "")

SUBSCRIPTION_PRICE_MAP = {
    "starter": getattr(app_settings, "STRIPE_PRICE_STARTER", ""),
    "professional": getattr(app_settings, "STRIPE_PRICE_PROFESSIONAL", ""),
    "enterprise": getattr(app_settings, "STRIPE_PRICE_ENTERPRISE", ""),
}


class PaymentProvider(StrEnum):
    STRIPE = "stripe"
    SUMUP = "sumup"
    BOTH = "both"


@dataclass
class CheckoutResult:
    provider: str
    checkout_id: str
    checkout_url: str | None = None
    status: str = "pending"


@dataclass
class OrderLineItem:
    name: str
    quantity: int
    unit_price_cents: int  # in Cent (kleinste Währungseinheit)
    vat_rate: float = 0.19


class BillingService:
    """
    Abstraktion über Stripe und SumUp.
    Der zu verwendende Provider wird pro Tenant aus restaurant.settings bestimmt.
    """

    def __init__(
        self,
        stripe_secret_key: str | None = None,
        sumup_api_key: str | None = None,
    ) -> None:
        self._stripe_key = stripe_secret_key
        self._sumup_key = sumup_api_key

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    async def create_checkout(
        self,
        order_id: UUID,
        total_cents: int,
        currency: str,
        items: list[OrderLineItem],
        restaurant_settings: dict,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        provider = restaurant_settings.get("payment_provider", PaymentProvider.SUMUP)

        if provider == PaymentProvider.STRIPE:
            return await self._stripe_checkout(
                order_id, total_cents, currency, items, success_url, cancel_url
            )
        elif provider == PaymentProvider.SUMUP:
            return await self._sumup_checkout(order_id, total_cents, currency, items)
        else:
            # "both" – Stripe bevorzugen
            return await self._stripe_checkout(
                order_id, total_cents, currency, items, success_url, cancel_url
            )

    async def get_checkout_status(
        self,
        checkout_id: str,
        provider: str,
    ) -> str:
        if provider == PaymentProvider.STRIPE:
            return await self._stripe_get_status(checkout_id)
        return await self._sumup_get_status(checkout_id)

    # ------------------------------------------------------------------
    # Stripe
    # ------------------------------------------------------------------

    async def _stripe_checkout(
        self,
        order_id: UUID,
        total_cents: int,
        currency: str,
        items: list[OrderLineItem],
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        if not self._stripe_key:
            raise RuntimeError("STRIPE_SECRET_KEY nicht konfiguriert")

        line_items = [
            {
                "price_data": {
                    "currency": currency.lower(),
                    "product_data": {"name": item.name},
                    "unit_amount": item.unit_price_cents,
                },
                "quantity": item.quantity,
            }
            for item in items
        ]

        payload = {
            "mode": "payment",
            "line_items": line_items,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {"order_id": str(order_id)},
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                data=payload,
                auth=(self._stripe_key, ""),
            )
            response.raise_for_status()
            data = response.json()

        return CheckoutResult(
            provider=PaymentProvider.STRIPE,
            checkout_id=data["id"],
            checkout_url=data["url"],
            status="pending",
        )

    async def _stripe_get_status(self, session_id: str) -> str:
        if not self._stripe_key:
            raise RuntimeError("STRIPE_SECRET_KEY nicht konfiguriert")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.stripe.com/v1/checkout/sessions/{session_id}",
                auth=(self._stripe_key, ""),
            )
            response.raise_for_status()
            data = response.json()

        status_map = {
            "open": "pending",
            "complete": "paid",
            "expired": "expired",
        }
        return status_map.get(data.get("status", ""), "unknown")

    # ------------------------------------------------------------------
    # SumUp
    # ------------------------------------------------------------------

    async def _sumup_checkout(
        self,
        order_id: UUID,
        total_cents: int,
        currency: str,
        items: list[OrderLineItem],
    ) -> CheckoutResult:
        if not self._sumup_key:
            raise RuntimeError("SUMUP_API_KEY nicht konfiguriert")

        total_amount = total_cents / 100

        payload = {
            "checkout_reference": str(order_id),
            "amount": total_amount,
            "currency": currency.upper(),
            "description": f"Bestellung {str(order_id)[:8]}",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.sumup.com/v0.1/checkouts",
                json=payload,
                headers={"Authorization": f"Bearer {self._sumup_key}"},
            )
            response.raise_for_status()
            data = response.json()

        return CheckoutResult(
            provider=PaymentProvider.SUMUP,
            checkout_id=data["id"],
            checkout_url=f"https://pay.sumup.com/b2c/checkout/{data['id']}",
            status=data.get("status", "PENDING").lower(),
        )

    async def _sumup_get_status(self, checkout_id: str) -> str:
        if not self._sumup_key:
            raise RuntimeError("SUMUP_API_KEY nicht konfiguriert")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.sumup.com/v0.1/checkouts/{checkout_id}",
                headers={"Authorization": f"Bearer {self._sumup_key}"},
            )
            response.raise_for_status()
            data = response.json()

        status_map = {
            "PENDING": "pending",
            "PAID": "paid",
            "FAILED": "failed",
            "EXPIRED": "expired",
        }
        return status_map.get(data.get("status", ""), "unknown")


class SubscriptionService:
    """Stripe subscription management for restaurant tiers."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_restaurant(self, tenant_id) -> Restaurant:
        result = await self.session.execute(select(Restaurant).where(Restaurant.id == tenant_id))
        restaurant = result.scalar_one_or_none()
        if not restaurant:
            raise ValueError("Restaurant not found")
        return restaurant

    async def ensure_customer(self, tenant_id, email: str) -> str:
        restaurant = await self._get_restaurant(tenant_id)
        if restaurant.stripe_customer_id:
            return restaurant.stripe_customer_id

        customer = stripe.Customer.create(
            email=email,
            name=restaurant.name,
            metadata={"tenant_id": str(tenant_id)},
        )
        restaurant.stripe_customer_id = customer.id
        restaurant.billing_email = email
        await self.session.flush()
        return customer.id

    async def create_checkout(
        self, tenant_id, plan_id: str, success_url: str, cancel_url: str
    ) -> str:
        restaurant = await self._get_restaurant(tenant_id)
        customer_id = await self.ensure_customer(
            tenant_id, restaurant.billing_email or restaurant.email or ""
        )
        price_id = SUBSCRIPTION_PRICE_MAP.get(plan_id)
        if not price_id:
            raise ValueError(f"Unknown plan: {plan_id}")

        checkout = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"tenant_id": str(tenant_id), "plan_id": plan_id},
        )
        return checkout.url

    async def create_portal(self, tenant_id) -> str:
        restaurant = await self._get_restaurant(tenant_id)
        if not restaurant.stripe_customer_id:
            raise ValueError("No Stripe customer found")
        portal = stripe.billing_portal.Session.create(
            customer=restaurant.stripe_customer_id,
        )
        return portal.url

    async def sync_subscription(self, tenant_id) -> dict:
        restaurant = await self._get_restaurant(tenant_id)
        if not restaurant.stripe_subscription_id:
            return {
                "id": None,
                "plan": restaurant.subscription_tier or "free",
                "status": restaurant.subscription_status or "inactive",
                "current_period_end": None,
            }
        sub = stripe.Subscription.retrieve(restaurant.stripe_subscription_id)
        restaurant.subscription_status = sub.status
        if sub.current_period_end:
            restaurant.subscription_current_period_end = datetime.fromtimestamp(
                sub.current_period_end, tz=UTC
            )
        await self.session.flush()
        return {
            "id": sub.id,
            "plan": restaurant.subscription_tier or "free",
            "status": sub.status,
            "current_period_end": (
                restaurant.subscription_current_period_end.isoformat()
                if restaurant.subscription_current_period_end
                else None
            ),
        }

    async def handle_checkout_completed(self, session_data: dict):
        metadata = session_data.get("metadata", {})
        tenant_id = metadata.get("tenant_id")
        plan_id = metadata.get("plan_id", "starter")
        if not tenant_id:
            logger.warning("Checkout without tenant_id")
            return
        result = await self.session.execute(select(Restaurant).where(Restaurant.id == tenant_id))
        restaurant = result.scalar_one_or_none()
        if not restaurant:
            return
        restaurant.stripe_customer_id = session_data.get("customer")
        restaurant.stripe_subscription_id = session_data.get("subscription")
        restaurant.subscription_tier = plan_id
        restaurant.subscription_status = "active"
        restaurant.is_suspended = False
        await self.session.flush()

    async def handle_subscription_updated(self, sub_data: dict):
        sub_id = sub_data.get("id")
        result = await self.session.execute(
            select(Restaurant).where(Restaurant.stripe_subscription_id == sub_id)
        )
        restaurant = result.scalar_one_or_none()
        if not restaurant:
            return
        restaurant.subscription_status = sub_data.get("status", "active")
        if sub_data.get("current_period_end"):
            restaurant.subscription_current_period_end = datetime.fromtimestamp(
                sub_data["current_period_end"], tz=UTC
            )
        await self.session.flush()

    async def handle_subscription_deleted(self, sub_data: dict):
        sub_id = sub_data.get("id")
        result = await self.session.execute(
            select(Restaurant).where(Restaurant.stripe_subscription_id == sub_id)
        )
        restaurant = result.scalar_one_or_none()
        if not restaurant:
            return
        restaurant.subscription_status = "canceled"
        restaurant.subscription_tier = "free"
        restaurant.stripe_subscription_id = None
        await self.session.flush()

    async def handle_payment_failed(self, invoice_data: dict):
        customer_id = invoice_data.get("customer")
        result = await self.session.execute(
            select(Restaurant).where(Restaurant.stripe_customer_id == customer_id)
        )
        restaurant = result.scalar_one_or_none()
        if not restaurant:
            return
        restaurant.subscription_status = "past_due"
        await self.session.flush()
