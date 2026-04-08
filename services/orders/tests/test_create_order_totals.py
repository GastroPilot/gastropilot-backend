"""Regression test: order totals are recalculated during create."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.api.routes import orders as orders_router


class _FakeSession:
    def add(self, _obj) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.mark.asyncio
async def test_create_order_recalculates_totals(monkeypatch):
    tenant_id = uuid.uuid4()
    reservation_id = uuid.uuid4()
    table_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async def _resolve(*_args, **_kwargs):
        return table_id, [table_id]

    async def _no_conflict(*_args, **_kwargs):
        return None

    async def _noop_broadcast(*_args, **_kwargs):
        return None

    recalc_calls = {"count": 0}

    async def _recalc(order, _session):
        recalc_calls["count"] += 1
        order.subtotal = 11.0
        order.tax_amount = 1.76
        order.total = 11.0

    monkeypatch.setattr(
        orders_router,
        "_resolve_order_table_assignment_from_reservation",
        _resolve,
    )
    monkeypatch.setattr(orders_router, "_find_active_order_conflict", _no_conflict)
    monkeypatch.setattr(orders_router.manager, "broadcast_to_tenant", _noop_broadcast)
    monkeypatch.setattr(orders_router, "_recalculate_order_totals", _recalc)

    request = SimpleNamespace(state=SimpleNamespace(tenant_id=tenant_id))
    current_user = SimpleNamespace(id=user_id)
    payload = orders_router.OrderCreate(
        reservation_id=reservation_id,
        items=[
            {
                "item_name": "Suppe",
                "quantity": 1,
                "unit_price": 11.0,
                "tax_rate": 0.07,
            }
        ],
    )

    result = await orders_router.create_order(
        data=payload,
        request=request,
        session=_FakeSession(),
        current_user=current_user,
    )

    assert recalc_calls["count"] == 1
    assert result["total"] == 11.0

