from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.models.order import Order, OrderItem
from app.services.order_item_status import normalize_order_item_status
from app.services.order_timing import apply_order_status_timestamps

TERMINAL_ORDER_STATUSES = {"paid", "canceled"}


def derive_order_status_from_items(items: Iterable[OrderItem]) -> str:
    normalized_statuses = [
        normalize_order_item_status(getattr(item, "status", None))
        for item in items
    ]
    active_statuses = [status for status in normalized_statuses if status != "canceled"]

    if not active_statuses:
        return "open"
    if "pending" in active_statuses:
        return "open"
    if "sent" in active_statuses:
        return "sent_to_kitchen"
    if "in_preparation" in active_statuses:
        return "in_preparation"
    if "ready" in active_statuses:
        return "ready"
    if all(status == "served" for status in active_statuses):
        return "served"
    return "open"


def sync_order_status_with_items(order: Order, items: Sequence[OrderItem]) -> str:
    if order.status in TERMINAL_ORDER_STATUSES:
        return order.status

    next_status = derive_order_status_from_items(items)
    if next_status == order.status:
        return order.status

    order.status = next_status
    if next_status == "open":
        # Re-opened orders should no longer be marked as served.
        order.served_at = None
        return next_status

    apply_order_status_timestamps(order, next_status)
    return next_status
