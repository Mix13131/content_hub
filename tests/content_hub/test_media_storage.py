from __future__ import annotations

import pytest

from content_hub.storage import MediaStorageEngine, StorageRegistry, StorageResult
from content_hub.storage.base import StorageConfigurationError
from content_hub.storage.engine import create_media_storage_engine
from content_hub.storage.s3 import S3CompatibleStorage
from content_hub.settings import Settings


class FakeStorage:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.uploaded: list[tuple[str, bytes, str | None]] = []

    def upload(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> StorageResult:
        self.uploaded.append((key, content, content_type))
        return StorageResult(
            storage_key=key,
            file_url=f"https://cdn.example/{key}",
            provider="fake",
            content_type=content_type,
            size_bytes=len(content),
        )

    def delete(self, key: str) -> None:
        self.deleted.append(key)

    def exists(self, key: str) -> bool:
        return key == "existing-key"

    def public_url(self, key: str) -> str:
        return f"https://cdn.example/{key}"


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def put_object(self, **kwargs: object) -> None:
        key = str(kwargs["Key"])
        self.objects[key] = bytes(kwargs["Body"])  # type: ignore[arg-type]

    def head_object(self, **kwargs: object) -> None:
        key = str(kwargs["Key"])
        if key not in self.objects:
            raise FakeS3NotFound()

    def delete_object(self, **kwargs: object) -> None:
        self.deleted.append(str(kwargs["Key"]))


class FakeS3NotFound(Exception):
    response = {
        "Error": {"Code": "NoSuchKey"},
        "ResponseMetadata": {"HTTPStatusCode": 404},
    }


def test_storage_registry_registers_by_provider_name() -> None:
    storage = FakeStorage()
    registry = StorageRegistry()

    registry.register(" S3 ", storage)

    assert registry.get("s3") is storage
    assert registry.providers() == ("s3",)


def test_media_storage_engine_delegates_to_provider() -> None:
    storage = FakeStorage()
    engine = MediaStorageEngine("fake", storage)

    result = engine.upload(
        key="telegram/1/2/photo-abc.jpg",
        content=b"image",
        content_type="image/jpeg",
    )
    assert result.file_url == "https://cdn.example/telegram/1/2/photo-abc.jpg"
    assert engine.exists("existing-key") is True
    assert engine.exists("missing-key") is False
    assert engine.public_url("existing-key") == "https://cdn.example/existing-key"

    engine.delete("existing-key")

    assert storage.deleted == ["existing-key"]


def test_create_media_storage_engine_returns_none_when_disabled() -> None:
    settings = Settings(storage_enabled=False)

    assert create_media_storage_engine(settings) is None


def test_create_media_storage_engine_rejects_unknown_provider() -> None:
    settings = Settings(
        storage_enabled=True,
        media_storage_provider="unknown",
    )

    with pytest.raises(StorageConfigurationError):
        create_media_storage_engine(settings)


def test_s3_compatible_storage_uses_path_style_public_url() -> None:
    client = FakeS3Client()
    storage = S3CompatibleStorage(
        endpoint_url="https://storage.example",
        access_key_id="access",
        secret_access_key="secret",
        bucket="content-hub",
        public_base_url=None,
        client=client,
    )

    assert storage.exists("telegram/1/2/photo-a.jpg") is False
    result = storage.upload(
        key="telegram/1/2/photo-a.jpg",
        content=b"image",
        content_type="image/jpeg",
    )

    assert result.storage_key == "telegram/1/2/photo-a.jpg"
    assert result.file_url == (
        "https://storage.example/content-hub/telegram/1/2/photo-a.jpg"
    )
    assert storage.exists("telegram/1/2/photo-a.jpg") is True

    storage.delete("telegram/1/2/photo-a.jpg")

    assert client.deleted == ["telegram/1/2/photo-a.jpg"]


def test_s3_compatible_storage_uses_public_base_url() -> None:
    storage = S3CompatibleStorage(
        endpoint_url="https://storage.example",
        access_key_id="access",
        secret_access_key="secret",
        bucket="content-hub",
        public_base_url="https://cdn.example/media",
        client=FakeS3Client(),
    )

    assert storage.public_url("telegram/-100/2/photo-a b.jpg") == (
        "https://cdn.example/media/telegram/-100/2/photo-a%20b.jpg"
    )
