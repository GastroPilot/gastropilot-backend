"""Race-condition regression test for orders-service create endpoint logic."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.routes import orders as orders_router


class _SharedCommitState:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._committed_once = False

    async def commit_once_else_conflict(self) -> None:
        async with self._lock:
            if not self._committed_once:
                self._committed_once = True
                return
            raise IntegrityError(
                "INSERT INTO orders (...) VALUES (...)",
                {},
                Exception(
                    'duplicate key value violates unique constraint "uq_orders_active_reservation"'
                ),
            )


class _FakeSession:
    def __init__(self, state: _SharedCommitState) -> None:
        self._state = state

    def add(self, _obj) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        await self._state.commit_once_else_conflict()

    async def refresh(self, _obj) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.mark.asyncio
async def test_parallel_create_order_maps_unique_conflict_to_409(monkeypatch):
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

    monkeypatch.setattr(
        orders_router,
        "_resolve_order_table_assignment_from_reservation",
        _resolve,
    )
    monkeypatch.setattr(orders_router, "_find_active_order_conflict", _no_conflict)
    monkeypatch.setattr(orders_router.manager, "broadcast_to_tenant", _noop_broadcast)

    request = SimpleNamespace(state=SimpleNamespace(tenant_id=tenant_id))
    current_user = SimpleNamespace(id=user_id)
    payload = orders_router.OrderCreate(
        reservation_id=reservation_id,
        items=[],
    )

    shared_state = _SharedCommitState()

    async def _invoke_once():
        session = _FakeSession(shared_state)
        return await orders_router.create_order(
            data=payload,
            request=request,
            session=session,
            current_user=current_user,
        )

    results = await asyncio.gather(_invoke_once(), _invoke_once(), return_exceptions=True)

    success_results = [result for result in results if not isinstance(result, Exception)]
    exceptions = [result for result in results if isinstance(result, Exception)]

    assert len(success_results) == 1
    assert len(exceptions) == 1
    assert isinstance(exceptions[0], HTTPException)
    assert exceptions[0].status_code == 409
    assert exceptions[0].detail == "An active order already exists for this reservation or table"
