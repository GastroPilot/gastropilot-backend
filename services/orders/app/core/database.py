from __future__ import annotations

import ssl as _ssl
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings

_SSLMODE_USE_SSL = {"require", "verify-ca", "verify-full", "prefer", "allow"}


def _strip_sslmode(url: str) -> tuple[str, str | None]:
    """Strip ``sslmode`` from URL (SQLAlchemy passes it as kwarg which asyncpg rejects)."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    sslmode = params.pop("sslmode", [None])[0]
    cleaned = parsed._replace(query=urlencode(params, doseq=True))
    return urlunparse(cleaned), sslmode


def _connect_args_for_sslmode(sslmode: str | None) -> dict:
    """Build asyncpg connect_args from the extracted sslmode value."""
    if sslmode in _SSLMODE_USE_SSL:
        ctx = _ssl.create_default_context()
        if sslmode == "require":
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
        return {"ssl": ctx}
    # No sslmode or explicitly disabled → no SSL
    return {"ssl": False}


class Base(DeclarativeBase):
    pass


_engine_app: AsyncEngine | None = None
_engine_admin: AsyncEngine | None = None
_session_factory_app: async_sessionmaker | None = None
_session_factory_admin: async_sessionmaker | None = None


def get_session_factories():
    global _engine_app, _engine_admin, _session_factory_app, _session_factory_admin

    if _engine_app is None:
        url, sslmode = _strip_sslmode(settings.DATABASE_URL)
        _engine_app = create_async_engine(
            url, pool_pre_ping=True, connect_args=_connect_args_for_sslmode(sslmode)
        )
        _session_factory_app = async_sessionmaker(
            _engine_app, class_=AsyncSession, expire_on_commit=False
        )

    if _engine_admin is None:
        url, sslmode = _strip_sslmode(settings.DATABASE_URL_ADMIN)
        _engine_admin = create_async_engine(
            url, pool_pre_ping=True, connect_args=_connect_args_for_sslmode(sslmode)
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
