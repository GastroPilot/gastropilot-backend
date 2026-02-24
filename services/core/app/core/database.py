from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings

logger = logging.getLogger(__name__)


def _fix_asyncpg_url(url: str) -> str:
    """Remove ``sslmode`` query param that asyncpg doesn't understand."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    params.pop("sslmode", None)
    cleaned = parsed._replace(query=urlencode(params, doseq=True))
    return urlunparse(cleaned)


class Base(DeclarativeBase):
    pass


_engine_app: AsyncEngine | None = None
_engine_admin: AsyncEngine | None = None
_session_factory_app: async_sessionmaker | None = None
_session_factory_admin: async_sessionmaker | None = None


def get_engines() -> tuple[AsyncEngine, AsyncEngine]:
    global _engine_app, _engine_admin

    if _engine_app is None:
        _engine_app = create_async_engine(
            _fix_asyncpg_url(settings.DATABASE_URL),
            echo=settings.is_development,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )

    if _engine_admin is None:
        _engine_admin = create_async_engine(
            _fix_asyncpg_url(settings.DATABASE_URL_ADMIN),
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )

    return _engine_app, _engine_admin


def get_session_factories() -> tuple[async_sessionmaker, async_sessionmaker]:
    global _session_factory_app, _session_factory_admin
    engine_app, engine_admin = get_engines()

    if _session_factory_app is None:
        _session_factory_app = async_sessionmaker(
            engine_app,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

    if _session_factory_admin is None:
        _session_factory_admin = async_sessionmaker(
            engine_admin,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

    return _session_factory_app, _session_factory_admin


async def close_engines() -> None:
    global _engine_app, _engine_admin
    if _engine_app:
        await _engine_app.dispose()
        _engine_app = None
    if _engine_admin:
        await _engine_admin.dispose()
        _engine_admin = None
