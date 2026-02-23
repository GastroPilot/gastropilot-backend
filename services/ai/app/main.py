from __future__ import annotations
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="GastroPilot AI Service",
    version="2.0.0",
    docs_url="/docs" if settings.is_development else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

from app.api.routes import health, predictions, recommendations, seating

app.include_router(health.router, prefix="/api/v1")
app.include_router(seating.router, prefix="/api/v1")
app.include_router(predictions.router, prefix="/api/v1")
app.include_router(recommendations.router, prefix="/api/v1")
