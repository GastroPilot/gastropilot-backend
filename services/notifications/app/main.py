from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis Consumer in separatem Thread starten
    from app.worker import start_redis_consumer

    consumer_thread = threading.Thread(
        target=start_redis_consumer,
        name="redis-consumer",
        daemon=True,
    )
    consumer_thread.start()
    logger.info("Redis Pub/Sub Consumer gestartet")
    yield
    logger.info("Notifications Service wird beendet")


app = FastAPI(
    title="GastroPilot Notifications Service",
    version="2.0.0",
    docs_url="/docs" if settings.is_development else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

from app.api.routes import health, webhooks

app.include_router(health.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")
# Legacy-Präfix für Kompatibilität
app.include_router(health.router, prefix="/v1")
