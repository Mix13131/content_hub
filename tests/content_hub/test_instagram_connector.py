import json
import uuid
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from content_hub.app import create_app
from content_hub.connectors.engine import ConnectorEngine
from content_hub.connectors.instagram import InstagramConnector
from content_hub.connectors.registry import ConnectorRegistry
from content_hub.connectors.website import WebsiteConnector
from content_hub.db import get_db
from content_hub.enums import MediaType, PlatformStatus, PublicationPlatform
from content_hub.integrations.instagram.client import (
    InstagramApiError,
    InstagramContainerResult,
    InstagramPublishResult,
)
from content_hub.models import Media, Post, PublicationJob, PublicationLog
from content_hub.services.telegram_ingestion import TelegramIngestionService
from content_hub.settings import Settings, get_settings


FIXTURES_DIR = Path(__file__).parent / "fixtures"
ADMIN_TOKEN = "local-admin-token"
INSTAGRAM_TOKEN = "secret-instagram-token"


@dataclass
class FakeInstagramClient:
    container_id: str = "ig-container-123"
    media_id: str = "ig-media-456"
    permalink: str | None = "https://instagram.example/p/ig-media-456"
    create_error: InstagramApiError | None = None
    publish_error: InstagramApiError | None = None
    permalink_error: InstagramApiError | None = None
    created_payloads: list[dict[str, str]] = field(default_factory=list)
    published_creation_ids: list[str] = field(default_factory=list)
    permalink_media_ids: list[str] = field(default_factory=list)

    def create_image_container(
        self,
        *,
        image_url: str,
        caption: str,
    ) -> InstagramContainerResult:
        if self.create_error is not None:
            raise self.create_error
        self.created_payloads.append({"image_url": image_url, "caption": caption})
        return InstagramContainerResult(
            container_id=self.container_id,
            raw_response={"id": self.container_id},
        )

    def publish_container(self, *, creation_id: str) -> InstagramPublishResult:
        if self.publish_error is not None:
            raise self.publish_error
        self.published_creation_ids.append(creation_id)
        return InstagramPublishResult(
            media_id=self.media_id,
            raw_response={"id": self.media_id},
        )

    def get_permalink(self, *, media_id: str) -> str | None:
        if self.permalink_error is not None:
            raise self.permalink_error
        self.permalink_media_ids.append(media_id)
        return self.permalink


@pytest.fixture()
def admin_client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    def override_get_settings() -> Settings:
        return Settings(
            database_url="sqlite://",
            telegram_webhook_secret=None,
            admin_api_token=ADMIN_TOKEN,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def admin_headers() -> dict[str, str]:
    return {"X-Content-Hub-Admin-Token": ADMIN_TOKEN}


def instagram_settings() -> Settings:
    return Settings(
        database_url="sqlite://",
        instagram_access_token=INSTAGRAM_TOKEN,
        instagram_account_id="17841400000000000",
        meta_graph_api_base_url="https://graph.facebook.com/v25.0",
    )


def create_photo_post(
    db_session: Session,
    *,
    file_url: str | None = "https://cdn.example/instagram-photo.jpg",
) -> tuple[Post, Media, dict[PublicationPlatform, PublicationJob]]:
    result = TelegramIngestionService().ingest_update(
        load_fixture("telegram_photo_channel_post.json"),
        db_session,
    )
    assert result.post_id is not None
    post = db_session.get(Post, uuid.UUID(result.post_id))
    assert post is not None
    media = db_session.scalar(select(Media).where(Media.post_id == post.id))
    assert media is not None
    media.file_url = file_url
    media.storage_key = "telegram/test/photo.jpg" if file_url else None
    db_session.commit()
    db_session.refresh(post)
    db_session.refresh(media)
    jobs = db_session.scalars(
        select(PublicationJob).where(PublicationJob.post_id == post.id)
    ).all()
    return post, media, {job.platform: job for job in jobs}


def create_video_post(
    db_session: Session,
    *,
    file_url: str | None = "https://cdn.example/instagram-video.mp4",
) -> tuple[Post, Media]:
    result = TelegramIngestionService().ingest_update(
        load_fixture("telegram_video_channel_post.json"),
        db_session,
    )
    assert result.post_id is not None
    post = db_session.get(Post, uuid.UUID(result.post_id))
    assert post is not None
    media = db_session.scalar(select(Media).where(Media.post_id == post.id))
    assert media is not None
    media.file_url = file_url
    db_session.commit()
    db_session.refresh(post)
    db_session.refresh(media)
    return post, media


def test_instagram_connector_validates_single_photo_with_file_url(
    db_session: Session,
) -> None:
    post, media, _ = create_photo_post(db_session)

    result = InstagramConnector(
        client=FakeInstagramClient(),
        settings=instagram_settings(),
    ).validate(post, [media])

    assert result.success is True


def test_instagram_connector_missing_credentials_returns_controlled_error(
    db_session: Session,
) -> None:
    post, media, _ = create_photo_post(db_session)

    result = InstagramConnector(
        settings=Settings(
            database_url="sqlite://",
            instagram_access_token=None,
            instagram_account_id=None,
        )
    ).publish(post, [media])

    assert result.success is False
    assert result.error_code == "INSTAGRAM_NOT_CONFIGURED"
    assert result.retryable is False


def test_instagram_connector_requires_https_file_url(db_session: Session) -> None:
    post, media, _ = create_photo_post(db_session, file_url=None)

    result = InstagramConnector(
        client=FakeInstagramClient(),
        settings=instagram_settings(),
    ).publish(post, [media])

    assert result.success is False
    assert result.error_code == "INSTAGRAM_MEDIA_URL_REQUIRED"
    assert result.retryable is False


def test_instagram_connector_rejects_multiple_media(db_session: Session) -> None:
    post, media, _ = create_photo_post(db_session)
    extra_media = Media(
        post_id=post.id,
        type=MediaType.photo,
        file_url="https://cdn.example/another-photo.jpg",
        storage_key="telegram/test/another-photo.jpg",
        telegram_file_id="another-file-id",
        telegram_file_unique_id="another-file-unique-id",
        sort_order=1,
    )

    result = InstagramConnector(
        client=FakeInstagramClient(),
        settings=instagram_settings(),
    ).publish(post, [media, extra_media])

    assert result.success is False
    assert result.error_code == "INSTAGRAM_UNSUPPORTED_MEDIA_COUNT"


def test_instagram_connector_rejects_video(db_session: Session) -> None:
    post, media = create_video_post(db_session)

    result = InstagramConnector(
        client=FakeInstagramClient(),
        settings=instagram_settings(),
    ).publish(post, [media])

    assert result.success is False
    assert result.error_code == "INSTAGRAM_UNSUPPORTED_MEDIA_TYPE"


def test_instagram_connector_success_publishes_photo(db_session: Session) -> None:
    post, media, _ = create_photo_post(db_session)
    fake_client = FakeInstagramClient()

    result = InstagramConnector(
        client=fake_client,
        settings=instagram_settings(),
    ).publish(post, [media])

    assert result.success is True
    assert result.external_post_id == "ig-media-456"
    assert result.external_url == "https://instagram.example/p/ig-media-456"
    assert fake_client.created_payloads == [
        {
            "image_url": "https://cdn.example/instagram-photo.jpg",
            "caption": "Фото новой спальни с матрасом",
        }
    ]
    assert fake_client.published_creation_ids == ["ig-container-123"]
    assert fake_client.permalink_media_ids == ["ig-media-456"]
    assert result.raw_response is not None
    assert result.raw_response["container"]["id"] == "ig-container-123"
    assert result.raw_response["publish"]["id"] == "ig-media-456"


def test_instagram_connector_permalink_failure_still_succeeds(
    db_session: Session,
) -> None:
    post, media, _ = create_photo_post(db_session)
    fake_client = FakeInstagramClient(
        permalink_error=InstagramApiError(
            f"Permalink lookup failed for {INSTAGRAM_TOKEN}.",
            raw_response={
                "error": {"message": f"Temporary issue for {INSTAGRAM_TOKEN}"}
            },
            retryable=True,
        )
    )

    result = InstagramConnector(
        client=fake_client,
        settings=instagram_settings(),
    ).publish(post, [media])

    assert result.success is True
    assert result.external_post_id == "ig-media-456"
    assert result.external_url is None
    assert result.raw_response is not None
    assert result.raw_response["permalink"]["status"] == "failed"
    assert INSTAGRAM_TOKEN not in json.dumps(result.raw_response)


def test_instagram_api_error_sanitizes_token_and_is_retryable(
    db_session: Session,
) -> None:
    post, media, _ = create_photo_post(db_session)
    fake_client = FakeInstagramClient(
        create_error=InstagramApiError(
            f"Instagram API rejected {INSTAGRAM_TOKEN}",
            raw_response={
                "access_token": INSTAGRAM_TOKEN,
                "error": {"message": f"Bad token {INSTAGRAM_TOKEN}"},
            },
            retryable=True,
        )
    )

    result = InstagramConnector(
        client=fake_client,
        settings=instagram_settings(),
    ).publish(post, [media])

    assert result.success is False
    assert result.error_code == "INSTAGRAM_API_ERROR"
    assert result.retryable is True
    assert result.error_message is not None
    assert INSTAGRAM_TOKEN not in result.error_message
    assert result.raw_response is not None
    assert INSTAGRAM_TOKEN not in json.dumps(result.raw_response)


def test_instagram_engine_updates_job_and_post_status(db_session: Session) -> None:
    post, media, jobs = create_photo_post(db_session)
    fake_client = FakeInstagramClient()
    registry = ConnectorRegistry()
    registry.register(WebsiteConnector())
    registry.register(
        InstagramConnector(client=fake_client, settings=instagram_settings())
    )
    job = jobs[PublicationPlatform.instagram]

    ConnectorEngine(registry=registry).publish_job(job.id, db_session)

    db_session.refresh(job)
    db_session.refresh(post)
    assert job.status == PlatformStatus.Success
    assert job.external_post_id == "ig-media-456"
    assert job.external_url == "https://instagram.example/p/ig-media-456"
    assert post.instagram_status == PlatformStatus.Success
    assert fake_client.created_payloads[0]["image_url"] == media.file_url


def test_admin_run_instagram_endpoint_uses_fake_client(
    admin_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post, _, _ = create_photo_post(db_session)
    fake_client = FakeInstagramClient()

    def fake_default_registry() -> ConnectorRegistry:
        registry = ConnectorRegistry()
        registry.register(WebsiteConnector())
        registry.register(
            InstagramConnector(client=fake_client, settings=instagram_settings())
        )
        return registry

    monkeypatch.setattr(
        "content_hub.connectors.engine.default_connector_registry",
        fake_default_registry,
    )

    response = admin_client.post(
        f"/admin/posts/{post.id}/run/{PublicationPlatform.instagram.value}",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["instagram_status"] == PlatformStatus.Success.value
    instagram_job = next(
        job for job in body["jobs"] if job["platform"] == "instagram"
    )
    assert instagram_job["status"] == PlatformStatus.Success.value
    assert instagram_job["external_post_id"] == "ig-media-456"
    assert instagram_job["external_url"] == "https://instagram.example/p/ig-media-456"
    assert fake_client.created_payloads


def test_instagram_api_error_updates_job_without_token_leak(
    db_session: Session,
) -> None:
    post, _, jobs = create_photo_post(db_session)
    fake_client = FakeInstagramClient(
        create_error=InstagramApiError(
            f"Rate limited for {INSTAGRAM_TOKEN}",
            raw_response={
                "error": {
                    "message": f"Rate limited for {INSTAGRAM_TOKEN}",
                    "code": 4,
                }
            },
            retryable=True,
        )
    )
    registry = ConnectorRegistry()
    registry.register(
        InstagramConnector(client=fake_client, settings=instagram_settings())
    )
    job = jobs[PublicationPlatform.instagram]

    ConnectorEngine(registry=registry).publish_job(job.id, db_session)

    db_session.refresh(job)
    db_session.refresh(post)
    assert job.status == PlatformStatus.Retry
    assert job.last_error_code == "INSTAGRAM_API_ERROR"
    assert job.last_error_message is not None
    assert INSTAGRAM_TOKEN not in job.last_error_message
    assert job.last_api_response is not None
    assert INSTAGRAM_TOKEN not in json.dumps(job.last_api_response)
    logs = db_session.scalars(
        select(PublicationLog).where(PublicationLog.job_id == job.id)
    ).all()
    assert all(INSTAGRAM_TOKEN not in (log.error_text or "") for log in logs)
