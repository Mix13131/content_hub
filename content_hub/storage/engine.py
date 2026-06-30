from __future__ import annotations

from typing import Any

from content_hub.storage.base import MediaStorage, StorageConfigurationError, StorageResult
from content_hub.storage.registry import StorageRegistry


class MediaStorageEngine:
    def __init__(self, provider: str, storage: MediaStorage) -> None:
        self.provider = provider.strip().lower()
        if not self.provider:
            raise StorageConfigurationError("Media storage provider is not configured.")
        self.storage = storage

    def upload(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> StorageResult:
        return self.storage.upload(
            key=key,
            content=content,
            content_type=content_type,
        )

    def delete(self, key: str) -> None:
        self.storage.delete(key)

    def exists(self, key: str) -> bool:
        return self.storage.exists(key)

    def public_url(self, key: str) -> str:
        return self.storage.public_url(key)


def create_media_storage_engine(settings: Any) -> MediaStorageEngine | None:
    if not settings.storage_enabled:
        return None

    provider = settings.media_storage_provider.strip().lower()
    registry = StorageRegistry()
    if provider == "s3":
        from content_hub.storage.s3 import S3CompatibleStorage

        registry.register(
            "s3",
            S3CompatibleStorage(
                endpoint_url=settings.s3_endpoint_url,
                access_key_id=settings.s3_access_key_id,
                secret_access_key=settings.s3_secret_access_key,
                bucket=settings.s3_bucket,
                region=settings.s3_region,
                public_base_url=settings.s3_public_base_url,
            ),
        )
    else:
        raise StorageConfigurationError(
            f"Unsupported media storage provider: {provider}"
        )

    return MediaStorageEngine(provider, registry.get(provider))
