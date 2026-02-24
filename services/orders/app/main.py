from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

_shared_path = Path(__file__).parent.parent.parent.parent / "packages"
if str(_shared_path) not in sys.path:
    sys.path.insert(0, str(_shared_path))

from shared.tenant import TenantMiddleware

from app.core.config import settings
from app.core.database import close_engines, get_session_factories

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

from app.api.routes import (
    health,
    invoices,
    kitchen,
    orders,
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
    app.include_router(waitlist.router, prefix=prefix)
    app.include_router(statistics.router, prefix=prefix)
    app.include_router(invoices.router, prefix=prefix)
    app.include_router(sumup.router, prefix=prefix)


@app.websocket("/ws/{tenant_id}")
async def websocket_endpoint(websocket: WebSocket, tenant_id: str):
    await manager.connect(websocket, tenant_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, tenant_id)
