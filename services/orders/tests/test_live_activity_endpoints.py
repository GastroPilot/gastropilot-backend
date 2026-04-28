"""Tests für Guest-JWT-basierte Live-Activity-Endpunkte.

Wir mocken die DB-Session vollständig (FakeSession) und rufen die
Endpoints direkt auf. Damit testen wir Auth-Path, Tenant-Isolation
und Upsert-Verhalten ohne reale Postgres-Instanz.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.routes import public_guest_orders
from app.core.guest_deps import GuestIdentity
from app.core.guest_repository import GuestOrdersRepository


def _repo(session: FakeSession, guest: GuestIdentity) -> GuestOrdersRepository:
    """Build a repo with the in-memory FakeSession; mirrors what FastAPI
    constructs via ``get_guest_orders_repo`` at request time."""
    return GuestOrdersRepository(db=session, guest=guest)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Mini-Fakes
# ---------------------------------------------------------------------------


class _FakeOrder:
    def __init__(
        self,
        *,
        order_id: uuid.UUID,
        tenant_id: uuid.UUID,
        guest_id: uuid.UUID | None,
    ) -> None:
        self.id = order_id
        self.tenant_id = tenant_id
        self.guest_id = guest_id
        self.order_number = "TEST-001"
        self.status = "in_preparation"
        self.subtotal = 10.0
        self.tax_amount = 1.9
        self.tip_amount = 0.0
        self.total = 11.9
        self.payment_status = "unpaid"
        self.opened_at = None
        self.created_at = None
        self.updated_at = None


@dataclass
class _ScalarRowResult:
    value: Any

    def scalar_one_or_none(self) -> Any:
        return self.value

    def first(self) -> Any:
        return self.value

    def scalars(self) -> _ScalarRowResult:
        return self


@dataclass
class _IterableScalars:
    items: list[Any]

    def all(self) -> list[Any]:
        return list(self.items)


class _ResultWithScalars:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None

    def first(self) -> Any:
        return self._items[0] if self._items else None

    def scalars(self) -> _IterableScalars:
        return _IterableScalars(self._items)


class FakeSession:
    """Minimaler AsyncSession-Stub.

    Die ``execute``-Aufrufe werden in der Reihenfolge bedient, in der sie
    im Endpoint vorkommen. Tests legen die Reihenfolge in ``responses`` an.
    """

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.executed: list[Any] = []
        self.committed = False

    async def execute(self, statement: Any, params: dict | None = None) -> Any:
        self.executed.append((statement, params))
        if not self._responses:
            raise AssertionError(f"Unerwarteter execute-Call ohne queued response: {statement}")
        return self._responses.pop(0)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Auth-Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_guest_rejects_missing_token():
    from types import SimpleNamespace

    from app.core.guest_deps import get_current_guest

    request = SimpleNamespace(state=SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        await get_current_guest(
            request=request,  # type: ignore[arg-type]
            credentials=None,
            access_token=None,
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_guest_rejects_non_guest_role(monkeypatch):
    from types import SimpleNamespace

    from fastapi.security import HTTPAuthorizationCredentials

    from app.core.guest_deps import get_current_guest

    monkeypatch.setattr(
        "app.core.guest_deps.verify_token",
        lambda token: {"role": "owner", "sub": str(uuid.uuid4())},
    )

    request = SimpleNamespace(state=SimpleNamespace())
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="x")

    with pytest.raises(HTTPException) as exc:
        await get_current_guest(
            request=request,  # type: ignore[arg-type]
            credentials=creds,
            access_token=None,
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_guest_accepts_guest_role(monkeypatch):
    from types import SimpleNamespace

    from fastapi.security import HTTPAuthorizationCredentials

    from app.core.guest_deps import get_current_guest

    guest_uuid = uuid.uuid4()
    monkeypatch.setattr(
        "app.core.guest_deps.verify_token",
        lambda token: {"role": "guest", "sub": str(guest_uuid)},
    )
    request = SimpleNamespace(state=SimpleNamespace())
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="x")

    identity = await get_current_guest(
        request=request,  # type: ignore[arg-type]
        credentials=creds,
        access_token=None,
    )
    assert identity.id == guest_uuid


# ---------------------------------------------------------------------------
# Tenant-Isolation: Order eines fremden Guests darf nicht abrufbar sein.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_token_404_for_foreign_order(monkeypatch):
    """Order existiert, gehört aber nicht zum aufrufenden Guest → 404."""
    order_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    foreign_guest_id_in_orders = uuid.uuid4()

    fake_order = _FakeOrder(
        order_id=order_id,
        tenant_id=tenant_id,
        guest_id=foreign_guest_id_in_orders,
    )

    session = FakeSession(
        responses=[
            _ResultWithScalars([fake_order]),  # SELECT Order
            _ResultWithScalars([]),  # SELECT 1 FROM guests ... (empty → not own)
        ]
    )
    guest = GuestIdentity(id=uuid.uuid4(), raw_payload={})

    body = public_guest_orders.LiveActivityTokenBody(push_token="x" * 32)

    with pytest.raises(HTTPException) as exc:
        await public_guest_orders.register_live_activity_token(
            order_id=order_id, body=body, repo=_repo(session, guest)
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_register_token_404_when_order_missing():
    order_id = uuid.uuid4()
    session = FakeSession(responses=[_ResultWithScalars([])])
    guest = GuestIdentity(id=uuid.uuid4(), raw_payload={})
    body = public_guest_orders.LiveActivityTokenBody(push_token="x" * 32)

    with pytest.raises(HTTPException) as exc:
        await public_guest_orders.register_live_activity_token(
            order_id=order_id, body=body, repo=_repo(session, guest)
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Happy-Path Upsert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_token_upsert_calls_commit():
    order_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    guest_id_in_orders = uuid.uuid4()
    guest_profile_id = uuid.uuid4()

    fake_order = _FakeOrder(
        order_id=order_id,
        tenant_id=tenant_id,
        guest_id=guest_id_in_orders,
    )
    session = FakeSession(
        responses=[
            _ResultWithScalars([fake_order]),  # SELECT Order
            _ResultWithScalars([(1,)]),  # SELECT 1 FROM guests → match
            _ResultWithScalars([]),  # INSERT ... ON CONFLICT DO UPDATE
        ]
    )
    guest = GuestIdentity(id=guest_profile_id, raw_payload={})
    body = public_guest_orders.LiveActivityTokenBody(push_token="abc12345xyz")

    response = await public_guest_orders.register_live_activity_token(
        order_id=order_id, body=body, repo=_repo(session, guest)
    )
    assert response.status_code == 204
    assert session.committed is True
    # Mind. 3 execute calls (Order, ownership, upsert)
    assert len(session.executed) >= 3


# ---------------------------------------------------------------------------
# DELETE-Endpoint: idempotent + Soft-Delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_token_idempotent_when_not_present():
    order_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    guest_id_in_orders = uuid.uuid4()

    fake_order = _FakeOrder(
        order_id=order_id,
        tenant_id=tenant_id,
        guest_id=guest_id_in_orders,
    )
    session = FakeSession(
        responses=[
            _ResultWithScalars([fake_order]),
            _ResultWithScalars([(1,)]),  # ownership match
            _ResultWithScalars([]),  # SELECT LiveActivityToken → empty
        ]
    )
    guest = GuestIdentity(id=uuid.uuid4(), raw_payload={})

    response = await public_guest_orders.end_live_activity_token(
        order_id=order_id,
        push_token="abc12345xyz",
        repo=_repo(session, guest),
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_delete_token_sets_ended_at_when_present():
    order_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    guest_id_in_orders = uuid.uuid4()

    fake_order = _FakeOrder(
        order_id=order_id,
        tenant_id=tenant_id,
        guest_id=guest_id_in_orders,
    )

    class _FakeToken:
        ended_at = None

    fake_token = _FakeToken()
    session = FakeSession(
        responses=[
            _ResultWithScalars([fake_order]),
            _ResultWithScalars([(1,)]),
            _ResultWithScalars([fake_token]),
        ]
    )
    guest = GuestIdentity(id=uuid.uuid4(), raw_payload={})

    await public_guest_orders.end_live_activity_token(
        order_id=order_id,
        push_token="abc12345xyz",
        repo=_repo(session, guest),
    )
    assert fake_token.ended_at is not None
    assert session.committed is True


# ---------------------------------------------------------------------------
# GET /me/orders/{order_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_my_order_happy_path():
    order_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    guest_id_in_orders = uuid.uuid4()

    fake_order = _FakeOrder(
        order_id=order_id,
        tenant_id=tenant_id,
        guest_id=guest_id_in_orders,
    )

    class _FakeItem:
        id = uuid.uuid4()
        item_name = "Pizza"
        quantity = 1
        unit_price = 10.0
        total_price = 10.0
        status = "ready"
        notes = None

    session = FakeSession(
        responses=[
            _ResultWithScalars([fake_order]),
            _ResultWithScalars([(1,)]),  # ownership (cached for the rest of the request)
            _ResultWithScalars([_FakeItem()]),  # items
            _ResultWithScalars([("Test Restaurant",)]),  # restaurant name
        ]
    )
    guest = GuestIdentity(id=uuid.uuid4(), raw_payload={})

    payload = await public_guest_orders.get_my_order(order_id=order_id, repo=_repo(session, guest))
    assert payload["id"] == str(order_id)
    assert payload["restaurant_name"] == "Test Restaurant"
    assert payload["items"][0]["name"] == "Pizza"
    # Ownership cache prevents the second call (list_order_items) from
    # re-fetching the order — exactly 4 execute calls expected.
    assert len(session.executed) == 4


@pytest.mark.asyncio
async def test_get_my_order_404_for_other_tenant():
    """Cross-Tenant: gleicher Guest, aber Order gehört einer anderen guests-Zeile.

    Dies entspricht dem realen Mehrmandanten-Szenario: Tenant A und Tenant B
    haben jeweils eigene ``guests``-Einträge. Das ``guest_profile_id`` matcht
    nur, wenn der Guest tatsächlich im betreffenden Tenant einen Datensatz
    besitzt – sonst 404.
    """
    order_id = uuid.uuid4()
    fake_order = _FakeOrder(
        order_id=order_id,
        tenant_id=uuid.uuid4(),
        guest_id=uuid.uuid4(),
    )
    session = FakeSession(
        responses=[
            _ResultWithScalars([fake_order]),
            _ResultWithScalars([]),  # ownership lookup empty (cross-tenant guest)
        ]
    )
    guest = GuestIdentity(id=uuid.uuid4(), raw_payload={})

    with pytest.raises(HTTPException) as exc:
        await public_guest_orders.get_my_order(order_id=order_id, repo=_repo(session, guest))
    assert exc.value.status_code == 404
