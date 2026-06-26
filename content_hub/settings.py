from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Content Hub"
    environment: str = "local"
    database_url: str = (
        "postgresql+psycopg://content_hub:content_hub@localhost:5432/content_hub"
    )
    telegram_webhook_secret: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CONTENT_HUB_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
