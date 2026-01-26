"""
Sentry integration for error tracking.

Sentry is optional - if sentry_sdk is not installed, all functions
become no-ops and the application continues to work normally.
"""
import logging

logger = logging.getLogger(__name__)

# Try to import sentry_sdk, but make it optional
try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False
    sentry_sdk = None  # type: ignore
    logger.info("sentry_sdk not installed - error tracking disabled")

from app.settings import (
    SENTRY_DSN,
    SENTRY_ENVIRONMENT,
    SENTRY_TRACES_SAMPLE_RATE,
    SENTRY_PROFILES_SAMPLE_RATE,
    ENV,
)


def init_sentry() -> bool:
    """
    Initialize Sentry error tracking.
    
    Returns:
        True if Sentry was initialized, False otherwise.
    """
    if not SENTRY_AVAILABLE:
        logger.info("sentry_sdk not installed, error tracking disabled")
        return False
    
    if not SENTRY_DSN:
        logger.info("Sentry DSN not configured, error tracking disabled")
        return False
    
    try:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment=SENTRY_ENVIRONMENT,
            
            # Performance monitoring
            traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
            profiles_sample_rate=SENTRY_PROFILES_SAMPLE_RATE,
            
            # Integrations
            integrations=[
                FastApiIntegration(
                    transaction_style="endpoint",
                ),
                SqlalchemyIntegration(),
                LoggingIntegration(
                    level=logging.INFO,
                    event_level=logging.ERROR,
                ),
            ],
            
            # Filter out health check endpoints from transactions
            traces_sampler=traces_sampler,
            
            # Don't send PII by default
            send_default_pii=False,
            
            # Attach request data
            max_request_body_size="medium",
            
            # Before send hook for filtering
            before_send=before_send,
            
            # Release version (use git commit hash in CI)
            release=f"gastropilot-backend@1.0.0",
        )
        
        logger.info(f"Sentry initialized for environment: {SENTRY_ENVIRONMENT}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize Sentry: {e}")
        return False


def traces_sampler(sampling_context: dict) -> float:
    """
    Custom sampler for Sentry traces.
    
    Filters out health check endpoints and adjusts sampling rate
    based on endpoint type.
    """
    transaction_context = sampling_context.get("transaction_context", {})
    name = transaction_context.get("name", "")
    
    # Don't trace health checks
    if "/health" in name or "/v1/" == name:
        return 0.0
    
    # Don't trace WebSocket connections (they're long-lived)
    if "/ws/" in name:
        return 0.01  # Very low sampling for WebSockets
    
    # Higher sampling for auth endpoints
    if "/auth/" in name:
        return min(SENTRY_TRACES_SAMPLE_RATE * 2, 1.0)
    
    return SENTRY_TRACES_SAMPLE_RATE


def before_send(event: dict, hint: dict) -> dict | None:
    """
    Filter events before sending to Sentry.
    
    Returns None to drop the event, or the modified event to send.
    """
    # Get the exception if available
    if "exc_info" in hint:
        exc_type, exc_value, tb = hint["exc_info"]
        
        # Don't log expected HTTP exceptions
        from fastapi import HTTPException
        if isinstance(exc_value, HTTPException):
            # Only log 5xx errors to Sentry
            if exc_value.status_code < 500:
                return None
    
    # Remove sensitive data from request
    if "request" in event:
        request = event["request"]
        
        # Remove Authorization header
        if "headers" in request:
            headers = request["headers"]
            if isinstance(headers, dict):
                headers.pop("Authorization", None)
                headers.pop("authorization", None)
                headers.pop("Cookie", None)
                headers.pop("cookie", None)
        
        # Mask sensitive form data
        if "data" in request and isinstance(request["data"], dict):
            for key in ["pin", "password", "secret", "token"]:
                if key in request["data"]:
                    request["data"][key] = "[FILTERED]"
    
    return event


def capture_exception(error: Exception, **context) -> str | None:
    """
    Capture an exception to Sentry with additional context.
    
    Args:
        error: The exception to capture
        **context: Additional context to attach
        
    Returns:
        The Sentry event ID, or None if Sentry is not initialized
    """
    if not SENTRY_AVAILABLE or not SENTRY_DSN:
        return None
    
    with sentry_sdk.push_scope() as scope:
        for key, value in context.items():
            scope.set_extra(key, value)
        
        return sentry_sdk.capture_exception(error)


def set_user_context(user_id: int, role: str, operator_number: str = None):
    """
    Set user context for Sentry events.
    
    Args:
        user_id: The user's ID
        role: The user's role
        operator_number: The user's operator number (optional)
    """
    if not SENTRY_AVAILABLE or not SENTRY_DSN:
        return
    
    sentry_sdk.set_user({
        "id": str(user_id),
        "role": role,
        "operator_number": operator_number,
    })


def clear_user_context():
    """Clear user context from Sentry."""
    if SENTRY_AVAILABLE and SENTRY_DSN:
        sentry_sdk.set_user(None)
