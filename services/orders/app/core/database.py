from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings


def _fix_asyncpg_url(url: str) -> str:
    """Pass through URL as-is; asyncpg handles sslmode natively."""
    return url


class Base(DeclarativeBase):
    pass


_engine_app: AsyncEngine | None = None
_engine_admin: AsyncEngine | None = None
_session_factory_app: async_sessionmaker | None = None
_session_factory_admin: async_sessionmaker | None = None


def get_session_factories():
    global _engine_app, _engine_admin, _session_factory_app, _session_factory_admin

    if _engine_app is None:
        _engine_app = create_async_engine(
            _fix_asyncpg_url(settings.DATABASE_URL), pool_pre_ping=True
        )
        _session_factory_app = async_sessionmaker(
            _engine_app, class_=AsyncSession, expire_on_commit=False
        )

    if _engine_admin is None:
        _engine_admin = create_async_engine(
            _fix_asyncpg_url(settings.DATABASE_URL_ADMIN), pool_pre_ping=True
        )
        _session_factory_admin = async_sessionmaker(
            _engine_admin, class_=AsyncSession, expire_on_commit=False
        )

    return _session_factory_app, _session_factory_admin


async def close_engines():
    global _engine_app, _engine_admin
    if _engine_app:
        await _engine_app.dispose()
        _engine_app = None
    if _engine_admin:
        await _engine_admin.dispose()
        _engine_admin = None
