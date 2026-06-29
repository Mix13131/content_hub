import json
import logging
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from content_hub.enums import (
    ContentSource,
    MediaType,
    PlatformStatus,
    PostStatus,
    PostType,
    PublicationLogLevel,
    PublicationPlatform,
)
from content_hub.models import Media, Post, PublicationJob, PublicationLog
from content_hub.services.telegram_ingestion import TelegramIngestionService


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


MVP_PLATFORMS = {
    PublicationPlatform.website,
    PublicationPlatform.instagram,
    PublicationPlatform.vk,
    PublicationPlatform.facebook,
}


def assert_publication_jobs_created(
    db_session: Session,
    post: Post,
) -> list[PublicationJob]:
    jobs = db_session.scalars(
        select(PublicationJob).where(PublicationJob.post_id == post.id)
    ).all()
    assert len(jobs) == 4
    assert {job.platform for job in jobs} == MVP_PLATFORMS
    for job in jobs:
        assert job.status == PlatformStatus.Waiting
        assert job.attempt_count == 0
        assert job.max_attempts == 5
        assert job.next_retry_at is None
        assert job.external_post_id is None
        assert job.external_url is None
        assert job.last_error_code is None
        assert job.last_error_message is None
        assert job.last_api_response is None
    return jobs


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_accepts_text_channel_post(client: TestClient, db_session: Session) -> None:
    payload = load_fixture("telegram_text_channel_post.json")

    response = client.post("/webhooks/telegram", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["ignored"] is False
    assert body["created"] is True
    assert body["post_id"]
    assert str(uuid.UUID(body["post_id"])) == body["post_id"]

    posts = db_session.scalars(select(Post)).all()
    assert len(posts) == 1
    assert posts[0].status == PostStatus.queued
    assert_publication_jobs_created(db_session, posts[0])


def test_telegram_webhook_stdout_diagnostics_for_channel_post(
    client: TestClient,
    capsys,
) -> None:
    payload = load_fixture("telegram_text_channel_post.json")

    response = client.post("/webhooks/telegram", json=payload)

    assert response.status_code == 200
    stdout = capsys.readouterr().out
    assert "CONTENT_HUB_TELEGRAM_UPDATE_RECEIVED" in stdout
    assert "keys=update_id,channel_post" in stdout
    assert "update_type=channel_post" in stdout
    assert "CONTENT_HUB_TELEGRAM_UPDATE_RESULT" in stdout
    assert "ignored=False" in stdout
    assert "created=True" in stdout


def test_message_update_is_ignored_with_supported_reason(
    client: TestClient,
    db_session: Session,
    capsys,
) -> None:
    payload = {
        "update_id": 1001,
        "message": {
            "message_id": 7,
            "text": "This text must not be saved",
        },
    }

    response = client.post("/webhooks/telegram", json=payload)

    assert response.status_code == 200
    assert response.json()["ignored"] is True
    assert response.json()["created"] is False
    assert response.json()["reason"] == "unsupported_update_type"
    assert db_session.scalars(select(Post)).all() == []
    stdout = capsys.readouterr().out
    assert "CONTENT_HUB_TELEGRAM_UPDATE_RECEIVED" in stdout
    assert "update_type=message" in stdout
    assert "CONTENT_HUB_TELEGRAM_UPDATE_RESULT" in stdout
    assert "ignored=True" in stdout
    assert "reason=unsupported_update_type" in stdout
    assert "This text must not be saved" not in stdout


def test_my_chat_member_update_is_ignored_with_supported_reason(
    client: TestClient,
    db_session: Session,
    capsys,
) -> None:
    payload = {
        "update_id": 1002,
        "my_chat_member": {
            "chat": {"id": -1001234567890, "type": "channel"},
            "new_chat_member": {"status": "administrator"},
        },
    }

    response = client.post("/webhooks/telegram", json=payload)

    assert response.status_code == 200
    assert response.json()["ignored"] is True
    assert response.json()["created"] is False
    assert response.json()["reason"] == "unsupported_update_type"
    assert db_session.scalars(select(Post)).all() == []
    stdout = capsys.readouterr().out
    assert "CONTENT_HUB_TELEGRAM_UPDATE_RECEIVED" in stdout
    assert "update_type=my_chat_member" in stdout
    assert "CONTENT_HUB_TELEGRAM_UPDATE_RESULT" in stdout
    assert "ignored=True" in stdout


def test_safe_telegram_stdout_diagnostics_do_not_expose_payload_data(
    client: TestClient,
    capsys,
) -> None:
    payload = load_fixture("telegram_photo_channel_post.json")

    response = client.post("/webhooks/telegram", json=payload)

    assert response.status_code == 200
    stdout = capsys.readouterr().out
    assert "CONTENT_HUB_TELEGRAM_UPDATE_RECEIVED" in stdout
    assert "CONTENT_HUB_TELEGRAM_UPDATE_RESULT" in stdout
    assert "update_type=channel_post" in stdout
    assert "Фото новой спальни с матрасом" not in stdout
    assert "photo-small-file-id" not in stdout
    assert "photo-large-file-id" not in stdout
    assert "photo-medium-file-id" not in stdout
    assert "photo-small-unique-id" not in stdout
    assert "photo-large-unique-id" not in stdout
    assert "photo-medium-unique-id" not in stdout
    assert "caption" not in stdout
    assert "file_id" not in stdout
    assert "file_unique_id" not in stdout


def test_telegram_webhook_stdout_error_diagnostics_are_safe(
    client: TestClient,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "update_id": 1003,
        "channel_post": {
            "message_id": 8,
            "chat": {"id": -1001234567890, "type": "channel"},
            "date": 1_725_194_400,
            "text": "Sensitive post text",
        },
    }

    def broken_ingest_update(
        self: TelegramIngestionService,
        update: dict,
        db: Session,
    ) -> None:
        raise RuntimeError("secret-like exception message")

    monkeypatch.setattr(
        TelegramIngestionService,
        "ingest_update",
        broken_ingest_update,
    )

    with pytest.raises(RuntimeError):
        client.post("/webhooks/telegram", json=payload)

    stdout = capsys.readouterr().out
    assert "CONTENT_HUB_TELEGRAM_UPDATE_RECEIVED" in stdout
    assert "CONTENT_HUB_TELEGRAM_UPDATE_ERROR" in stdout
    assert "update_type=channel_post" in stdout
    assert "error_type=RuntimeError" in stdout
    assert "Sensitive post text" not in stdout
    assert "secret-like exception message" not in stdout


def test_safe_telegram_update_logs_do_not_expose_payload_data(
    client: TestClient,
    caplog,
) -> None:
    payload = load_fixture("telegram_photo_channel_post.json")
    caplog.set_level(
        logging.INFO,
        logger="content_hub.services.telegram_ingestion",
    )

    response = client.post("/webhooks/telegram", json=payload)

    assert response.status_code == 200
    logs = caplog.text
    assert "telegram_update_received" in logs
    assert "telegram_update_result" in logs
    assert "update_type=channel_post" in logs
    assert "keys=['channel_post', 'update_id']" in logs
    assert "Фото новой спальни с матрасом" not in logs
    assert "photo-large-file-id" not in logs
    assert "photo-large-unique-id" not in logs
    assert "caption" not in logs
    assert "file_id" not in logs
    assert "file_unique_id" not in logs


def test_repeated_webhook_does_not_create_duplicate(
    client: TestClient,
    db_session: Session,
) -> None:
    payload = load_fixture("telegram_text_channel_post.json")

    first_response = client.post("/webhooks/telegram", json=payload)
    second_response = client.post("/webhooks/telegram", json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["created"] is True
    assert second_response.json()["created"] is False
    assert second_response.json()["reason"] == "duplicate"
    assert first_response.json()["post_id"] == second_response.json()["post_id"]
    assert len(db_session.scalars(select(Post)).all()) == 1
    assert len(db_session.scalars(select(Media)).all()) == 0
    assert len(db_session.scalars(select(PublicationJob)).all()) == 4


def test_post_is_created_with_expected_fields(
    client: TestClient,
    db_session: Session,
) -> None:
    payload = load_fixture("telegram_text_channel_post.json")

    client.post("/webhooks/telegram", json=payload)

    post = db_session.scalar(select(Post))
    assert post is not None
    assert post.telegram_chat_id == -1001234567890
    assert post.telegram_post_id == 42
    assert post.telegram_message_ids == [42]
    assert post.telegram_url == "https://t.me/content_hub_test/42"
    assert post.text == "Новый пост о матрасах и уютной спальне"
    assert post.author == "Юлия Смирнова"
    assert post.slug == "telegram-c1001234567890-m42"
    assert post.title == "Новый пост о матрасах и уютной спальне"
    assert post.meta_description == "Новый пост о матрасах и уютной спальне"
    assert post.image_alt_text is None
    assert post.post_type == PostType.text
    assert post.photo_count == 0
    assert post.video_count == 0
    assert post.is_public is False
    assert post.source == ContentSource.telegram_channel
    assert post.status == PostStatus.queued
    assert post.website_status == PlatformStatus.Waiting
    assert post.instagram_status == PlatformStatus.Waiting
    assert post.facebook_status == PlatformStatus.Waiting
    assert post.vk_status == PlatformStatus.Waiting
    assert post.story_status is None
    assert_publication_jobs_created(db_session, post)

    log = db_session.scalar(
        select(PublicationLog).where(PublicationLog.event == "post_received")
    )
    assert log is not None
    assert log.post_id == post.id
    assert log.service == "telegram"
    assert log.level == PublicationLogLevel.info
    assert log.event == "post_received"

    queue_log = db_session.scalar(
        select(PublicationLog).where(
            PublicationLog.event == "publication_jobs_created"
        )
    )
    assert queue_log is not None
    assert queue_log.post_id == post.id
    assert queue_log.service == "queue"
    assert queue_log.level == PublicationLogLevel.info
    assert "4" in queue_log.message


def test_service_ingests_text_without_fastapi(db_session: Session) -> None:
    payload = load_fixture("telegram_text_channel_post.json")

    result = TelegramIngestionService().ingest_update(payload, db_session)

    assert result.created is True
    assert result.post_id is not None
    assert str(uuid.UUID(result.post_id)) == result.post_id
    post = db_session.scalar(select(Post))
    assert post is not None
    assert post.post_type == PostType.text
    assert post.status == PostStatus.queued
    assert_publication_jobs_created(db_session, post)


def test_photo_channel_post_creates_post_and_largest_photo_media(
    client: TestClient,
    db_session: Session,
) -> None:
    payload = load_fixture("telegram_photo_channel_post.json")

    response = client.post("/webhooks/telegram", json=payload)

    assert response.status_code == 200
    assert response.json()["created"] is True

    post = db_session.scalar(select(Post))
    assert post is not None
    assert post.text == "Фото новой спальни с матрасом"
    assert post.post_type == PostType.photo
    assert post.slug == "telegram-c1001234567890-m43"
    assert post.title == "Фото новой спальни с матрасом"
    assert post.meta_description == "Фото новой спальни с матрасом"
    assert post.image_alt_text == "Фото новой спальни с матрасом"
    assert post.photo_count == 1
    assert post.video_count == 0
    assert post.status == PostStatus.queued
    assert_publication_jobs_created(db_session, post)

    media = db_session.scalar(select(Media))
    assert media is not None
    assert media.post_id == post.id
    assert media.type == MediaType.photo
    assert media.file_url is None
    assert media.storage_key is None
    assert media.telegram_file_id == "photo-large-file-id"
    assert media.telegram_file_unique_id == "photo-large-unique-id"
    assert media.sort_order == 0
    assert media.width == 1280
    assert media.height == 960
    assert media.size_bytes == 210000


def test_video_channel_post_creates_post_and_video_media(
    client: TestClient,
    db_session: Session,
) -> None:
    payload = load_fixture("telegram_video_channel_post.json")

    response = client.post("/webhooks/telegram", json=payload)

    assert response.status_code == 200
    assert response.json()["created"] is True

    post = db_session.scalar(select(Post))
    assert post is not None
    assert post.text == "Короткое видео про интерьер"
    assert post.post_type == PostType.video
    assert post.slug == "telegram-c1001234567890-m44"
    assert post.title == "Короткое видео про интерьер"
    assert post.meta_description == "Короткое видео про интерьер"
    assert post.image_alt_text == "Короткое видео про интерьер"
    assert post.photo_count == 0
    assert post.video_count == 1
    assert post.status == PostStatus.queued
    assert_publication_jobs_created(db_session, post)

    media = db_session.scalar(select(Media))
    assert media is not None
    assert media.post_id == post.id
    assert media.type == MediaType.video
    assert media.file_url is None
    assert media.storage_key is None
    assert media.telegram_file_id == "video-file-id"
    assert media.telegram_file_unique_id == "video-unique-id"
    assert media.sort_order == 0
    assert media.mime_type == "video/mp4"
    assert media.size_bytes == 4200000
    assert media.width == 1080
    assert media.height == 1920
    assert media.duration_seconds == 27


def test_generated_slugs_are_unique_for_different_telegram_posts(
    client: TestClient,
    db_session: Session,
) -> None:
    client.post("/webhooks/telegram", json=load_fixture("telegram_text_channel_post.json"))
    client.post("/webhooks/telegram", json=load_fixture("telegram_photo_channel_post.json"))

    slugs = [post.slug for post in db_session.scalars(select(Post)).all()]

    assert slugs == [
        "telegram-c1001234567890-m42",
        "telegram-c1001234567890-m43",
    ]
    assert len(slugs) == len(set(slugs))


def test_repeated_photo_webhook_does_not_create_duplicate_media(
    client: TestClient,
    db_session: Session,
) -> None:
    payload = load_fixture("telegram_photo_channel_post.json")

    first_response = client.post("/webhooks/telegram", json=payload)
    second_response = client.post("/webhooks/telegram", json=payload)

    assert first_response.json()["created"] is True
    assert second_response.json()["created"] is False
    assert second_response.json()["reason"] == "duplicate"
    assert len(db_session.scalars(select(Post)).all()) == 1
    assert len(db_session.scalars(select(Media)).all()) == 1
    assert len(db_session.scalars(select(PublicationJob)).all()) == 4


def test_repeated_video_webhook_does_not_create_duplicate_media(
    client: TestClient,
    db_session: Session,
) -> None:
    payload = load_fixture("telegram_video_channel_post.json")

    first_response = client.post("/webhooks/telegram", json=payload)
    second_response = client.post("/webhooks/telegram", json=payload)

    assert first_response.json()["created"] is True
    assert second_response.json()["created"] is False
    assert second_response.json()["reason"] == "duplicate"
    assert len(db_session.scalars(select(Post)).all()) == 1
    assert len(db_session.scalars(select(Media)).all()) == 1
    assert len(db_session.scalars(select(PublicationJob)).all()) == 4


def test_publication_job_platform_is_unique_per_post(
    client: TestClient,
    db_session: Session,
) -> None:
    payload = load_fixture("telegram_text_channel_post.json")
    client.post("/webhooks/telegram", json=payload)
    post = db_session.scalar(select(Post))
    assert post is not None

    db_session.add(
        PublicationJob(
            post_id=post.id,
            platform=PublicationPlatform.website,
            status=PlatformStatus.Waiting,
            attempt_count=0,
            max_attempts=5,
        )
    )

    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:
        raise AssertionError("Expected unique post/platform constraint")
