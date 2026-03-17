from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

env_path = Path(__file__).parent.parent.parent.parent / ".env"
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

    DATABASE_URL: str = (
        "postgresql+asyncpg://gastropilot:gastropilot@localhost:5432/gastropilot"
    )
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

    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
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
    def ENVIRONMENT(self) -> str:
        return self.ENV

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.ENV == "development"


settings = Settings()
