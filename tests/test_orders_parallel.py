"""Concurrency tests for order creation conflict handling."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import create_access_token, hash_password
from app.database import Base
from app.database.models import Reservation, Restaurant, Table, User
from app.dependencies import get_session as get_db_session
from app.main import app
from app.routers import orders as orders_router


@pytest.mark.asyncio
async def test_parallel_create_order_allows_only_one_active_order(monkeypatch, tmp_path: Path):
    """Two concurrent create requests for same reservation/table must resolve to 201 + 409."""
    db_path = tmp_path / "parallel_orders_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False, future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as seed_session:
        restaurant = Restaurant(
            name="Parallel Test Restaurant",
            address="Race Street 1",
            phone="+49 123 456",
            email="parallel@test.local",
        )
        seed_session.add(restaurant)
        await seed_session.flush()

        table = Table(
            restaurant_id=restaurant.id,
            number="R1",
            capacity=4,
            shape="rectangle",
            position_x=100.0,
            position_y=100.0,
            width=120.0,
            height=80.0,
            is_active=True,
        )
        seed_session.add(table)
        await seed_session.flush()

        reservation_start = datetime.now(UTC) + timedelta(hours=1)
        reservation = Reservation(
            restaurant_id=restaurant.id,
            table_id=table.id,
            start_at=reservation_start,
            end_at=reservation_start + timedelta(hours=2),
            party_size=2,
            status="confirmed",
            channel="manual",
            guest_name="Parallel Guest",
        )
        seed_session.add(reservation)

        user = User(
            operator_number="7777",
            pin_hash=hash_password("secret"),
            first_name="Parallel",
            last_name="Admin",
            role="restaurantinhaber",
            is_active=True,
        )
        seed_session.add(user)
        await seed_session.flush()

        await seed_session.execute(text("""
                CREATE UNIQUE INDEX uq_orders_active_reservation_test
                ON orders(restaurant_id, reservation_id)
                WHERE reservation_id IS NOT NULL
                  AND status NOT IN ('paid', 'canceled')
                  AND payment_status <> 'paid'
                """))
        await seed_session.execute(text("""
                CREATE UNIQUE INDEX uq_orders_active_table_test
                ON orders(restaurant_id, table_id)
                WHERE table_id IS NOT NULL
                  AND status NOT IN ('paid', 'canceled')
                  AND payment_status <> 'paid'
                """))

        await seed_session.commit()

        restaurant_id = restaurant.id
        reservation_id = reservation.id
        user_id = user.id

    token = create_access_token(
        data={
            "user_id": user_id,
            "sub": str(user_id),
            "operator_number": "7777",
            "role": "restaurantinhaber",
        }
    )
    headers = {"Authorization": f"Bearer {token}"}

    async def _override_get_session():
        async with session_maker() as session:
            yield session

    async def _allow_orders_module():
        return None

    gate = asyncio.Event()
    gate_lock = asyncio.Lock()
    arrived = {"count": 0}

    async def _race_no_conflict(*args, **kwargs):
        async with gate_lock:
            arrived["count"] += 1
            if arrived["count"] >= 2:
                gate.set()
        await asyncio.wait_for(gate.wait(), timeout=2)
        return None

    order_number_lock = asyncio.Lock()
    order_number_counter = {"value": 0}

    async def _unique_order_number(*args, **kwargs):
        async with order_number_lock:
            order_number_counter["value"] += 1
            return f"ORD-RACE-{order_number_counter['value']:04d}"

    monkeypatch.setattr(orders_router, "_find_active_order_conflict", _race_no_conflict)
    monkeypatch.setattr(orders_router, "_generate_order_number", _unique_order_number)

    app.dependency_overrides[get_db_session] = _override_get_session
    app.dependency_overrides[orders_router.require_orders_module] = _allow_orders_module

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=True
        ) as client:
            payload = {"reservation_id": reservation_id, "party_size": 2, "notes": "parallel"}
            responses = await asyncio.gather(
                client.post(
                    f"/v1/restaurants/{restaurant_id}/orders",
                    headers=headers,
                    json=payload,
                ),
                client.post(
                    f"/v1/restaurants/{restaurant_id}/orders",
                    headers=headers,
                    json=payload,
                ),
            )
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()

    status_codes = sorted(response.status_code for response in responses)
    assert status_codes == [201, 409]

    conflict_response = next(response for response in responses if response.status_code == 409)
    assert (
        conflict_response.json()["detail"]
        == "An active order already exists for this reservation or table"
    )
