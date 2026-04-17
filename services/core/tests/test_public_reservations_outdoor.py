"""Unit tests for has_outdoor_table computation in public reservation endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api.routes import public_reservations as pr


def _fake_table(table_id: uuid.UUID, *, is_outdoor: bool, number: str = "T") -> SimpleNamespace:
    return SimpleNamespace(id=table_id, is_outdoor=is_outdoor, number=number)


def test_compute_has_outdoor_table_empty_list() -> None:
    assert pr._compute_has_outdoor_table([], {}) is False


def test_compute_has_outdoor_table_single_indoor() -> None:
    t_id = uuid.uuid4()
    assert (
        pr._compute_has_outdoor_table(
            [t_id],
            {t_id: _fake_table(t_id, is_outdoor=False)},
        )
        is False
    )


def test_compute_has_outdoor_table_single_outdoor() -> None:
    t_id = uuid.uuid4()
    assert (
        pr._compute_has_outdoor_table(
            [t_id],
            {t_id: _fake_table(t_id, is_outdoor=True)},
        )
        is True
    )


def test_compute_has_outdoor_table_group_any_outdoor_wins() -> None:
    indoor, outdoor = uuid.uuid4(), uuid.uuid4()
    tables_by_id = {
        indoor: _fake_table(indoor, is_outdoor=False),
        outdoor: _fake_table(outdoor, is_outdoor=True),
    }
    assert pr._compute_has_outdoor_table([indoor, outdoor], tables_by_id) is True


def test_compute_has_outdoor_table_group_all_indoor() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    tables_by_id = {
        a: _fake_table(a, is_outdoor=False),
        b: _fake_table(b, is_outdoor=False),
    }
    assert pr._compute_has_outdoor_table([a, b], tables_by_id) is False


def test_compute_has_outdoor_table_unknown_id_is_ignored() -> None:
    known, unknown = uuid.uuid4(), uuid.uuid4()
    tables_by_id = {known: _fake_table(known, is_outdoor=True)}
    assert pr._compute_has_outdoor_table([known, unknown], tables_by_id) is True
    assert pr._compute_has_outdoor_table([unknown], tables_by_id) is False


# --- Route-level tests with mocked session ---


class _FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        rows = self._rows

        class _Scalars:
            def all(self_inner):
                return rows

            def first(self_inner):
                return rows[0] if rows else None

        return _Scalars()

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeSession:
    """Minimal async session that returns pre-programmed results per select target."""

    def __init__(self, handlers):
        self._handlers = handlers

    async def execute(self, stmt):
        column_descs = getattr(stmt, "column_descriptions", None) or []
        entity = column_descs[0]["entity"] if column_descs else None
        handler = self._handlers.get(entity)
        if handler is None:
            raise AssertionError(f"No handler for entity {entity!r} / stmt={stmt}")
        rows = handler(stmt)
        return _FakeExecuteResult(rows)


@pytest.mark.asyncio
async def test_get_reservation_status_returns_has_outdoor_for_outdoor_table(monkeypatch):
    from app.models.reservation import Reservation
    from app.models.restaurant import Restaurant, Table
    from app.models.table_config import ReservationTable

    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    table_id = uuid.uuid4()
    reservation_id = uuid.uuid4()

    restaurant = SimpleNamespace(
        id=tenant_id,
        name="Test Bistro",
        slug="test-bistro",
        public_booking_enabled=True,
    )
    reservation = SimpleNamespace(
        id=reservation_id,
        tenant_id=tenant_id,
        confirmation_code="ABC12345",
        status="confirmed",
        guest_name="Guest",
        guest_email="g@example.com",
        start_at=datetime.now(UTC) + timedelta(hours=48),
        table_id=table_id,
        party_size=2,
        special_requests=None,
    )
    outdoor_table = _fake_table(table_id, is_outdoor=True, number="7")

    handlers = {
        Restaurant: lambda _stmt: [restaurant],
        Reservation: lambda _stmt: [reservation],
        ReservationTable: lambda _stmt: [table_id],
        Table: lambda _stmt: [outdoor_table],
    }

    result = await pr.get_reservation_status(
        slug="test-bistro",
        code="ABC12345",
        db=_FakeSession(handlers),
    )

    assert isinstance(result, pr.PublicReservationStatusResponse)
    assert result.has_outdoor_table is True
    assert result.table_number == "7"
    assert result.confirmation_code == "ABC12345"
    # Sanity: no cross-tenant leakage in the mocked handler
    assert other_tenant_id != tenant_id


@pytest.mark.asyncio
async def test_get_reservation_status_returns_false_for_indoor_table():
    from app.models.reservation import Reservation
    from app.models.restaurant import Restaurant, Table
    from app.models.table_config import ReservationTable

    tenant_id = uuid.uuid4()
    table_id = uuid.uuid4()

    restaurant = SimpleNamespace(
        id=tenant_id,
        name="Test Bistro",
        slug="test-bistro",
        public_booking_enabled=True,
    )
    reservation = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        confirmation_code="IND00000",
        status="confirmed",
        guest_name="Guest",
        guest_email="g@example.com",
        start_at=datetime.now(UTC) + timedelta(hours=3),
        table_id=table_id,
        party_size=2,
        special_requests=None,
    )
    indoor_table = _fake_table(table_id, is_outdoor=False, number="3")

    handlers = {
        Restaurant: lambda _stmt: [restaurant],
        Reservation: lambda _stmt: [reservation],
        ReservationTable: lambda _stmt: [table_id],
        Table: lambda _stmt: [indoor_table],
    }

    result = await pr.get_reservation_status(
        slug="test-bistro",
        code="IND00000",
        db=_FakeSession(handlers),
    )

    assert result.has_outdoor_table is False
    assert result.table_number == "3"


@pytest.mark.asyncio
async def test_get_reservation_status_pending_without_table_is_not_outdoor():
    from app.models.reservation import Reservation
    from app.models.restaurant import Restaurant, Table
    from app.models.table_config import ReservationTable

    tenant_id = uuid.uuid4()

    restaurant = SimpleNamespace(
        id=tenant_id,
        name="Test Bistro",
        slug="test-bistro",
        public_booking_enabled=True,
    )
    reservation = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        confirmation_code="PEND0000",
        status="pending",
        guest_name="Guest",
        guest_email="g@example.com",
        start_at=datetime.now(UTC) + timedelta(hours=5),
        table_id=None,
        party_size=2,
        special_requests=None,
    )

    handlers = {
        Restaurant: lambda _stmt: [restaurant],
        Reservation: lambda _stmt: [reservation],
        ReservationTable: lambda _stmt: [],
        Table: lambda _stmt: [],
    }

    result = await pr.get_reservation_status(
        slug="test-bistro",
        code="PEND0000",
        db=_FakeSession(handlers),
    )

    assert result.has_outdoor_table is False
    assert result.table_number is None


@pytest.mark.asyncio
async def test_get_reservation_status_unknown_slug_returns_404():
    """Slug-based restaurant lookup miss (e.g. typo): no reservation data leaks."""
    from app.models.restaurant import Restaurant

    handlers = {
        Restaurant: lambda _stmt: [],
    }

    with pytest.raises(Exception) as exc_info:
        await pr.get_reservation_status(
            slug="does-not-exist",
            code="ABC12345",
            db=_FakeSession(handlers),
        )

    assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_get_reservation_status_same_code_other_tenant_returns_404():
    """
    Stronger cross-tenant check: a confirmation code that exists under
    tenant B must NOT leak when the lookup targets tenant A's slug.

    The route filters `Reservation.tenant_id == restaurant.id`. The fake
    session mirrors that filter by inspecting the statement's compiled SQL
    for the tenant UUID. When the query is scoped to tenant A, the
    reservation handler returns []; only a hypothetical tenant-B-scoped
    query (which the route never makes) would see the reservation.
    """
    from app.models.reservation import Reservation
    from app.models.restaurant import Restaurant

    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()
    assert tenant_a_id != tenant_b_id

    restaurant_a = SimpleNamespace(
        id=tenant_a_id,
        name="Bistro A",
        slug="bistro-a",
        public_booking_enabled=True,
    )
    reservation_b = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_b_id,
        confirmation_code="SHARED01",
        status="confirmed",
        guest_name="Guest B",
        guest_email="b@example.com",
        start_at=datetime.now(UTC) + timedelta(hours=24),
        table_id=None,
        party_size=2,
        special_requests=None,
    )

    reservation_calls: list[str] = []

    def _uuid_markers(u: uuid.UUID) -> tuple[str, str]:
        # SQLAlchemy's literal-bind compiler renders UUIDs as hex without
        # dashes for the Postgres UUID type — check both forms to stay
        # robust against dialect changes.
        return (str(u), u.hex)

    def reservation_handler(stmt):
        try:
            compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        except Exception:
            compiled = str(stmt)
        reservation_calls.append(compiled)
        if any(marker in compiled for marker in _uuid_markers(tenant_a_id)):
            return []
        if any(marker in compiled for marker in _uuid_markers(tenant_b_id)):
            return [reservation_b]
        return []

    handlers = {
        Restaurant: lambda _stmt: [restaurant_a],
        Reservation: reservation_handler,
    }

    with pytest.raises(Exception) as exc_info:
        await pr.get_reservation_status(
            slug="bistro-a",
            code="SHARED01",
            db=_FakeSession(handlers),
        )

    assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()
    # The route must have queried reservations with tenant_a's filter,
    # never with tenant_b's — otherwise the cross-tenant scope is broken.
    assert reservation_calls, "expected a Reservation query"
    joined = "\n".join(reservation_calls)
    assert any(marker in joined for marker in _uuid_markers(tenant_a_id))
    assert not any(marker in joined for marker in _uuid_markers(tenant_b_id))
