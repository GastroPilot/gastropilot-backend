from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.database import close_engines, get_engines
from app.core.tenant import TenantMiddleware

# Add shared packages to path
_shared_path = Path(__file__).parent.parent.parent.parent / "packages"
if str(_shared_path) not in sys.path:
    sys.path.insert(0, str(_shared_path))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        traces_sample_rate=0.1,
    )

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting GastroPilot Core Service...")
    get_engines()
    yield
    logger.info("Shutting down Core Service...")
    await close_engines()


app = FastAPI(
    title="GastroPilot Core Service",
    version="2.0.0",
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "Accept",
        "Accept-Language",
        "Cache-Control",
        "X-Requested-With",
        "X-Admin-Tenant-Context",
    ],
)

app.add_middleware(TenantMiddleware)

from app.api.routes import (  # noqa: E402
    admin,
    allergens,
    auth,
    dashboard,
    health,
    menus,
    payments,
    reservations,
    restaurants,
    users,
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(restaurants.router, prefix="/api/v1")
app.include_router(reservations.router, prefix="/api/v1")
app.include_router(menus.router, prefix="/api/v1")
app.include_router(allergens.router, prefix="/api/v1")
app.include_router(payments.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")

# Legacy /v1 prefix support
app.include_router(health.router, prefix="/v1")
app.include_router(auth.router, prefix="/v1")
app.include_router(users.router, prefix="/v1")
app.include_router(restaurants.router, prefix="/v1")
app.include_router(reservations.router, prefix="/v1")
app.include_router(menus.router, prefix="/v1")
app.include_router(allergens.router, prefix="/v1")
app.include_router(payments.router, prefix="/v1")
app.include_router(admin.router, prefix="/v1")
app.include_router(dashboard.router, prefix="/v1")
