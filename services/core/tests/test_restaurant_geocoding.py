"""Unit-Tests für das best-effort Nominatim-Geocoding bei Tenant-Create/Update.

Die Tests mocken `geocode_address`, sodass keine HTTP-Calls passieren. Sie
verifizieren:

- Tenant-Create mit Adresse → settings.latitude/longitude werden gesetzt.
- Restaurant-Patch mit geänderter `street` → settings werden überschrieben.
- Restaurant-Patch ohne Adress-Änderung → kein Geocode-Call, settings unverändert.
- Geocoder liefert None → Restaurant-Update läuft trotzdem durch, settings unverändert.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.routes import admin as admin_routes
from app.api.routes import restaurants as restaurant_routes

# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _FakeExecuteResult:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Async-Session, die ein vorgegebenes Restaurant zurückgibt."""

    def __init__(self, restaurant: Any | None):
        self._restaurant = restaurant
        self.added: list[Any] = []
        self.commit_count = 0
        self.flush_count = 0

    async def execute(self, _stmt: Any) -> _FakeExecuteResult:
        return _FakeExecuteResult([self._restaurant] if self._restaurant else [])

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1
        # Falls ein Restaurant ohne ID added wurde, ID generieren.
        for obj in self.added:
            if hasattr(obj, "id") and getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, _obj: Any) -> None:
        return None


def _make_restaurant(**overrides: Any) -> SimpleNamespace:
    """Restaurant-Stand-In mit den von den Routen gelesenen Attributen."""
    base: dict[str, Any] = dict(
        id=uuid.uuid4(),
        name="Test-Restaurant",
        slug="test-restaurant",
        address=None,
        phone=None,
        email=None,
        description=None,
        company_name=None,
        street=None,
        zip_code=None,
        city=None,
        country=None,
        tax_number=None,
        vat_id=None,
        settings={},
        public_booking_enabled=False,
        booking_lead_time_hours=2,
        booking_max_party_size=12,
        booking_default_duration=120,
        opening_hours=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# Tests: PATCH /restaurants/{id}
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_update_restaurant_geocodes_when_street_changes(monkeypatch):
    restaurant = _make_restaurant(
        street="Alte Straße 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
        settings={"latitude": 0.0, "longitude": 0.0},
    )
    session = _FakeSession(restaurant)

    captured: dict[str, str] = {}

    async def fake_geocode(address: str) -> tuple[float, float] | None:
        captured["address"] = address
        return 52.5200, 13.4050

    monkeypatch.setattr(restaurant_routes, "geocode_address", fake_geocode)

    update = restaurant_routes.RestaurantUpdate(street="Neue Straße 5")
    current_user = SimpleNamespace(role="owner", tenant_id=restaurant.id)

    response = await restaurant_routes.update_restaurant(
        restaurant_id=restaurant.id,
        data=update,
        current_user=current_user,
        session=session,
    )

    assert restaurant.street == "Neue Straße 5"
    assert restaurant.settings["latitude"] == pytest.approx(52.5200)
    assert restaurant.settings["longitude"] == pytest.approx(13.4050)
    # Nominatim-Adress-String enthält das neue Strassen-Feld.
    assert "Neue Straße 5" in captured["address"]
    assert response.settings["latitude"] == pytest.approx(52.5200)


@pytest.mark.asyncio
async def test_update_restaurant_skips_geocoding_when_only_name_changes(monkeypatch):
    restaurant = _make_restaurant(
        street="Alte Straße 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
        settings={"latitude": 52.0, "longitude": 13.0},
    )
    session = _FakeSession(restaurant)

    call_count = {"n": 0}

    async def fake_geocode(_address: str) -> tuple[float, float] | None:
        call_count["n"] += 1
        return 99.9, 99.9

    monkeypatch.setattr(restaurant_routes, "geocode_address", fake_geocode)

    update = restaurant_routes.RestaurantUpdate(name="Neuer Name")
    current_user = SimpleNamespace(role="owner", tenant_id=restaurant.id)

    await restaurant_routes.update_restaurant(
        restaurant_id=restaurant.id,
        data=update,
        current_user=current_user,
        session=session,
    )

    assert call_count["n"] == 0
    assert restaurant.settings["latitude"] == 52.0
    assert restaurant.settings["longitude"] == 13.0
    assert restaurant.name == "Neuer Name"


@pytest.mark.asyncio
async def test_update_restaurant_handles_geocoding_failure_gracefully(monkeypatch):
    restaurant = _make_restaurant(
        street="Alte Straße 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
        settings={"latitude": 52.0, "longitude": 13.0, "other_key": "untouched"},
    )
    session = _FakeSession(restaurant)

    async def fake_geocode(_address: str) -> tuple[float, float] | None:
        return None  # Nominatim down / kein Treffer.

    monkeypatch.setattr(restaurant_routes, "geocode_address", fake_geocode)

    update = restaurant_routes.RestaurantUpdate(city="Hamburg")
    current_user = SimpleNamespace(role="owner", tenant_id=restaurant.id)

    response = await restaurant_routes.update_restaurant(
        restaurant_id=restaurant.id,
        data=update,
        current_user=current_user,
        session=session,
    )

    # City wurde dennoch geändert; lat/lng sind unverändert; Update kommt durch.
    assert restaurant.city == "Hamburg"
    assert restaurant.settings["latitude"] == 52.0
    assert restaurant.settings["longitude"] == 13.0
    assert restaurant.settings["other_key"] == "untouched"
    assert session.commit_count == 1
    assert response.settings["latitude"] == 52.0


@pytest.mark.asyncio
async def test_update_restaurant_does_not_geocode_when_field_unchanged(monkeypatch):
    restaurant = _make_restaurant(
        street="Alte Straße 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
        settings={},
    )
    session = _FakeSession(restaurant)

    call_count = {"n": 0}

    async def fake_geocode(_address: str) -> tuple[float, float] | None:
        call_count["n"] += 1
        return 1.0, 2.0

    monkeypatch.setattr(restaurant_routes, "geocode_address", fake_geocode)

    # Identischer Wert für street → keine "Änderung" → kein Geocoding.
    update = restaurant_routes.RestaurantUpdate(street="Alte Straße 1")
    current_user = SimpleNamespace(role="owner", tenant_id=restaurant.id)

    await restaurant_routes.update_restaurant(
        restaurant_id=restaurant.id,
        data=update,
        current_user=current_user,
        session=session,
    )

    assert call_count["n"] == 0
    assert "latitude" not in restaurant.settings


# --------------------------------------------------------------------------- #
# Tests: POST /admin/tenants
# --------------------------------------------------------------------------- #


class _AdminFakeSession:
    """Session, die das beim ``add()`` übergebene Restaurant referenziert."""

    def __init__(self):
        self.restaurant: Any | None = None
        self.added: list[Any] = []
        self.commit_count = 0

    async def execute(self, _stmt: Any) -> _FakeExecuteResult:
        # Slug- und Email-Lookups liefern keinen Treffer.
        return _FakeExecuteResult([])

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if obj.__class__.__name__ == "Restaurant":
            self.restaurant = obj

    async def flush(self) -> None:
        if self.restaurant is not None and getattr(self.restaurant, "id", None) is None:
            self.restaurant.id = uuid.uuid4()
            # Mindest-Defaults setzen, die im weiteren Verlauf gelesen werden.
            if not hasattr(self.restaurant, "settings") or self.restaurant.settings is None:
                self.restaurant.settings = {}
            if not hasattr(self.restaurant, "created_at"):
                self.restaurant.created_at = datetime.now(UTC)

    async def commit(self) -> None:
        self.commit_count += 1


@pytest.mark.asyncio
async def test_create_tenant_geocodes_address(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_geocode(address: str) -> tuple[float, float] | None:
        captured["address"] = address
        return 48.1351, 11.5820

    monkeypatch.setattr(admin_routes, "geocode_address", fake_geocode)

    session = _AdminFakeSession()
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    current_user = SimpleNamespace(id=uuid.uuid4())

    payload = admin_routes.TenantCreate(
        name="Bistro München",
        address="Marienplatz 1, 80331 München",
        owner_first_name="Max",
        owner_last_name="Mustermann",
        owner_email="max@example.com",
        owner_password="supersecret",
        owner_operator_number="0001",
        owner_pin="123456",
    )

    response = await admin_routes.create_tenant(
        data=payload,
        request=request,
        current_user=current_user,
        session=session,
    )

    assert captured["address"] == "Marienplatz 1, 80331 München"
    assert session.restaurant is not None
    assert session.restaurant.settings["latitude"] == pytest.approx(48.1351)
    assert session.restaurant.settings["longitude"] == pytest.approx(11.5820)
    assert response.tenant_name == "Bistro München"


@pytest.mark.asyncio
async def test_create_tenant_without_address_skips_geocoding(monkeypatch):
    call_count = {"n": 0}

    async def fake_geocode(_address: str) -> tuple[float, float] | None:
        call_count["n"] += 1
        return 1.0, 2.0

    monkeypatch.setattr(admin_routes, "geocode_address", fake_geocode)

    session = _AdminFakeSession()
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    current_user = SimpleNamespace(id=uuid.uuid4())

    payload = admin_routes.TenantCreate(
        name="Adressloses Bistro",
        owner_first_name="Anna",
        owner_last_name="Beispiel",
        owner_email="anna@example.com",
        owner_password="supersecret",
        owner_operator_number="0002",
        owner_pin="654321",
    )

    await admin_routes.create_tenant(
        data=payload,
        request=request,
        current_user=current_user,
        session=session,
    )

    assert call_count["n"] == 0
    assert "latitude" not in (session.restaurant.settings or {})


@pytest.mark.asyncio
async def test_create_tenant_geocoding_failure_does_not_block(monkeypatch):
    async def fake_geocode(_address: str) -> tuple[float, float] | None:
        return None

    monkeypatch.setattr(admin_routes, "geocode_address", fake_geocode)

    session = _AdminFakeSession()
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    current_user = SimpleNamespace(id=uuid.uuid4())

    payload = admin_routes.TenantCreate(
        name="Bistro Pleite",
        address="Irgendwostraße 99",
        owner_first_name="Carl",
        owner_last_name="Test",
        owner_email="carl@example.com",
        owner_password="supersecret",
        owner_operator_number="0003",
        owner_pin="999888",
    )

    response = await admin_routes.create_tenant(
        data=payload,
        request=request,
        current_user=current_user,
        session=session,
    )

    assert session.commit_count == 1
    assert "latitude" not in (session.restaurant.settings or {})
    assert response.tenant_name == "Bistro Pleite"


# --------------------------------------------------------------------------- #
# Tests: build_address_string Helper
# --------------------------------------------------------------------------- #


def test_build_address_string_uses_structured_fields():
    from app.services.geocoding import build_address_string

    result = build_address_string(
        street="Hauptstraße 12",
        zip_code="10115",
        city="Berlin",
        country="DE",
    )
    assert result == "Hauptstraße 12, 10115 Berlin, DE"


def test_build_address_string_falls_back_to_address():
    from app.services.geocoding import build_address_string

    result = build_address_string(
        street=None,
        zip_code=None,
        city=None,
        country=None,
        address_fallback="Marienplatz 1, 80331 München",
    )
    assert result == "Marienplatz 1, 80331 München"


def test_build_address_string_returns_none_when_empty():
    from app.services.geocoding import build_address_string

    result = build_address_string(
        street=None,
        zip_code=None,
        city=None,
        country=None,
    )
    assert result is None


def test_build_address_string_skips_missing_parts():
    from app.services.geocoding import build_address_string

    result = build_address_string(
        street=None,
        zip_code=None,
        city="Hamburg",
        country=None,
    )
    assert result == "Hamburg"
