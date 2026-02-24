"""
Database seeding for development environment.

This module provides functions to seed the database with default data
for local development. It should only be used in development mode.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.database.models import User
from app.settings import ENV

logger = logging.getLogger(__name__)


async def seed_default_users(session: AsyncSession) -> None:
    """
    Seeds default users for development environment.

    Creates a Servecta admin user with operator number 0000 if it doesn't exist.
    This function is idempotent - it will not create duplicate users.

    Args:
        session: AsyncSession for database operations

    Default Users:
        - Operator 0000: Servecta admin (PIN: 000000)
    """
    if ENV not in ["development", "test"]:
        logger.info("Skipping user seeding (not in development/test environment)")
        return

    logger.info("Starting database seeding for development environment...")

    # Check if Servecta user (0000) already exists
    result = await session.execute(select(User).where(User.operator_number == "0000"))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        logger.info("Servecta user (0000) already exists, skipping seed")
        return

    # Create Servecta admin user
    logger.info("Creating default Servecta user (0000)...")

    servecta_user = User(
        operator_number="0000",
        pin_hash=hash_password("000000"),
        first_name="Servecta",
        last_name="Admin",
        role="servecta",
        is_active=True,
        created_at_utc=datetime.now(UTC),
        updated_at_utc=datetime.now(UTC),
    )

    session.add(servecta_user)
    await session.commit()

    logger.info("✅ Successfully created Servecta user (0000)")
    logger.info("   Login credentials:")
    logger.info("   - Operator Number: 0000")
    logger.info("   - PIN: 000000")
    logger.info("   - Role: servecta")


async def seed_platform_admin(session: AsyncSession) -> None:
    """
    Seeds a platform_admin user if PLATFORM_ADMIN_PASSWORD is set.

    In development/test: falls back to default password if env var not set.
    In staging/production: only creates user if PLATFORM_ADMIN_PASSWORD is explicitly set.

    This function is idempotent.
    """
    import os

    admin_email = os.environ.get("PLATFORM_ADMIN_EMAIL", "admin@gastropilot.de")
    admin_password = os.environ.get("PLATFORM_ADMIN_PASSWORD")

    if not admin_password:
        if ENV in ["development", "test"]:
            admin_password = "admin1234"
        else:
            # In production/staging: only create if password is explicitly provided
            return

    # Check if a platform_admin with this email already exists
    result = await session.execute(select(User).where(User.email == admin_email))
    existing = result.scalar_one_or_none()

    if existing:
        logger.info(f"Platform admin user ({admin_email}) already exists, skipping seed")
        return

    logger.info(f"Creating platform admin user ({admin_email})...")

    admin_user = User(
        email=admin_email,
        password_hash=hash_password(admin_password),
        first_name="Platform",
        last_name="Admin",
        role="platform_admin",
        is_active=True,
        created_at_utc=datetime.now(UTC),
        updated_at_utc=datetime.now(UTC),
    )

    session.add(admin_user)
    await session.commit()

    logger.info(f"Successfully created platform admin user ({admin_email})")


async def seed_database() -> None:
    """
    Main seeding function that orchestrates all seeding operations.

    This function should be called after database initialization (init_db)
    during application startup.
    """
    from app.database.instance import async_session

    async with async_session() as session:
        await seed_default_users(session)
        await seed_platform_admin(session)
