from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class StorageError(RuntimeError):
    """Base error for storage operations with safe, non-secret messages."""


class StorageConfigurationError(StorageError):
    """Raised when a storage provider cannot be configured safely."""


@dataclass(frozen=True)
class StorageResult:
    storage_key: str
    file_url: str
    provider: str
    content_type: str | None = None
    size_bytes: int | None = None


@runtime_checkable
class MediaStorage(Protocol):
    def upload(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> StorageResult:
        ...

    def delete(self, key: str) -> None:
        ...

    def exists(self, key: str) -> bool:
        ...

    def public_url(self, key: str) -> str:
        ...
