"""Provider-agnostic payment terminal abstraction."""

from __future__ import annotations

from typing import Any, Protocol

from app.models.order import Order
from app.models.terminal import PaymentTerminal, TerminalPayment


class TerminalProvider(Protocol):
    """Interface for payment terminal providers."""

    provider_name: str

    async def initiate_payment(
        self,
        terminal: PaymentTerminal,
        order: Order,
        amount: float,
        currency: str = "EUR",
        **kwargs: Any,
    ) -> dict:
        """Start a payment. Returns dict with status + provider_data."""
        ...

    async def confirm_payment(self, payment: TerminalPayment) -> str:
        """Confirm a payment (manual terminals). Returns new status."""
        ...

    async def cancel_payment(self, payment: TerminalPayment) -> str:
        """Cancel a payment. Returns new status."""
        ...

    async def get_terminal_status(self, terminal: PaymentTerminal) -> dict | None:
        """Get live status for a terminal (battery, online, etc.). None if unsupported."""
        ...

    async def pair_terminal(self, tenant_id, **kwargs: Any) -> dict:
        """Pair/register a new terminal with the provider. Returns provider-specific data."""
        ...


def get_terminal_provider(provider_name: str) -> TerminalProvider:
    """Factory: return the correct provider implementation."""
    if provider_name == "sumup":
        from app.services.sumup_provider import SumUpTerminalProvider

        return SumUpTerminalProvider()
    if provider_name == "manual":
        from app.services.manual_provider import ManualTerminalProvider

        return ManualTerminalProvider()
    raise ValueError(f"Unbekannter Terminal-Provider: {provider_name}")
