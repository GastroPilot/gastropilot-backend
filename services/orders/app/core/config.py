from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "development"
    DATABASE_URL: str = (
        "postgresql+asyncpg://gastropilot_app:gastropilot_app_password@localhost:5432/gastropilot"
    )
    DATABASE_ADMIN_URL: str = (
        "postgresql+asyncpg://gastropilot_admin:gastropilot_admin_password@localhost:5432/gastropilot"
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
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"
    CORS_ORIGINS: str = "http://localhost:3001"
    CORS_ORIGIN_REGEX: str = r"https://([a-zA-Z0-9-]+\.)?gpilot\.app"
    CORS_ALLOW_CREDENTIALS: bool = True
    STRIPE_SECRET_KEY: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        return self.ENV == "development"

    @property
    def ENVIRONMENT(self) -> str:
        return self.ENV


settings = Settings()
