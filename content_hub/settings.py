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
    telegram_bot_token: str | None = None
    admin_api_token: str | None = None
    allowed_telegram_chat_ids: str | None = None
    media_storage_provider: str = "s3"
    storage_enabled: bool = False
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_public_base_url: str | None = None
    instagram_access_token: str | None = None
    instagram_account_id: str | None = None
    facebook_page_id: str | None = None
    meta_graph_api_base_url: str = "https://graph.facebook.com/v25.0"

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

    @field_validator("media_storage_provider")
    @classmethod
    def validate_media_storage_provider(cls, value: str) -> str:
        provider = value.strip().lower()
        if not provider:
            raise ValueError("CONTENT_HUB_MEDIA_STORAGE_PROVIDER must not be empty")
        return provider

    @field_validator("meta_graph_api_base_url")
    @classmethod
    def validate_meta_graph_api_base_url(cls, value: str) -> str:
        base_url = value.strip().rstrip("/")
        if not base_url:
            raise ValueError("CONTENT_HUB_META_GRAPH_API_BASE_URL must not be empty")
        if not base_url.startswith(("https://", "http://")):
            raise ValueError(
                "CONTENT_HUB_META_GRAPH_API_BASE_URL must be an HTTP(S) URL"
            )
        return base_url

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
