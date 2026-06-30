from __future__ import annotations

from content_hub.storage.base import MediaStorage


class StorageRegistry:
    def __init__(self) -> None:
        self._storages: dict[str, MediaStorage] = {}

    def register(self, name: str, storage: MediaStorage) -> None:
        provider = self._normalize_name(name)
        self._storages[provider] = storage

    def get(self, name: str) -> MediaStorage:
        provider = self._normalize_name(name)
        try:
            return self._storages[provider]
        except KeyError as exc:
            raise KeyError(f"Storage provider is not registered: {provider}") from exc

    def providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._storages))

    def _normalize_name(self, name: str) -> str:
        provider = name.strip().lower()
        if not provider:
            raise ValueError("Storage provider name must not be empty.")
        return provider
