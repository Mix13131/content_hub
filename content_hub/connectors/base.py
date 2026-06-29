from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from content_hub.models import Media, Post


@dataclass(frozen=True)
class ConnectorResult:
    success: bool
    external_post_id: str | None = None
    external_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw_response: dict[str, Any] | None = None
    retryable: bool = False


@dataclass(frozen=True)
class ConnectorCapabilities:
    can_publish: bool
    can_update: bool
    can_delete: bool
    supports_media: bool
    supports_albums: bool
    supports_video: bool


class Connector(Protocol):
    name: str

    def capabilities(self) -> ConnectorCapabilities:
        ...

    def validate(self, post: Post, media: list[Media]) -> ConnectorResult:
        ...

    def publish(self, post: Post, media: list[Media]) -> ConnectorResult:
        ...

    def update(self, post: Post, media: list[Media]) -> ConnectorResult:
        ...

    def delete(self, external_post_id: str) -> ConnectorResult:
        ...

