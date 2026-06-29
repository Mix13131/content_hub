from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Content Hub"
    environment: str = "local"
    database_url: str = (
        "postgresql+psycopg://content_hub:content_hub@localhost:5432/content_hub"
    )
    telegram_webhook_secret: str | None = None
    admin_api_token: str | None = None
    allowed_telegram_chat_ids: str | None = None

    @field_validator("allowed_telegram_chat_ids")
    @classmethod
    def validate_allowed_telegram_chat_ids(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        for raw_chat_id in value.split(","):
            chat_id = raw_chat_id.strip()
            if not chat_id:
                raise ValueError(
                    "CONTENT_HUB_ALLOWED_TELEGRAM_CHAT_IDS contains an empty value"
                )
            try:
                int(chat_id)
            except ValueError as exc:
                raise ValueError(
                    "CONTENT_HUB_ALLOWED_TELEGRAM_CHAT_IDS must contain integer "
                    "Telegram chat IDs separated by commas"
                ) from exc
        return value

    @property
    def allowed_telegram_chat_id_set(self) -> frozenset[int]:
        if not self.allowed_telegram_chat_ids:
            return frozenset()
        return frozenset(
            int(chat_id.strip())
            for chat_id in self.allowed_telegram_chat_ids.split(",")
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CONTENT_HUB_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
