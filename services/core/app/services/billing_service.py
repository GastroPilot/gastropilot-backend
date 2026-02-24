from __future__ import annotations
import logging
from dataclasses import dataclass
from uuid import UUID
from enum import StrEnum

import httpx

logger = logging.getLogger(__name__)


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
