from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ENV: str = "development"
    SEED_ON_STARTUP: bool = False
    APP_VERSION: str = "0.16.0"

    DATABASE_URL: str = "postgresql+asyncpg://gastropilot:gastropilot@localhost:5432/gastropilot"
    DATABASE_ADMIN_URL: str = (
        "postgresql+asyncpg://gastropilot:gastropilot@localhost:5432/gastropilot"
    )

    JWT_SECRET: str = "dev-secret-key-change-in-production-min-32-characters-long"
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "gastropilot"
    JWT_AUDIENCE: str = "gastropilot-api"
    JWT_LEEWAY_SECONDS: int = 10
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    BCRYPT_ROUNDS: int = 12
    REFRESH_TOKEN_PEPPER: str = ""

    COOKIE_DOMAIN: str | None = None
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    COOKIE_PATH: str = "/"
    USE_HTTPONLY_COOKIES: bool = True

    REDIS_URL: str | None = None

    @field_validator("REDIS_URL", mode="before")
    @classmethod
    def normalize_redis_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    CORS_ORIGINS: str = "http://localhost:3001,http://127.0.0.1:3001"
    CORS_ORIGIN_REGEX: str = r"https://([a-zA-Z0-9-]+\.)?gpilot\.app"
    CORS_ALLOW_CREDENTIALS: bool = True
    WEB_PASSWORD_ONLY_ORIGINS: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "https://gpilot.app,https://www.gpilot.app,"
        "https://demo.gpilot.app,https://www.demo.gpilot.app,"
        "https://staging.gpilot.app,https://www.staging.gpilot.app,"
        "https://test.gpilot.app,https://www.test.gpilot.app"
    )

    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_PRICE_STARTER: str | None = None
    STRIPE_PRICE_PROFESSIONAL: str | None = None
    STRIPE_PRICE_ENTERPRISE: str | None = None
    SUMUP_API_KEY: str | None = None
    SUMUP_MERCHANT_CODE: str | None = None
    SUMUP_WEBHOOK_SECRET: str | None = None
    SUMUP_WEBHOOK_URL: str | None = None
    SUMUP_TEST_MODE: bool = True

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@gastropilot.org"

    OPENAI_API_KEY: str | None = None
    AI_MODEL: str = "gpt-4o-mini"

    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"

    # Upload storage: local filesystem (default) or S3/Minio
    UPLOAD_DIR: str = "/data/uploads"
    UPLOAD_PUBLIC_URL: str = "/uploads"

    # S3/Minio (optional – wenn leer wird lokaler Speicher genutzt)
    MINIO_ENDPOINT: str = "http://minio:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET: str = "gastropilot-uploads"
    MINIO_PUBLIC_URL: str = ""

    RATE_LIMIT_PER_MINUTE: int = 60
    REQUEST_TIMEOUT: int = 30

    PUBLIC_BOOKING_ENABLED: bool = False
    RESERVATION_WIDGET_URL: str = "http://localhost:3002"
    GUEST_PORTAL_URL: str = "http://localhost:3002"
    INTERNAL_API_KEY: str = "internal-secret-change-in-production"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def web_password_only_origins_list(self) -> list[str]:
        return [o.strip() for o in self.WEB_PASSWORD_ONLY_ORIGINS.split(",") if o.strip()]

    @property
    def ENVIRONMENT(self) -> str:
        return self.ENV

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.ENV == "development"


settings = Settings()
