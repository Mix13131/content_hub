from __future__ import annotations

from typing import Any

from content_hub.connectors.base import ConnectorCapabilities, ConnectorResult
from content_hub.enums import MediaType
from content_hub.integrations.instagram.client import (
    HttpInstagramApiClient,
    InstagramApiCredentials,
    InstagramApiError,
    InstagramClient,
    sanitize_instagram_response,
)
from content_hub.models import Media, Post
from content_hub.settings import Settings, get_settings


class InstagramConnector:
    name = "instagram"

    def __init__(
        self,
        *,
        client: InstagramClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._client = client
        self._settings = settings

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            can_publish=True,
            can_update=False,
            can_delete=False,
            supports_media=True,
            supports_albums=False,
            supports_video=False,
        )

    def validate(self, post: Post, media: list[Media]) -> ConnectorResult:
        configured = self._client is not None or self._credentials().is_configured
        if not configured:
            return self._failure(
                error_code="INSTAGRAM_NOT_CONFIGURED",
                error_message="Instagram credentials are not configured.",
                raw_response={"configured": False},
            )
        if len(media) != 1:
            return self._failure(
                error_code="INSTAGRAM_UNSUPPORTED_MEDIA_COUNT",
                error_message="Instagram MVP supports exactly one media item.",
                raw_response={"media_count": len(media)},
            )

        media_item = media[0]
        if media_item.type != MediaType.photo:
            return self._failure(
                error_code="INSTAGRAM_UNSUPPORTED_MEDIA_TYPE",
                error_message="Instagram MVP supports photo posts only.",
                raw_response={"media_type": media_item.type.value},
            )
        if not media_item.file_url or not media_item.file_url.startswith("https://"):
            return self._failure(
                error_code="INSTAGRAM_MEDIA_URL_REQUIRED",
                error_message=(
                    "Instagram publishing requires a public HTTPS media file URL."
                ),
                raw_response={"has_file_url": bool(media_item.file_url)},
            )

        return ConnectorResult(
            success=True,
            raw_response={
                "mode": "api",
                "connector": self.name,
                "mvp": "single_photo",
            },
        )

    def publish(self, post: Post, media: list[Media]) -> ConnectorResult:
        validation = self.validate(post, media)
        if not validation.success:
            return validation

        media_item = media[0]
        client = self._instagram_client()
        try:
            container = client.create_image_container(
                image_url=str(media_item.file_url),
                caption=post.text or "",
            )
            published = client.publish_container(creation_id=container.container_id)
            permalink, permalink_response = self._safe_permalink_lookup(
                client,
                published.media_id,
            )
        except InstagramApiError as exc:
            return self._api_failure(exc)

        raw_response = {
            "mode": "api",
            "connector": self.name,
            "mvp": "single_photo",
            "container": {
                "id": container.container_id,
                "response": container.raw_response,
            },
            "publish": {
                "id": published.media_id,
                "response": published.raw_response,
            },
        }
        if permalink_response is not None:
            raw_response["permalink"] = permalink_response

        return ConnectorResult(
            success=True,
            external_post_id=published.media_id,
            external_url=permalink,
            raw_response=raw_response,
        )

    def update(self, post: Post, media: list[Media]) -> ConnectorResult:
        return self._failure(
            error_code="INSTAGRAM_UPDATE_UNSUPPORTED",
            error_message="Instagram connector does not support update in MVP.",
        )

    def delete(self, external_post_id: str) -> ConnectorResult:
        return self._failure(
            error_code="INSTAGRAM_DELETE_UNSUPPORTED",
            error_message="Instagram connector does not support delete in MVP.",
        )

    def _instagram_client(self) -> InstagramClient:
        if self._client is not None:
            return self._client
        return HttpInstagramApiClient(self._credentials())

    def _credentials(self) -> InstagramApiCredentials:
        settings = self._settings or get_settings()
        return InstagramApiCredentials(
            access_token=settings.instagram_access_token,
            account_id=settings.instagram_account_id,
            graph_api_base_url=settings.meta_graph_api_base_url,
        )

    def _safe_permalink_lookup(
        self,
        client: InstagramClient,
        media_id: str,
    ) -> tuple[str | None, dict[str, Any] | None]:
        try:
            permalink = client.get_permalink(media_id=media_id)
        except InstagramApiError as exc:
            access_token = self._credentials().access_token
            return None, {
                "status": "failed",
                "error_message": str(
                    sanitize_instagram_response(
                        str(exc),
                        secrets=(access_token,),
                    )
                ),
                "raw_response": sanitize_instagram_response(
                    exc.raw_response,
                    secrets=(access_token,),
                ),
            }
        return permalink, {"status": "success", "url": permalink}

    def _api_failure(self, exc: InstagramApiError) -> ConnectorResult:
        access_token = self._credentials().access_token
        return ConnectorResult(
            success=False,
            error_code="INSTAGRAM_API_ERROR",
            error_message=str(
                sanitize_instagram_response(
                    str(exc),
                    secrets=(access_token,),
                )
            ),
            raw_response=sanitize_instagram_response(
                {
                    "mode": "api",
                    "connector": self.name,
                    "error": exc.raw_response,
                },
                secrets=(access_token,),
            ),
            retryable=exc.retryable,
        )

    def _failure(
        self,
        *,
        error_code: str,
        error_message: str,
        raw_response: dict[str, Any] | None = None,
    ) -> ConnectorResult:
        response = {
            "mode": "api",
            "connector": self.name,
        }
        if raw_response:
            response.update(raw_response)
        return ConnectorResult(
            success=False,
            error_code=error_code,
            error_message=error_message,
            raw_response=response,
            retryable=False,
        )
