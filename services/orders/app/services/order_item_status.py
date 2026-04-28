from __future__ import annotations

ORDER_ITEM_STATUSES = (
    "pending",
    "sent",
    "in_preparation",
    "ready",
    "served",
    "canceled",
)

_ORDER_ITEM_STATUS_SET = set(ORDER_ITEM_STATUSES)

_ALLOWED_NEXT_STATUSES: dict[str, set[str]] = {
    # Allow forward + manual corrective backward transitions between
    # kitchen workflow steps. Terminal transitions still require explicit action.
    "pending": {"sent", "canceled"},
    "sent": {"pending", "in_preparation", "canceled"},
    "in_preparation": {"sent", "ready", "canceled"},
    # KDS undo: allow moving a ready item back to active preparation.
    "ready": {"in_preparation", "served", "canceled"},
    "served": {"ready", "canceled"},
    "canceled": set(),
}


def normalize_order_item_status(value: str | None) -> str:
    return (value or "").strip().lower()


def is_valid_order_item_status(value: str | None) -> bool:
    return normalize_order_item_status(value) in _ORDER_ITEM_STATUS_SET


def get_allowed_next_order_item_statuses(current_status: str | None) -> list[str]:
    normalized = normalize_order_item_status(current_status)
    return sorted(_ALLOWED_NEXT_STATUSES.get(normalized, set()))


def can_transition_order_item_status(
    current_status: str | None,
    next_status: str | None,
    *,
    allow_noop: bool = True,
) -> bool:
    normalized_current = normalize_order_item_status(current_status)
    normalized_next = normalize_order_item_status(next_status)

    if normalized_current not in _ORDER_ITEM_STATUS_SET:
        return False
    if normalized_next not in _ORDER_ITEM_STATUS_SET:
        return False
    if allow_noop and normalized_current == normalized_next:
        return True

    return normalized_next in _ALLOWED_NEXT_STATUSES.get(normalized_current, set())
