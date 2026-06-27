import json
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from content_hub.app import create_app
from content_hub.db import get_db
from content_hub.enums import PlatformStatus, PostStatus, PostType, PublicationPlatform
from content_hub.models import Media, Post, PublicationJob
from content_hub.services.publication_status import PublicationStatusService
from content_hub.services.telegram_ingestion import TelegramIngestionService
from content_hub.settings import Settings, get_settings


FIXTURES_DIR = Path(__file__).parent / "fixtures"
ADMIN_TOKEN = "local-admin-token"


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


def create_post_from_fixture(db_session: Session, fixture_name: str) -> Post:
    result = TelegramIngestionService().ingest_update(
        load_fixture(fixture_name),
        db_session,
    )
    assert result.post_id is not None
    post = db_session.get(Post, uuid.UUID(result.post_id))
    assert post is not None
    return post


def admin_headers() -> dict[str, str]:
    return {"X-Content-Hub-Admin-Token": ADMIN_TOKEN}


def test_admin_posts_require_token_when_configured(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    missing_response = admin_client.get("/admin/posts")
    wrong_response = admin_client.get(
        "/admin/posts",
        headers={"X-Content-Hub-Admin-Token": "wrong-token"},
    )
    correct_response = admin_client.get("/admin/posts", headers=admin_headers())

    assert missing_response.status_code == 403
    assert wrong_response.status_code == 403
    assert correct_response.status_code == 200


def test_admin_posts_allow_access_without_configured_token(
    client: TestClient,
    db_session: Session,
) -> None:
    create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = client.get("/admin/posts")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_admin_posts_returns_summaries_and_filters(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    text_post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    create_post_from_fixture(db_session, "telegram_photo_channel_post.json")

    website_job = db_session.scalar(
        select(PublicationJob).where(
            PublicationJob.post_id == text_post.id,
            PublicationJob.platform == PublicationPlatform.website,
        )
    )
    assert website_job is not None
    PublicationStatusService().start_job(website_job.id, db_session)

    response = admin_client.get(
        "/admin/posts",
        params={
            "status": PostStatus.queued.value,
            "post_type": PostType.text.value,
            "platform": PublicationPlatform.website.value,
            "platform_status": PlatformStatus.Publishing.value,
        },
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(text_post.id)
    assert body[0]["telegram_post_id"] == 42
    assert body[0]["post_type"] == PostType.text.value
    assert body[0]["status"] == PostStatus.queued.value
    assert body[0]["website_status"] == PlatformStatus.Publishing.value
    assert body[0]["text_preview"] == "Новый пост о матрасах и уютной спальне"


def test_get_admin_post_detail_returns_post_media_jobs_and_logs(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")
    media = db_session.scalar(select(Media).where(Media.post_id == post.id))
    assert media is not None

    response = admin_client.get(f"/admin/posts/{post.id}", headers=admin_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(post.id)
    assert body["text"] == "Фото новой спальни с матрасом"
    assert body["telegram_message_ids"] == [43]
    assert body["media"][0]["id"] == str(media.id)
    assert body["media"][0]["telegram_file_id"] == "photo-large-file-id"
    assert body["media"][0]["file_url"] is None
    assert body["media"][0]["storage_key"] is None
    assert len(body["jobs"]) == 4
    assert {job["platform"] for job in body["jobs"]} == {
        PublicationPlatform.website.value,
        PublicationPlatform.instagram.value,
        PublicationPlatform.vk.value,
        PublicationPlatform.facebook.value,
    }
    assert body["logs"][0]["event"] == "publication_jobs_created"


def test_unknown_admin_post_returns_404(admin_client: TestClient) -> None:
    response = admin_client.get(
        f"/admin/posts/{uuid.uuid4()}",
        headers=admin_headers(),
    )

    assert response.status_code == 404
