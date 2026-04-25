"""Unit tests for the authenticated guest-reservation-detail endpoint.

Verifies that `GET /public/me/reservations/<id>` returns `has_outdoor_table`
and the restaurant location fields required by the Gäste-App weather
banner.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api.routes import guest_profile as gp


def _fake_table(table_id: uuid.UUID, *, is_outdoor: bool, number: str = "T") -> SimpleNamespace:
    return SimpleNamespace(id=table_id, is_outdoor=is_outdoor, number=number)


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

    def one_or_none(self):
        if len(self._rows) > 1:
            raise RuntimeError("multiple rows")
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeSession:
    """Minimal async session returning pre-programmed rows per entity hit."""

    def __init__(self, handlers):
        self._handlers = handlers

    async def execute(self, stmt):
        column_descs = getattr(stmt, "column_descriptions", None) or []
        entity = column_descs[0]["entity"] if column_descs else None
        # The reservation-detail route joins Reservation + Restaurant; its
        # first column_description is Reservation. Fall back to "select"
        # key for the joined select.
        key = entity
        handler = self._handlers.get(key)
        if handler is None:
            raise AssertionError(f"no handler for {key!r}; stmt={stmt}")
        return _FakeExecuteResult(handler(stmt))


@pytest.mark.asyncio
async def test_get_guest_reservation_detail_exposes_outdoor_flag_and_location():
    from app.models.reservation import Guest, Reservation
    from app.models.restaurant import Restaurant, Table
    from app.models.table_config import ReservationTable

    tenant_id = uuid.uuid4()
    reservation_id = uuid.uuid4()
    table_id = uuid.uuid4()
    guest_db_id = uuid.uuid4()
    guest_profile_id = uuid.uuid4()

    restaurant = SimpleNamespace(
        id=tenant_id,
        name="Bistro Garten",
        slug="bistro-garten",
        city="Berlin",
        zip_code="10115",
    )
    reservation = SimpleNamespace(
        id=reservation_id,
        tenant_id=tenant_id,
        guest_id=guest_db_id,
        confirmation_code="OUTDOOR1",
        status="confirmed",
        guest_name="Guest",
        guest_email="g@example.com",
        guest_phone=None,
        party_size=2,
        start_at=datetime.now(UTC) + timedelta(hours=20),
        table_id=table_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    guest_row = SimpleNamespace(id=guest_db_id, guest_profile_id=guest_profile_id)
    outdoor_table = _fake_table(table_id, is_outdoor=True, number="5")

    handlers = {
        Guest: lambda _stmt: [guest_row],
        # Reservation+Restaurant join — route consumes it as one_or_none
        # over tuples. `.all()` returns the paired row; `.one_or_none()`
        # picks the first.
        Reservation: lambda _stmt: [(reservation, restaurant)],
        ReservationTable: lambda _stmt: [table_id],
        Table: lambda _stmt: [outdoor_table],
    }

    guest = SimpleNamespace(id=guest_profile_id)
    result = await gp.get_guest_reservation_detail(
        reservation_id=str(reservation_id),
        guest=guest,
        db=_FakeSession(handlers),
    )

    assert result["has_outdoor_table"] is True
    assert result["restaurant_city"] == "Berlin"
    assert result["restaurant_zip_code"] == "10115"
    assert result["confirmation_code"] == "OUTDOOR1"
    assert result["restaurant_name"] == "Bistro Garten"


@pytest.mark.asyncio
async def test_get_guest_reservation_detail_indoor_table_returns_false():
    from app.models.reservation import Guest, Reservation
    from app.models.restaurant import Restaurant, Table
    from app.models.table_config import ReservationTable

    tenant_id = uuid.uuid4()
    reservation_id = uuid.uuid4()
    table_id = uuid.uuid4()
    guest_db_id = uuid.uuid4()
    guest_profile_id = uuid.uuid4()

    restaurant = SimpleNamespace(
        id=tenant_id,
        name="Indoor Spot",
        slug="indoor-spot",
        city="München",
        zip_code=None,
    )
    reservation = SimpleNamespace(
        id=reservation_id,
        tenant_id=tenant_id,
        guest_id=guest_db_id,
        confirmation_code="INDOOR01",
        status="confirmed",
        guest_name="Guest",
        guest_email="g@example.com",
        guest_phone=None,
        party_size=3,
        start_at=datetime.now(UTC) + timedelta(hours=5),
        table_id=table_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    guest_row = SimpleNamespace(id=guest_db_id, guest_profile_id=guest_profile_id)
    indoor_table = _fake_table(table_id, is_outdoor=False, number="2")

    handlers = {
        Guest: lambda _stmt: [guest_row],
        Reservation: lambda _stmt: [(reservation, restaurant)],
        ReservationTable: lambda _stmt: [table_id],
        Table: lambda _stmt: [indoor_table],
    }

    guest = SimpleNamespace(id=guest_profile_id)
    result = await gp.get_guest_reservation_detail(
        reservation_id=str(reservation_id),
        guest=guest,
        db=_FakeSession(handlers),
    )

    assert result["has_outdoor_table"] is False
    assert result["restaurant_city"] == "München"
    assert result["restaurant_zip_code"] is None


@pytest.mark.asyncio
async def test_get_guest_reservation_detail_pending_without_table():
    from app.models.reservation import Guest, Reservation
    from app.models.restaurant import Restaurant, Table
    from app.models.table_config import ReservationTable

    tenant_id = uuid.uuid4()
    reservation_id = uuid.uuid4()
    guest_db_id = uuid.uuid4()
    guest_profile_id = uuid.uuid4()

    restaurant = SimpleNamespace(
        id=tenant_id,
        name="Pending Place",
        slug="pending-place",
        city="Hamburg",
        zip_code="20095",
    )
    reservation = SimpleNamespace(
        id=reservation_id,
        tenant_id=tenant_id,
        guest_id=guest_db_id,
        confirmation_code="PENDING0",
        status="pending",
        guest_name="Guest",
        guest_email="g@example.com",
        guest_phone=None,
        party_size=2,
        start_at=datetime.now(UTC) + timedelta(hours=48),
        table_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    guest_row = SimpleNamespace(id=guest_db_id, guest_profile_id=guest_profile_id)

    handlers = {
        Guest: lambda _stmt: [guest_row],
        Reservation: lambda _stmt: [(reservation, restaurant)],
        ReservationTable: lambda _stmt: [],
        Table: lambda _stmt: [],
    }

    guest = SimpleNamespace(id=guest_profile_id)
    result = await gp.get_guest_reservation_detail(
        reservation_id=str(reservation_id),
        guest=guest,
        db=_FakeSession(handlers),
    )

    assert result["has_outdoor_table"] is False
    assert result["restaurant_city"] == "Hamburg"
