from __future__ import annotations

from content_hub.connectors.base import ConnectorCapabilities, ConnectorResult
from content_hub.models import Media, Post
from content_hub.renderers.base import PageRenderer
from content_hub.renderers.html_renderer import HtmlRenderer


class TildaConnector:
    name = "tilda"

    def __init__(self, renderer: PageRenderer | None = None) -> None:
        self.renderer = renderer or HtmlRenderer()

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
                error_code="TILDA_SLUG_MISSING",
                error_message="Tilda preview requires post.slug",
            )
        return ConnectorResult(success=True)

    def publish(self, post: Post, media: list[Media]) -> ConnectorResult:
        validation = self.validate(post, media)
        if not validation.success:
            return validation

        page = self.renderer.render(post, media)
        return ConnectorResult(
            success=True,
            external_url=f"tilda-preview://{page.slug}",
            raw_response={
                "mode": "preview",
                "html_length": len(page.html),
            },
        )

    def update(self, post: Post, media: list[Media]) -> ConnectorResult:
        return ConnectorResult(
            success=False,
            error_code="TILDA_UPDATE_UNSUPPORTED",
            error_message="Tilda preview connector does not support update",
        )

    def delete(self, external_post_id: str) -> ConnectorResult:
        return ConnectorResult(
            success=False,
            error_code="TILDA_DELETE_UNSUPPORTED",
            error_message="Tilda preview connector does not support delete",
        )
