"""Tests für apply_order_status_timestamps.

Deckt den persistierten ETA-Pfad ab, der bei einem Status-Übergang nach
``sent_to_kitchen`` gesetzt wird (Issue #40 BE-4).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.services.order_timing import (
    KITCHEN_DEFAULT_PREP_MINUTES,
    apply_order_status_timestamps,
)


class _FakeOrder:
    """Minimaler Order-Stub – nur die Felder, die ``apply_order_status_timestamps`` anfasst."""

    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.status = "open"
        self.opened_at: datetime | None = None
        self.sent_to_kitchen_at: datetime | None = None
        self.in_preparation_at: datetime | None = None
        self.ready_at: datetime | None = None
        self.served_at: datetime | None = None
        self.estimated_completion_at: datetime | None = None


def test_sent_to_kitchen_sets_eta_to_default_offset_from_now():
    order = _FakeOrder()

    before = datetime.now(UTC)
    apply_order_status_timestamps(order, "sent_to_kitchen")
    after = datetime.now(UTC)

    assert order.sent_to_kitchen_at is not None
    assert order.estimated_completion_at is not None

    delta = order.estimated_completion_at - order.sent_to_kitchen_at
    assert delta == timedelta(minutes=KITCHEN_DEFAULT_PREP_MINUTES)

    # ETA muss zwischen now()+default und after+default liegen.
    assert order.estimated_completion_at >= before + timedelta(minutes=KITCHEN_DEFAULT_PREP_MINUTES)
    assert order.estimated_completion_at <= after + timedelta(minutes=KITCHEN_DEFAULT_PREP_MINUTES)


def test_sent_to_kitchen_does_not_overwrite_existing_eta():
    """Wenn der AI-Service die Spalte schon gesetzt hat, bleibt sein Wert stehen."""
    order = _FakeOrder()
    ai_estimate = datetime.now(UTC) + timedelta(minutes=42)
    order.estimated_completion_at = ai_estimate

    apply_order_status_timestamps(order, "sent_to_kitchen")

    assert order.estimated_completion_at == ai_estimate


def test_in_preparation_also_seeds_eta_when_skipping_sent_to_kitchen():
    """Falls der Workflow ``sent_to_kitchen`` überspringt und direkt
    ``in_preparation`` setzt (z.B. durch Direkt-Bedienung), soll die ETA
    trotzdem gefüllt werden."""
    order = _FakeOrder()

    apply_order_status_timestamps(order, "in_preparation")

    assert order.estimated_completion_at is not None
    assert order.in_preparation_at is not None
    delta = order.estimated_completion_at - order.in_preparation_at
    assert delta == timedelta(minutes=KITCHEN_DEFAULT_PREP_MINUTES)


def test_ready_does_not_set_eta():
    """Statuswechsel auf ``ready`` ist Endpunkt der Heizphase – kein ETA-Set."""
    order = _FakeOrder()

    apply_order_status_timestamps(order, "ready")

    assert order.ready_at is not None
    assert order.estimated_completion_at is None
