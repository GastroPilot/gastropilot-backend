from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    ENV: str = "development"
    REDIS_URL: str | None = None
    OPENAI_API_KEY: str | None = None
    AI_MODEL: str = "gpt-4o-mini"
    CORS_ORIGINS: str = "http://localhost:3001"
    CORS_ORIGIN_REGEX: str = r"https://([a-zA-Z0-9-]+\.)?gpilot\.app"
    CORS_ALLOW_CREDENTIALS: bool = True

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        return self.ENV == "development"


settings = Settings()
