from __future__ import annotations

from content_hub.connectors.base import (
    ConnectorCapabilities,
    ConnectorResult,
)
from content_hub.models import Media, Post


class WebsiteConnector:
    name = "website"

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            can_publish=True,
            can_update=False,
            can_delete=False,
            supports_media=True,
            supports_albums=True,
            supports_video=True,
        )

    def validate(self, post: Post, media: list[Media]) -> ConnectorResult:
        if not post.slug:
            return ConnectorResult(
                success=False,
                error_code="WEBSITE_SLUG_MISSING",
                error_message="Website publication requires post.slug",
            )
        return ConnectorResult(success=True, raw_response=self._raw_response())

    def publish(self, post: Post, media: list[Media]) -> ConnectorResult:
        validation = self.validate(post, media)
        if not validation.success:
            return validation

        return ConnectorResult(
            success=True,
            external_post_id=str(post.id),
            external_url=f"/news/{post.slug}",
            raw_response=self._raw_response(),
        )

    def update(self, post: Post, media: list[Media]) -> ConnectorResult:
        return ConnectorResult(
            success=False,
            error_code="WEBSITE_UPDATE_UNSUPPORTED",
            error_message="Website connector does not support update",
        )

    def delete(self, external_post_id: str) -> ConnectorResult:
        return ConnectorResult(
            success=False,
            error_code="WEBSITE_DELETE_UNSUPPORTED",
            error_message="Website connector does not support delete",
        )

    def _raw_response(self) -> dict[str, str]:
        return {
            "mode": "internal",
            "connector": self.name,
            "visibility": "public",
        }
