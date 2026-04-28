from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class TrailingSlashMiddleware:
    """ASGI-Middleware: entfernt Trailing Slashes bevor der Router sie sieht."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope["path"]
            if len(path) > 1 and path.endswith("/"):
                scope["path"] = path.rstrip("/")
        await self.app(scope, receive, send)


from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import app.models  # noqa: F401  — register all models for FK resolution
from app.core.config import settings
from app.core.database import close_engines, get_engines
from app.core.tenant import TenantMiddleware
from app.middleware.audit_logging import AuditLoggingMiddleware

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
    if settings.is_development and settings.SEED_ON_STARTUP:
        from app.core.seed import seed_database

        try:
            await seed_database()
        except Exception:
            logger.exception(
                "Database seeding failed during startup; continuing without seed data."
            )
    yield
    logger.info("Shutting down Core Service...")
    await close_engines()


app = FastAPI(
    title="GastroPilot Core Service",
    version="2.0.0",
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    lifespan=lifespan,
    redirect_slashes=False,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

logger = logging.getLogger(__name__)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error("Validation error on %s %s: %s", request.method, request.url.path, exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


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
app.add_middleware(AuditLoggingMiddleware)
app.add_middleware(TrailingSlashMiddleware)

from app.api.routes import (  # noqa: E402
    admin,
    allergens,
    auth,
    billing,
    blocks,
    dashboard,
    devices,
    guest_auth,
    guest_profile,
    guests_crm,
    health,
    internal,
    license,
    menus,
    messages,
    notification_inbox,
    payments,
    guest_invites,
    public_reservations,
    public_waitlist,
    qr_codes,
    reservation_table_day_configs,
    reservations,
    restaurant_search,
    restaurants,
    reviews,
    table_day_configs,
    upsell_packages,
    uploads,
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
    license.router,
    public_reservations.router,
    guest_invites.router,
    guest_auth.router,
    guest_profile.router,
    restaurant_search.router,
    reviews.router,
    guests_crm.router,
    qr_codes.router,
    public_waitlist.router,
    billing.router,
    devices.router,
    upsell_packages.router,
    vouchers.router,
    uploads.router,
    notification_inbox.router,
    internal.router,
]

for r in _all_routers:
    app.include_router(r, prefix="/api/v1")
    app.include_router(r, prefix="/v1")
