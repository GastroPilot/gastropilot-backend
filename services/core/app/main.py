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

import app.models  # noqa: F401  — register all models for FK resolution
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
    blocks,
    dashboard,
    health,
    license,
    menus,
    messages,
    payments,
    prepayments,
    public_reservations,
    reservation_table_day_configs,
    reservations,
    restaurants,
    table_day_configs,
    upsell_packages,
    user_settings,
    users,
    vouchers,
    waitlist,
)

_all_routers = [
    health.router,
    auth.router,
    users.router,
    user_settings.router,
    restaurants.router,
    reservations.router,
    menus.router,
    allergens.router,
    payments.router,
    admin.router,
    dashboard.router,
    blocks.router,
    table_day_configs.router,
    reservation_table_day_configs.router,
    waitlist.router,
    messages.router,
    vouchers.router,
    upsell_packages.router,
    prepayments.router,
    license.router,
    public_reservations.router,
]

for r in _all_routers:
    app.include_router(r, prefix="/api/v1")
    app.include_router(r, prefix="/v1")
