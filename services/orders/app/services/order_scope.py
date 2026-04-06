from __future__ import annotations

from collections.abc import Iterable

# Scope foundation for the kitchen/order refactor:
# - order.status is lifecycle-oriented (open -> paid/canceled)
# - kitchen progress is tracked per order item
# Legacy order-level kitchen statuses remain temporarily for compatibility.

ORDER_LIFECYCLE_STATUSES = {"open", "paid", "canceled"}
ORDER_TERMINAL_STATUSES = {"paid", "canceled"}
ORDER_LEGACY_KITCHEN_PROGRESS_STATUSES = {
    "sent_to_kitchen",
    "in_preparation",
    "ready",
    "served",
}


def normalize_order_status(value: str | None) -> str:
    return (value or "").strip().lower()


def is_terminal_order_status(status: str | None) -> bool:
    return normalize_order_status(status) in ORDER_TERMINAL_STATUSES


def is_lifecycle_order_status(status: str | None) -> bool:
    return normalize_order_status(status) in ORDER_LIFECYCLE_STATUSES


def is_legacy_kitchen_progress_order_status(status: str | None) -> bool:
    return normalize_order_status(status) in ORDER_LEGACY_KITCHEN_PROGRESS_STATUSES


def is_order_active(status: str | None, payment_status: str | None) -> bool:
    normalized_payment_status = (payment_status or "").strip().lower()
    return not is_terminal_order_status(status) and normalized_payment_status != "paid"


def has_only_lifecycle_statuses(statuses: Iterable[str]) -> bool:
    return all(is_lifecycle_order_status(status) for status in statuses)
