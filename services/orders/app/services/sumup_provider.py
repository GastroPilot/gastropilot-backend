"""SumUp terminal provider — wraps existing SumUp API calls."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from app.core.config import settings
from app.models.order import Order
from app.models.terminal import PaymentTerminal, TerminalPayment

logger = logging.getLogger(__name__)

SUMUP_BASE = "https://api.sumup.com"
SUMUP_TIMEOUT = httpx.Timeout(30.0)


def _get_credentials() -> tuple[str, str]:
    api_key = getattr(settings, "SUMUP_API_KEY", None)
    merchant_code = getattr(settings, "SUMUP_MERCHANT_CODE", None)
    if not api_key or not merchant_code:
        raise ValueError("SumUp nicht konfiguriert (SUMUP_API_KEY/SUMUP_MERCHANT_CODE)")
    return api_key, merchant_code


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


class SumUpTerminalProvider:
    provider_name = "sumup"

    async def initiate_payment(
        self,
        terminal: PaymentTerminal,
        order: Order,
        amount: float,
        currency: str = "EUR",
        **kwargs: Any,
    ) -> dict:
        api_key, merchant_code = _get_credentials()
        webhook_url = getattr(settings, "SUMUP_WEBHOOK_URL", None)
        reader_id = terminal.provider_terminal_id
        checkout_ref = f"order_{order.id}_{uuid.uuid4()}"
        client_tx_id = str(uuid.uuid4())

        async with httpx.AsyncClient(base_url=SUMUP_BASE, timeout=SUMUP_TIMEOUT,
                                     headers=_headers(api_key)) as client:
            if reader_id:
                # Reader-specific checkout
                amount_cents = int(round(amount * 100))
                payload: dict = {
                    "total_amount": {
                        "currency": currency,
                        "minor_unit": 2,
                        "value": amount_cents,
                    },
                    "description": kwargs.get("description", f"Bestellung {order.order_number or order.id}"),
                }
                if webhook_url:
                    payload["return_url"] = webhook_url
                tip_rates = kwargs.get("tip_rates")
                if tip_rates:
                    payload["tip_rates"] = tip_rates
                    payload["tip_timeout"] = max(30, min(kwargs.get("tip_timeout", 60), 120))

                resp = await client.post(
                    f"/v0.1/merchants/{merchant_code}/readers/{reader_id}/checkout",
                    json=payload,
                )
            else:
                # Generic checkout (no specific reader)
                payload = {
                    "amount": amount,
                    "currency": currency,
                    "merchant_code": merchant_code,
                    "checkout_reference": checkout_ref,
                    "description": kwargs.get("description", ""),
                }
                if webhook_url:
                    payload["return_url"] = webhook_url

                resp = await client.post("/v0.1/checkouts", json=payload)

            if resp.status_code >= 400:
                logger.error("SumUp checkout failed: %s %s", resp.status_code, resp.text)
                return {
                    "status": "failed",
                    "provider_data": {"error": resp.text},
                }

            data = resp.json()
            return {
                "status": "processing",
                "provider_data": {
                    "checkout_id": data.get("id") or data.get("checkout_id"),
                    "client_transaction_id": client_tx_id,
                    "checkout_reference": checkout_ref,
                    "reader_id": reader_id,
                },
            }

    async def confirm_payment(self, payment: TerminalPayment) -> str:
        # SumUp payments are confirmed via webhook, not manually
        return payment.status

    async def cancel_payment(self, payment: TerminalPayment) -> str:
        api_key, merchant_code = _get_credentials()
        pd = payment.provider_data or {}
        reader_id = pd.get("reader_id")

        if reader_id:
            try:
                async with httpx.AsyncClient(base_url=SUMUP_BASE, timeout=SUMUP_TIMEOUT,
                                             headers=_headers(api_key)) as client:
                    await client.post(
                        f"/v0.1/merchants/{merchant_code}/readers/{reader_id}/terminate"
                    )
            except Exception as exc:
                logger.warning("SumUp terminate failed: %s", exc)

        return "canceled"

    async def get_terminal_status(self, terminal: PaymentTerminal) -> dict | None:
        if not terminal.provider_terminal_id:
            return None
        try:
            api_key, merchant_code = _get_credentials()
            async with httpx.AsyncClient(base_url=SUMUP_BASE, timeout=SUMUP_TIMEOUT,
                                         headers=_headers(api_key)) as client:
                resp = await client.get(
                    f"/v0.1/merchants/{merchant_code}/readers/{terminal.provider_terminal_id}/status"
                )
                if resp.status_code == 200:
                    return resp.json()
        except Exception as exc:
            logger.warning("SumUp reader status failed for %s: %s", terminal.provider_terminal_id, exc)
        return None

    async def pair_terminal(self, tenant_id, **kwargs: Any) -> dict:
        api_key, merchant_code = _get_credentials()
        pairing_code = kwargs["pairing_code"]
        name = kwargs["name"]
        metadata = kwargs.get("metadata")

        async with httpx.AsyncClient(base_url=SUMUP_BASE, timeout=SUMUP_TIMEOUT,
                                     headers=_headers(api_key)) as client:
            resp = await client.post(
                f"/v0.1/merchants/{merchant_code}/readers",
                json={"pairing_code": pairing_code, "name": name, "metadata": metadata},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "provider_terminal_id": data.get("id"),
                "device": data.get("device"),
                "raw": data,
            }
