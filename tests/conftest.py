"""
Pytest configuration and fixtures for GastroPilot backend tests.
"""

import pytest
import asyncio
from collections.abc import AsyncGenerator, Generator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from app.database import Base
from app.dependencies import get_session as get_db_session
from app.main import app
from app.auth import hash_password, create_access_token

# Test database URL (SQLite in-memory)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for each test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def async_engine():
    """Create async engine for each test function."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture(scope="function")
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a new database session for each test."""
    async_session_maker = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with overridden database session."""

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=True
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def test_user(db_session: AsyncSession):
    """Create a test user."""
    from app.database.models import User

    user = User(
        operator_number="1234",
        pin_hash=hash_password("123456"),
        first_name="Test",
        last_name="User",
        role="mitarbeiter",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_admin_user(db_session: AsyncSession):
    """Create a test admin user (restaurantinhaber)."""
    from app.database.models import User

    user = User(
        operator_number="9999",
        pin_hash=hash_password("admin123"),
        first_name="Admin",
        last_name="User",
        role="restaurantinhaber",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_servecta_user(db_session: AsyncSession):
    """Create a test Servecta user."""
    from app.database.models import User

    user = User(
        operator_number="0000",
        pin_hash=hash_password("servecta"),
        first_name="Servecta",
        last_name="Admin",
        role="servecta",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def auth_headers(test_user):
    """Create authentication headers for test user."""
    token = create_access_token(
        data={
            "user_id": test_user.id,
            "sub": str(test_user.id),
            "operator_number": test_user.operator_number,
            "role": test_user.role,
        }
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_auth_headers(test_admin_user):
    """Create authentication headers for admin user."""
    token = create_access_token(
        data={
            "user_id": test_admin_user.id,
            "sub": str(test_admin_user.id),
            "operator_number": test_admin_user.operator_number,
            "role": test_admin_user.role,
        }
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def test_restaurant(db_session: AsyncSession):
    """Create a test restaurant."""
    from app.database.models import Restaurant

    restaurant = Restaurant(
        name="Test Restaurant",
        address="Teststraße 1, 12345 Teststadt",
        phone="+49 123 456789",
        email="test@restaurant.de",
        description="Ein Test-Restaurant",
    )
    db_session.add(restaurant)
    await db_session.commit()
    await db_session.refresh(restaurant)
    return restaurant


@pytest.fixture
async def test_table(db_session: AsyncSession, test_restaurant):
    """Create a test table."""
    from app.database.models import Table

    table = Table(
        restaurant_id=test_restaurant.id,
        number="T1",
        capacity=4,
        shape="rectangle",
        position_x=100.0,
        position_y=100.0,
        width=120.0,
        height=80.0,
        is_active=True,
    )
    db_session.add(table)
    await db_session.commit()
    await db_session.refresh(table)
    return table


@pytest.fixture
async def test_guest(db_session: AsyncSession, test_restaurant):
    """Create a test guest."""
    from app.database.models import Guest

    guest = Guest(
        restaurant_id=test_restaurant.id,
        first_name="Max",
        last_name="Mustermann",
        email="max@example.de",
        phone="+49 170 1234567",
    )
    db_session.add(guest)
    await db_session.commit()
    await db_session.refresh(guest)
    return guest
