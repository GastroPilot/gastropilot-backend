import logging
from contextlib import asynccontextmanager
from datetime import UTC

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.database.instance import init_db
from app.middleware import (
    ActivityLogMiddleware,
    AuditLogMiddleware,
    HostValidationMiddleware,
    RequestLoggingMiddleware,
    RequestTimeoutMiddleware,
    SecurityHeadersMiddleware,
    log_shutdown,
    log_startup,
    setup_logging,
)
from app.rate_limiter import setup_rate_limiting
from app.routers import (
    ai,
    areas,
    audit_logs,
    auth,
    block_assignments,
    blocks,
    dashboard,
    guests,
    invoices,
    license,
    menu_items,
    messages,
    obstacles,
    order_statistics,
    orders,
    prepayments,
    public_reservations,
    reservation_table_day_configs,
    reservation_tables,
    reservations,
    restaurants,
    sumup,
    table_day_configs,
    tables,
    upsell_packages,
    user_settings,
    vouchers,
    waitlist,
    webhook_sumup,
    webhook_whatsapp,
    websocket,
)
from app.sentry import init_sentry
from app.settings import (
    ACTIVITY_LOGGING_ENABLED,
    CORS_ALLOW_CREDENTIALS,
    CORS_ALLOW_HEADERS,
    CORS_ALLOW_METHODS,
    CORS_ORIGIN_REGEX,
    CORS_ORIGINS,
    DATABASE_URL,
    DB_TYPE,
    ENV,
    LOG_LEVEL,
    REQUEST_TIMEOUT,
)
from app.version import VERSION

logger = logging.getLogger(__name__)

# Set specific loggers to DEBUG in development
if ENV == "development":
    logging.getLogger("app.auth").setLevel(logging.DEBUG)
    logging.getLogger("app.dependencies").setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle management für Startup und Shutdown"""
    from app.database.seed import seed_database
    from app.services.license_service import license_service

    # Initialize Sentry early for error tracking
    sentry_initialized = init_sentry()
    if sentry_initialized:
        logger.info("Sentry error tracking initialized")

    log_startup()
    await init_db()

    # Seed default users for development
    await seed_database()

    # Initialisiere License Service
    await license_service.check_license(force=True)
    logger.info(f"License features: {license_service.get_features()}")

    yield

    log_shutdown()


app = FastAPI(
    title="GastroPilot API",
    description="API für das GastroPilot Backend",
    version=VERSION,
    docs_url="/v1/docs" if ENV == "development" else None,
    redoc_url="/v1/redoc" if ENV == "development" else None,
    openapi_url="/v1/openapi.json" if ENV == "development" else None,
    lifespan=lifespan,
)

setup_logging()

# Proxy Headers Middleware - MUSS als erstes sein!
# Vertraut X-Forwarded-Proto und X-Forwarded-For Headers vom Reverse-Proxy (Nginx)
# Dadurch werden Redirects korrekt mit https:// statt http:// generiert
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Log CORS-Konfiguration beim Start
logger.info("=" * 60)
logger.info("CORS Configuration:")
logger.info(f"  CORS_ORIGINS: {CORS_ORIGINS}")
logger.info(f"  CORS_ORIGIN_REGEX: {CORS_ORIGIN_REGEX}")
logger.info(f"  CORS_ALLOW_CREDENTIALS: {CORS_ALLOW_CREDENTIALS}")
logger.info(f"  CORS_ALLOW_METHODS: {CORS_ALLOW_METHODS}")
logger.info(f"  CORS_ALLOW_HEADERS: {CORS_ALLOW_HEADERS}")
logger.info("=" * 60)

# CORS Middleware (MUSS vor SecurityHeadersMiddleware sein!)
# allow_origins: Explizite Liste (localhost für Development)
# allow_origin_regex: Dynamisches Pattern für alle *.gpilot.app Subdomains
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=CORS_ALLOW_METHODS,
    allow_headers=CORS_ALLOW_HEADERS,
    expose_headers=["*"],  # erlaubt z.B. SSE-Header wie text/event-stream
)

# Security headers
app.add_middleware(SecurityHeadersMiddleware)

# Request logging
app.add_middleware(RequestLoggingMiddleware)

# Request timeout
app.add_middleware(RequestTimeoutMiddleware, timeout=REQUEST_TIMEOUT)

# Host validation (warn only)
app.add_middleware(HostValidationMiddleware)

# Activity logging (DB)
if ACTIVITY_LOGGING_ENABLED:
    app.add_middleware(ActivityLogMiddleware)
    app.add_middleware(AuditLogMiddleware)

# Rate limiting (SlowAPI)
limiter = setup_rate_limiting(app)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# Router registrieren
app.include_router(auth.router, prefix="/v1")
app.include_router(license.router, prefix="/v1")
app.include_router(restaurants.router, prefix="/v1")
app.include_router(tables.router, prefix="/v1")
app.include_router(guests.router, prefix="/v1")
app.include_router(reservations.router, prefix="/v1")
app.include_router(areas.router, prefix="/v1")
app.include_router(obstacles.router, prefix="/v1")
app.include_router(blocks.router, prefix="/v1")
app.include_router(block_assignments.router, prefix="/v1")
app.include_router(waitlist.router, prefix="/v1")
app.include_router(messages.router, prefix="/v1")
app.include_router(reservation_tables.router, prefix="/v1")
app.include_router(table_day_configs.router, prefix="/v1")
app.include_router(reservation_table_day_configs.router, prefix="/v1")
app.include_router(audit_logs.router, prefix="/v1")
app.include_router(user_settings.router, prefix="/v1")
app.include_router(orders.router, prefix="/v1")
app.include_router(menu_items.router, prefix="/v1")
app.include_router(order_statistics.router, prefix="/v1")
app.include_router(invoices.router, prefix="/v1")
app.include_router(license.router, prefix="/v1")
app.include_router(sumup.router, prefix="/v1")
app.include_router(vouchers.router, prefix="/v1")
app.include_router(upsell_packages.router, prefix="/v1")
app.include_router(prepayments.router, prefix="/v1")
app.include_router(websocket.router, prefix="/v1")
app.include_router(dashboard.router, prefix="/v1")
app.include_router(ai.router, prefix="/v1")
# Public routes (no authentication required)
app.include_router(public_reservations.router, prefix="/v1")
app.include_router(webhook_whatsapp.router, prefix="/v1")
app.include_router(webhook_sumup.router, prefix="/v1")
# Webhooks auch unter /api/v1 verfügbar (für Reverse-Proxy Setups)
app.include_router(webhook_whatsapp.router, prefix="/api/v1")
app.include_router(webhook_sumup.router, prefix="/api/v1")


@app.get("/v1/")
async def root():
    """Root-Endpoint mit allgemeinen Informationen über die API"""
    from datetime import datetime

    return {
        "message": "Welcome to GastroPilot API",
        "version": VERSION,
        "api_name": "GastroPilot API",
        "description": "API für das GastroPilot Backend",
        "docs": "/v1/docs" if ENV == "development" else None,
        "health": "/v1/health",
        "timestamp": datetime.now(UTC).isoformat(),
        "endpoints": {
            "authentication": "/v1/auth",
            "license": "/v1/license",
            "restaurants": "/v1/restaurants",
            "tables": "/v1/tables",
            "guests": "/v1/guests",
            "reservations": "/v1/reservations",
            "areas": "/v1/areas",
            "obstacles": "/v1/obstacles",
            "blocks": "/v1/blocks",
            "block_assignments": "/v1/block-assignments",
            "waitlist": "/v1/waitlist",
            "messages": "/v1/messages",
            "reservation_tables": "/v1/reservation-tables",
            "table_day_configs": "/v1/table-day-configs",
            "reservation_table_day_configs": "/v1/reservation-table-day-configs",
            "audit_logs": "/v1/audit-logs",
            "user_settings": "/v1/user-settings",
            "orders": "/v1/orders",
            "menu_items": "/v1/menu-items",
            "order_statistics": "/v1/order-statistics",
            "invoices": "/v1/invoices",
            "ai": "/v1/ai",
        },
    }


def _is_production_environment() -> bool:
    """Prüft, ob wir in einem produktionsreifen Environment sind"""
    return ENV in ["production", "demo"]


@app.get("/v1/health")
async def health():
    """Health Check Endpoint mit API- und Environment-Informationen

    Für Production/Demo: Minimale Informationen (keine DB Connection Strings)
    Für Staging/Test/Dev: Detaillierte Informationen (inkl. maskierter DB URLs)
    """
    from datetime import datetime

    from sqlalchemy import text

    from app.database.instance import async_session

    is_prod_env = _is_production_environment()

    # Datenbank-Verbindung testen
    db_status = "unknown"
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
            db_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        db_status = "disconnected"

    # Basis-Response
    response = {
        "status": "healthy" if db_status == "connected" else "degraded",
        "version": VERSION,
        "timestamp": datetime.now(UTC).isoformat(),
        "api": {
            "name": "GastroPilot API",
            "version": VERSION,
            "prefix": "/v1",
            "description": "API für das GastroPilot Backend",
        },
    }

    # Für produktionsreife Environments: Minimale Informationen
    if is_prod_env:
        response["environment"] = {
            "env": ENV,
        }
        response["services"] = {
            "database": {
                "status": db_status,
                "type": DB_TYPE,
            },
        }
    else:
        # Für Development/Staging/Test: Detaillierte Informationen
        response["environment"] = {
            "env": ENV,
            "log_level": LOG_LEVEL,
            "activity_logging": ACTIVITY_LOGGING_ENABLED,
            "request_timeout": REQUEST_TIMEOUT,
        }
        response["services"] = {
            "database": {
                "status": db_status,
                "type": DB_TYPE,
                "url_masked": _mask_database_url(DATABASE_URL) if DATABASE_URL else None,
            },
        }

    return response


def _mask_database_url(url: str | None) -> str | None:
    """Maskiert sensible Informationen in der Datenbank-URL"""
    if not url:
        return None
    # Zeige nur Schema und Host, aber nicht Credentials
    if "@" in url:
        # Format: postgresql://user:pass@host:port/db
        parts = url.split("@")
        if len(parts) == 2:
            schema_part = parts[0].split("://")[0] if "://" in parts[0] else ""
            return f"{schema_part}://***:***@{parts[1]}"
    return url.split("?")[0]  # Entferne Query-Parameter
