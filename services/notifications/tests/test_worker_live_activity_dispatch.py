"""Tests für den Live-Activity-Routing-Hook im Notifications-Worker."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest


def _ensure_fake_aioapns_loaded() -> None:
    if "aioapns" in sys.modules:
        return
    fake = types.ModuleType("aioapns")
    fake.APNs = type("APNs", (), {})  # type: ignore[attr-defined]
    fake.NotificationRequest = type("NotificationRequest", (), {})  # type: ignore[attr-defined]
    sys.modules["aioapns"] = fake


_ensure_fake_aioapns_loaded()


from app import worker  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_celery_eager(monkeypatch):
    """Sorgt dafür, dass Celery-Tasks im Test sofort ausgeführt werden."""
    monkeypatch.setattr(worker.celery_app.conf, "task_always_eager", True)
    yield


def test_status_map_covers_all_internal_statuses():
    expected = {
        "open",
        "sent_to_kitchen",
        "in_preparation",
        "ready",
        "served",
        "paid",
        "canceled",
    }
    assert expected.issubset(set(worker._LIVE_ACTIVITY_STATUS_MAP.keys()))


def test_dispatch_routes_order_status_changed(monkeypatch):
    captured: dict[str, Any] = {}

    def _fake_delay(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(worker.send_live_activity_update_task, "delay", _fake_delay)
    worker._maybe_dispatch_live_activity_for_order_event(
        "order_status_changed",
        {
            "order_id": "11111111-1111-1111-1111-111111111111",
            "tenant_id": "22222222-2222-2222-2222-222222222222",
            "new_status": "ready",
        },
    )

    assert captured["order_id"] == "11111111-1111-1111-1111-111111111111"
    assert captured["new_status"] == "ready"
    assert captured["tenant_id"] == "22222222-2222-2222-2222-222222222222"


def test_dispatch_routes_order_dot_status(monkeypatch):
    captured: dict[str, Any] = {}

    def _fake_delay(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(worker.send_live_activity_update_task, "delay", _fake_delay)

    worker._maybe_dispatch_live_activity_for_order_event(
        "order.ready",
        {"order_id": "abc", "tenant_id": "xyz"},
    )
    assert captured["new_status"] == "ready"
    assert captured["order_id"] == "abc"


def test_dispatch_ignores_unknown_event(monkeypatch):
    called = {"n": 0}

    def _fake_delay(**kwargs: Any) -> None:
        called["n"] += 1

    monkeypatch.setattr(worker.send_live_activity_update_task, "delay", _fake_delay)

    worker._maybe_dispatch_live_activity_for_order_event(
        "reservation.confirmed", {"order_id": "abc"}
    )
    worker._maybe_dispatch_live_activity_for_order_event(
        "order.unknown_status", {"order_id": "abc"}
    )
    worker._maybe_dispatch_live_activity_for_order_event("order.ready", {})  # missing order_id

    assert called["n"] == 0


def test_terminal_status_schedules_end_task(monkeypatch):
    captured: dict[str, Any] = {}

    def _fake_apply_async(**kwargs: Any) -> None:
        captured.update(kwargs)

    def _fake_fetch(_order_id: str) -> list[dict]:
        return [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "push_token": "push-1",
                "tenant_id": "tenant-1",
            }
        ]

    monkeypatch.setattr(worker, "_fetch_active_live_activity_tokens", _fake_fetch)

    def _consume_coro(coro: Any) -> None:
        # Schließt die Coroutine, damit kein "never awaited"-Warning entsteht.
        try:
            coro.close()
        except Exception:
            pass

    monkeypatch.setattr(worker, "_run_async", _consume_coro)
    monkeypatch.setattr(worker.end_live_activity_task, "apply_async", _fake_apply_async)

    result = worker.send_live_activity_update_task(
        order_id="o1",
        new_status="served",
        tenant_id="t1",
    )

    assert result == {"sent": 1, "tokens": 1}
    assert "kwargs" in captured
    assert captured["kwargs"]["final_status"] == "served"
    assert captured["countdown"] >= 0
