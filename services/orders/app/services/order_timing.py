from __future__ import annotations

from datetime import UTC, datetime

from app.models.order import Order


def apply_order_status_timestamps(order: Order, new_status: str) -> None:
    """Set status timestamp fields based on the target order status."""
    now = datetime.now(UTC)
    opened_at = order.opened_at or now

    if new_status == "sent_to_kitchen":
        order.sent_to_kitchen_at = now
        return

    if new_status == "in_preparation":
        if order.sent_to_kitchen_at is None:
            order.sent_to_kitchen_at = opened_at
        order.in_preparation_at = now
        return

    if new_status == "ready":
        if order.sent_to_kitchen_at is None:
            order.sent_to_kitchen_at = opened_at
        if order.in_preparation_at is None:
            order.in_preparation_at = order.sent_to_kitchen_at or opened_at
        order.ready_at = now
        return

    if new_status == "served":
        if order.sent_to_kitchen_at is None:
            order.sent_to_kitchen_at = opened_at
        if order.in_preparation_at is None:
            order.in_preparation_at = order.sent_to_kitchen_at or opened_at
        if order.ready_at is None:
            order.ready_at = order.in_preparation_at or opened_at
        order.served_at = now
