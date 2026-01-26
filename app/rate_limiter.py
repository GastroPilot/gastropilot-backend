"""
Rate Limiting mit slowapi (an Referenz angelehnt).
In Development deaktiviert; in Production optional mit Redis (REDIS_URL) oder in-memory.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import logging
from app.settings import REDIS_URL, ENV

logger = logging.getLogger(__name__)

# In der Entwicklungsumgebung: Rate Limiting komplett deaktivieren
if ENV == "development":
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[],  # Keine Limits in Development
        storage_uri=None,
        swallow_errors=True
    )
    logger.info("Rate limiting DISABLED in development mode")
else:
    if REDIS_URL:
        storage_uri = REDIS_URL
        logger.info(f"Rate limiter using Redis backend: {REDIS_URL}")
    else:
        storage_uri = None  # In-memory for dev/single worker
        logger.info("Rate limiter using in-memory backend")

    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["200 per day", "50 per minute"],
        storage_uri=storage_uri,
        swallow_errors=True  # Don't crash if Redis is unavailable
    )


def setup_rate_limiting(app: FastAPI):
    """
    Konfiguriert Rate Limiting für die App und hängt einen globalen Handler an.
    """
    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request, exc):
        logger.warning(
            f"Rate limit exceeded for {request.client[0] if request.client else 'unknown'}"
        )
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded",
                "retry_after": exc.detail.split("after ")[-1] if "after" in exc.detail else "60"
            }
        )

    return limiter


# ==================== RATE LIMIT DECORATORS ====================

def _no_op_decorator(func):
    """No-Op Decorator für Development - macht nichts"""
    return func


if ENV == "development":
    def rate_limit_strict():
        return _no_op_decorator

    def rate_limit_moderate():
        return _no_op_decorator

    def rate_limit_generous():
        return _no_op_decorator

    def rate_limit_public():
        return _no_op_decorator
else:
    def rate_limit_strict():
        return limiter.limit("15/minute")

    def rate_limit_moderate():
        return limiter.limit("30/minute")

    def rate_limit_generous():
        return limiter.limit("100/minute")

    def rate_limit_public():
        return limiter.limit("10/minute")
