import os
import warnings
from pathlib import Path

from dotenv import load_dotenv

# Load .env file - try to find it in the current directory or parent directories
ENV = os.getenv("ENV", "development")

# Try to load .env file from current directory or app directory
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # Fallback: try current working directory
    load_dotenv()


def _getenv_str(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise ValueError(f"{name} must be set")
    return value  # type: ignore[return-value]


# Database
if ENV == "development":
    DATABASE_URL = _getenv_str("DATABASE_URL", default="sqlite+aiosqlite:///./reservation_dev.db")
    if "sqlite" in DATABASE_URL:
        warnings.warn(
            "⚠️  Using SQLite database in development. " "Set DATABASE_URL in .env for PostgreSQL!",
            UserWarning,
        )
else:
    DATABASE_URL = _getenv_str("DATABASE_URL", required=True)

# DB_TYPE automatisch erkennen
_db_type_env = os.getenv("DATABASE_TYPE", "").lower().strip()
if _db_type_env in ["sqlite", "neon", "postgresql"]:
    DB_TYPE = _db_type_env
elif "sqlite" in DATABASE_URL.lower() or DATABASE_URL.startswith("sqlite"):
    DB_TYPE = "sqlite"
elif "postgresql" in DATABASE_URL.lower() or DATABASE_URL.startswith("postgresql"):
    DB_TYPE = "neon"  # "neon" wird für PostgreSQL verwendet
else:
    # Default: SQLite für Development
    if ENV == "development":
        DB_TYPE = "sqlite"
        warnings.warn(
            f"⚠️  Could not detect database type from URL, defaulting to SQLite. "
            f"URL: {DATABASE_URL[:50]}...",
            UserWarning,
        )
    else:
        DB_TYPE = "neon"
        warnings.warn(
            f"⚠️  Could not detect database type from URL, defaulting to Neon/PostgreSQL. "
            f"URL: {DATABASE_URL[:50]}...",
            UserWarning,
        )

# JWT / Security
if ENV == "development":
    _default_jwt_secret = "dev-secret-key-change-in-production-min-32-characters-long"
    JWT_SECRET = _getenv_str("JWT_SECRET", default=_default_jwt_secret)
    if JWT_SECRET == _default_jwt_secret:
        warnings.warn(
            "⚠️  WARNING: Using default JWT_SECRET in development. "
            "Set JWT_SECRET in .env for production!",
            UserWarning,
        )
else:
    JWT_SECRET = _getenv_str("JWT_SECRET", required=True)

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ISSUER = os.getenv("JWT_ISSUER", "reservation-app")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "reservation-api")
JWT_LEEWAY_SECONDS = int(os.getenv("JWT_LEEWAY_SECONDS", "10"))

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
# Optional pepper for refresh token hashing
REFRESH_TOKEN_PEPPER = os.getenv("REFRESH_TOKEN_PEPPER", "")

# Cookie settings for HttpOnly tokens
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", None)  # None = same domain only
COOKIE_SECURE = (
    os.getenv("COOKIE_SECURE", "false" if ENV == "development" else "true").lower() == "true"
)
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")  # "lax", "strict", or "none"
COOKIE_PATH = os.getenv("COOKIE_PATH", "/")
# Set to True to use HttpOnly cookies instead of response body tokens
USE_HTTPONLY_COOKIES = os.getenv("USE_HTTPONLY_COOKIES", "true").lower() == "true"

# Password hashing
BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", "12"))

# Redis for Rate Limiting
# If REDIS_URL is not set, slowapi uses in-memory storage (per-process, not distributed).
# For production with multiple workers/pods, set REDIS_URL to enable distributed rate limiting.
# Example: REDIS_URL=redis://localhost:6379/0
REDIS_URL = os.getenv("REDIS_URL")

# Request Timeout (seconds)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = os.getenv("LOG_FORMAT", "json")  # "json" or "text"
LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
LOG_FILE_NAME = os.getenv("LOG_FILE_NAME", "tischbot_api_logs.log")
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "14"))
LOG_MAX_TOTAL_BYTES = int(os.getenv("LOG_MAX_TOTAL_BYTES", str(50 * 1024 * 1024)))
ACTIVITY_LOGGING_ENABLED = os.getenv("ACTIVITY_LOGGING_ENABLED", "true").lower() == "true"

# CORS Configuration
# Development origins (explicit list)
_dev_origins = [
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:8001",
    "http://127.0.0.1:8001",
    "http://localhost:8081",
    "http://127.0.0.1:8081",
]

# Allow custom origins via environment variable
_env_origins = os.getenv("CORS_ORIGINS", "")
if _env_origins:
    CORS_ORIGINS = [origin.strip() for origin in _env_origins.split(",") if origin.strip()]
else:
    CORS_ORIGINS = _dev_origins

# Regex pattern for dynamic origin matching (e.g., all *.gpilot.app subdomains)
# This allows any subdomain without code changes when new customers are added
# Pattern: https://(www.|test.|staging.|demo.|<kunde>.)gpilot.app
CORS_ORIGIN_REGEX = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"https://([a-zA-Z0-9-]+\.)?gpilot\.app"
)
CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "True").lower() == "true"
CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
CORS_ALLOW_HEADERS = [
    "Content-Type",
    "Authorization",
    "Accept",
    "Accept-Language",
    "Cache-Control",
    "X-Requested-With",
]

# Security Headers
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS]

# License / Feature Management
LICENSE_KEY = os.getenv("LICENSE_KEY", "")  # Lizenzschlüssel für Kommunikation mit Mutterschiff
MOTHERSHIP_URL = os.getenv(
    "MOTHERSHIP_URL", "https://mothership.servecta.com"
)  # URL des Hauptservers
LICENSE_CHECK_INTERVAL = int(
    os.getenv("LICENSE_CHECK_INTERVAL", "3600")
)  # Intervall für License-Checks in Sekunden (default: 1 Stunde)
LICENSE_CHECK_TIMEOUT = int(
    os.getenv("LICENSE_CHECK_TIMEOUT", "5")
)  # Timeout für License-Checks in Sekunden

# Sentry Error Tracking
SENTRY_DSN = os.getenv("SENTRY_DSN", "")  # Leave empty to disable Sentry
SENTRY_ENVIRONMENT = os.getenv("SENTRY_ENVIRONMENT", ENV)
SENTRY_TRACES_SAMPLE_RATE = float(
    os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")
)  # 10% of transactions
SENTRY_PROFILES_SAMPLE_RATE = float(
    os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.1")
)  # 10% of sampled transactions

# AI / OpenAI Configuration
AI_ENABLED = os.getenv("AI_ENABLED", "false").lower() == "true"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "500"))
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.3"))

# Twilio Configuration (for SMS and WhatsApp)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")  # For SMS
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "")  # e.g., "whatsapp:+14155238886"

# Email Configuration (SMTP)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "noreply@gastropilot.org")


# Public Booking Configuration
PUBLIC_BOOKING_ENABLED = os.getenv("PUBLIC_BOOKING_ENABLED", "false").lower() == "true"
PUBLIC_BOOKING_DEFAULT_DURATION = int(os.getenv("PUBLIC_BOOKING_DEFAULT_DURATION", "120"))
RESERVATION_WIDGET_URL = os.getenv(
    "RESERVATION_WIDGET_URL", "http://localhost:3002"
)  # URL zum Reservation Widget

# SumUp Configuration
SUMUP_API_KEY = os.getenv("SUMUP_API_KEY", "")  # SumUp API Key (sk_test_... oder sk_live_...)
SUMUP_MERCHANT_CODE = os.getenv("SUMUP_MERCHANT_CODE", "")  # SumUp Merchant Code (z.B. "MH4H92C7")
SUMUP_WEBHOOK_SECRET = os.getenv("SUMUP_WEBHOOK_SECRET", "")  # Secret für Webhook-Verifizierung
SUMUP_WEBHOOK_URL = os.getenv(
    "SUMUP_WEBHOOK_URL", ""
)  # Öffentliche URL für Webhooks (z.B. https://api.example.com/webhooks/sumup)
SUMUP_TEST_MODE = (
    os.getenv("SUMUP_TEST_MODE", "true").lower() == "true"
)  # Testmodus: true = Checkout ohne Reader, false = Reader Checkout
