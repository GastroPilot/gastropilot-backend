from __future__ import annotations

import logging
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.types import ASGIApp, Receive, Scope, Send

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware


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

_shared_path = Path(__file__).parent.parent.parent.parent / "packages"
if str(_shared_path) not in sys.path:
    sys.path.insert(0, str(_shared_path))

from shared.auth import configure as configure_auth
from shared.auth import verify_token
from shared.schemas import PLATFORM_ROLES
from shared.tenant import TenantMiddleware

from app.core.config import settings
from app.core.database import close_engines, get_session_factories

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

configure_auth(
    jwt_secret=settings.JWT_SECRET,
    jwt_algorithm=settings.JWT_ALGORITHM,
    jwt_issuer=settings.JWT_ISSUER,
    jwt_audience=settings.JWT_AUDIENCE,
    jwt_leeway_seconds=settings.JWT_LEEWAY_SECONDS,
    access_token_expire_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    refresh_token_expire_days=settings.REFRESH_TOKEN_EXPIRE_DAYS,
    bcrypt_rounds=settings.BCRYPT_ROUNDS,
    refresh_token_pepper=settings.REFRESH_TOKEN_PEPPER,
)


def _is_platform_role(role: str | None) -> bool:
    if not role:
        return False
    return any(role == str(platform_role) for platform_role in PLATFORM_ROLES)


def _normalize_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting GastroPilot Orders Service...")
    get_session_factories()
    yield
    logger.info("Shutting down Orders Service...")
    await close_engines()


app = FastAPI(
    title="GastroPilot Orders Service",
    version="2.0.0",
    docs_url="/docs" if settings.is_development else None,
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
)
app.add_middleware(TenantMiddleware)
app.add_middleware(TrailingSlashMiddleware)

from app.api.routes import (
    fiskaly,
    health,
    invoices,
    kitchen,
    kitchen_courses,
    kitchen_device,
    orders,
    public_orders,
    statistics,
    sumup,
    waitlist,
    webhook_sumup,
)
from app.websocket.manager import manager

# Health-Router zuerst, damit /orders/health nicht von /{order_id} abgefangen wird
app.include_router(health.router, prefix="/api/v1")
app.include_router(webhook_sumup.router, prefix="/api/v1")

for prefix in ("/api/v1", "/v1"):
    app.include_router(orders.router, prefix=prefix)
    app.include_router(kitchen.router, prefix=prefix)
    app.include_router(kitchen_courses.router, prefix=prefix)
    app.include_router(waitlist.router, prefix=prefix)
    app.include_router(statistics.router, prefix=prefix)
    app.include_router(invoices.router, prefix=prefix)
    app.include_router(sumup.router, prefix=prefix)
    app.include_router(public_orders.router, prefix=prefix)
    app.include_router(kitchen_device.router, prefix=prefix)
    app.include_router(fiskaly.router, prefix=prefix)


@app.websocket("/ws/{tenant_id}")
async def websocket_endpoint(websocket: WebSocket, tenant_id: str):
    normalized_target_tenant = _normalize_uuid(tenant_id)
    if normalized_target_tenant is None:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid tenant_id",
        )
        return

    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Missing access token",
        )
        return

    payload = verify_token(token)
    if not payload:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid access token",
        )
        return

    role = payload.get("role")
    token_tenant = payload.get("tenant_id")
    impersonating_tenant = payload.get("impersonating_tenant_id")
    effective_token_tenant = (
        impersonating_tenant if _is_platform_role(role) and impersonating_tenant else token_tenant
    )
    normalized_effective_tenant = _normalize_uuid(
        str(effective_token_tenant) if effective_token_tenant is not None else None
    )

    # Plattform-Rollen ohne gesetzten Tenant dürfen weiterhin explizit einen Tenant-Raum öffnen.
    if normalized_effective_tenant is None and _is_platform_role(role):
        normalized_effective_tenant = normalized_target_tenant

    if normalized_effective_tenant != normalized_target_tenant:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Tenant mismatch",
        )
        return

    await manager.connect(websocket, normalized_target_tenant)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, normalized_target_tenant)
