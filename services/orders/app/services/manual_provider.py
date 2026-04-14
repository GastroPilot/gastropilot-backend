"""Manual terminal provider — for non-API-connected card terminals."""

from __future__ import annotations

from typing import Any

from app.models.order import Order
from app.models.terminal import PaymentTerminal, TerminalPayment


class ManualTerminalProvider:
    provider_name = "manual"

    async def initiate_payment(
        self,
        terminal: PaymentTerminal,
        order: Order,
        amount: float,
        currency: str = "EUR",
        **kwargs: Any,
    ) -> dict:
        return {
            "status": "awaiting_confirmation",
            "provider_data": {
                "terminal_name": terminal.name,
                "note": "Bitte Zahlung am Terminal durchführen und bestätigen.",
            },
        }

    async def confirm_payment(self, payment: TerminalPayment) -> str:
        return "successful"

    async def cancel_payment(self, payment: TerminalPayment) -> str:
        return "canceled"

    async def get_terminal_status(self, terminal: PaymentTerminal) -> dict | None:
        return None  # Manual terminals have no live status

    async def pair_terminal(self, tenant_id, **kwargs: Any) -> dict:
        return {}  # No pairing needed for manual terminals
