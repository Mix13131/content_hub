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
from content_hub.models import Media, Post, PublicationJob, PublicationLog
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
    assert body[0]["is_public"] is False
    assert body[0]["slug"] == "telegram-c1001234567890-m42"
    assert body[0]["title"] == "Новый пост о матрасах и уютной спальне"
    assert body[0]["meta_description"] == "Новый пост о матрасах и уютной спальне"
    assert body[0]["image_alt_text"] is None
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
    assert body["is_public"] is False
    assert body["slug"] == "telegram-c1001234567890-m43"
    assert body["title"] == "Фото новой спальни с матрасом"
    assert body["meta_description"] == "Фото новой спальни с матрасом"
    assert body["image_alt_text"] == "Фото новой спальни с матрасом"
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


def test_admin_posts_filter_by_public_visibility(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    public_post = create_post_from_fixture(
        db_session,
        "telegram_text_channel_post.json",
    )
    private_post = create_post_from_fixture(
        db_session,
        "telegram_photo_channel_post.json",
    )
    public_post.is_public = True
    db_session.flush()

    public_response = admin_client.get(
        "/admin/posts",
        params={"is_public": "true"},
        headers=admin_headers(),
    )
    private_response = admin_client.get(
        "/admin/posts",
        params={"is_public": "false"},
        headers=admin_headers(),
    )

    assert public_response.status_code == 200
    assert private_response.status_code == 200
    assert [post["id"] for post in public_response.json()] == [str(public_post.id)]
    assert [post["id"] for post in private_response.json()] == [str(private_post.id)]


def test_publish_post_sets_public_flag_and_creates_log(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = admin_client.post(
        f"/admin/posts/{post.id}/publish",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_public"] is True
    assert post.is_public is True
    log = db_session.scalar(
        select(PublicationLog).where(
            PublicationLog.post_id == post.id,
            PublicationLog.event == "post_published_publicly",
        )
    )
    assert log is not None
    assert log.service == "admin"
    assert log.level == "info"


def test_published_post_appears_in_public_api(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    publish_response = admin_client.post(
        f"/admin/posts/{post.id}/publish",
        headers=admin_headers(),
    )
    public_response = admin_client.get("/api/posts/public")

    assert publish_response.status_code == 200
    assert public_response.status_code == 200
    assert [item["id"] for item in public_response.json()] == [str(post.id)]


def test_unpublish_post_clears_public_flag_and_creates_log(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    post.is_public = True
    db_session.flush()

    response = admin_client.post(
        f"/admin/posts/{post.id}/unpublish",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_public"] is False
    assert post.is_public is False
    log = db_session.scalar(
        select(PublicationLog).where(
            PublicationLog.post_id == post.id,
            PublicationLog.event == "post_unpublished_publicly",
        )
    )
    assert log is not None
    assert log.service == "admin"
    assert log.level == "info"


def test_unpublished_post_disappears_from_public_api(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    post.is_public = True
    db_session.flush()

    before_response = admin_client.get("/api/posts/public")
    unpublish_response = admin_client.post(
        f"/admin/posts/{post.id}/unpublish",
        headers=admin_headers(),
    )
    after_response = admin_client.get("/api/posts/public")

    assert before_response.status_code == 200
    assert [item["id"] for item in before_response.json()] == [str(post.id)]
    assert unpublish_response.status_code == 200
    assert after_response.status_code == 200
    assert after_response.json() == []


def test_publish_and_unpublish_require_token(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    publish_response = admin_client.post(f"/admin/posts/{post.id}/publish")
    unpublish_response = admin_client.post(f"/admin/posts/{post.id}/unpublish")

    assert publish_response.status_code == 403
    assert unpublish_response.status_code == 403


def test_publish_and_unpublish_unknown_post_return_404(
    admin_client: TestClient,
) -> None:
    post_id = uuid.uuid4()

    publish_response = admin_client.post(
        f"/admin/posts/{post_id}/publish",
        headers=admin_headers(),
    )
    unpublish_response = admin_client.post(
        f"/admin/posts/{post_id}/unpublish",
        headers=admin_headers(),
    )

    assert publish_response.status_code == 404
    assert unpublish_response.status_code == 404


def test_update_post_seo_normalizes_slug_updates_fields_and_creates_log(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = admin_client.patch(
        f"/admin/posts/{post.id}/seo",
        headers=admin_headers(),
        json={
            "slug": "  Custom Slug!  ",
            "title": "Custom title",
            "meta_description": "Custom meta description",
            "image_alt_text": "Custom alt",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "custom-slug"
    assert body["title"] == "Custom title"
    assert body["meta_description"] == "Custom meta description"
    assert body["image_alt_text"] == "Custom alt"
    assert post.slug == "custom-slug"
    log = db_session.scalar(
        select(PublicationLog).where(
            PublicationLog.post_id == post.id,
            PublicationLog.event == "post_seo_updated",
        )
    )
    assert log is not None
    assert log.service == "admin"
    assert log.level == "info"


def test_update_post_seo_allows_partial_update(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = admin_client.patch(
        f"/admin/posts/{post.id}/seo",
        headers=admin_headers(),
        json={"title": "Only title changed"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "telegram-c1001234567890-m42"
    assert body["title"] == "Only title changed"


def test_update_post_seo_rejects_occupied_slug(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    first_post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    second_post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")

    response = admin_client.patch(
        f"/admin/posts/{second_post.id}/seo",
        headers=admin_headers(),
        json={"slug": first_post.slug},
    )

    assert response.status_code == 409


def test_update_post_seo_rejects_empty_normalized_slug(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = admin_client.patch(
        f"/admin/posts/{post.id}/seo",
        headers=admin_headers(),
        json={"slug": " !!! "},
    )

    assert response.status_code == 422


def test_update_post_seo_requires_token(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = admin_client.patch(
        f"/admin/posts/{post.id}/seo",
        json={"title": "Hidden"},
    )

    assert response.status_code == 403


def test_update_post_seo_unknown_post_returns_404(
    admin_client: TestClient,
) -> None:
    response = admin_client.patch(
        f"/admin/posts/{uuid.uuid4()}/seo",
        headers=admin_headers(),
        json={"title": "Missing"},
    )

    assert response.status_code == 404


def test_retry_post_platform_requires_token(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = admin_client.post(f"/admin/posts/{post.id}/retry/instagram")

    assert response.status_code == 403


def test_retry_post_platform_returns_job_to_waiting_without_resetting_attempts(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    job = db_session.scalar(
        select(PublicationJob).where(
            PublicationJob.post_id == post.id,
            PublicationJob.platform == PublicationPlatform.instagram,
        )
    )
    assert job is not None
    service = PublicationStatusService()
    service.start_job(job.id, db_session)
    service.mark_error(
        job.id,
        db_session,
        error_code="IG_ERROR",
        error_message="Instagram failed",
    )

    response = admin_client.post(
        f"/admin/posts/{post.id}/retry/instagram",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["retried_count"] == 1
    assert body["retried_platforms"] == [PublicationPlatform.instagram.value]
    retried_job = next(
        job
        for job in body["post"]["jobs"]
        if job["platform"] == PublicationPlatform.instagram.value
    )
    assert retried_job["status"] == PlatformStatus.Waiting.value
    assert retried_job["attempt_count"] == 1
    assert retried_job["last_error_code"] is None
    assert retried_job["last_error_message"] is None


def test_retry_post_platform_recalculates_post_status(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    jobs = db_session.scalars(
        select(PublicationJob).where(PublicationJob.post_id == post.id)
    ).all()
    service = PublicationStatusService()
    for job in jobs:
        service.mark_error(job.id, db_session)
    assert post.status == PostStatus.error

    response = admin_client.post(
        f"/admin/posts/{post.id}/retry/website",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["post"]["status"] == PostStatus.queued.value
    assert body["post"]["website_status"] == PlatformStatus.Waiting.value


def test_retry_post_platform_for_success_job_returns_409(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    job = db_session.scalar(
        select(PublicationJob).where(
            PublicationJob.post_id == post.id,
            PublicationJob.platform == PublicationPlatform.website,
        )
    )
    assert job is not None
    PublicationStatusService().mark_success(job.id, db_session)

    response = admin_client.post(
        f"/admin/posts/{post.id}/retry/website",
        headers=admin_headers(),
    )

    assert response.status_code == 409


def test_retry_post_platform_unknown_post_returns_404(
    admin_client: TestClient,
) -> None:
    response = admin_client.post(
        f"/admin/posts/{uuid.uuid4()}/retry/instagram",
        headers=admin_headers(),
    )

    assert response.status_code == 404


def test_retry_post_platform_unknown_job_returns_404(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = admin_client.post(
        f"/admin/posts/{post.id}/retry/telegram_story",
        headers=admin_headers(),
    )

    assert response.status_code == 404


def test_retry_post_platform_invalid_platform_returns_422(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = admin_client.post(
        f"/admin/posts/{post.id}/retry/not-a-platform",
        headers=admin_headers(),
    )

    assert response.status_code == 422


def test_retry_failed_post_jobs_returns_only_error_and_retry_jobs_to_waiting(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    jobs = {
        job.platform: job
        for job in db_session.scalars(
            select(PublicationJob).where(PublicationJob.post_id == post.id)
        ).all()
    }
    service = PublicationStatusService()
    service.start_job(jobs[PublicationPlatform.website].id, db_session)
    service.mark_error(
        jobs[PublicationPlatform.website].id,
        db_session,
        error_code="WEBSITE_ERROR",
        error_message="Website failed",
    )
    service.start_job(jobs[PublicationPlatform.instagram].id, db_session)
    service.schedule_retry(
        jobs[PublicationPlatform.instagram].id,
        db_session,
        error_code="IG_TIMEOUT",
        error_message="Instagram timeout",
    )
    service.mark_success(jobs[PublicationPlatform.vk].id, db_session)
    service.start_job(jobs[PublicationPlatform.facebook].id, db_session)

    response = admin_client.post(
        f"/admin/posts/{post.id}/retry-failed",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["retried_count"] == 2
    assert set(body["retried_platforms"]) == {
        PublicationPlatform.website.value,
        PublicationPlatform.instagram.value,
    }
    jobs_by_platform = {
        job["platform"]: job
        for job in body["post"]["jobs"]
    }
    assert jobs_by_platform[PublicationPlatform.website.value]["status"] == (
        PlatformStatus.Waiting.value
    )
    assert jobs_by_platform[PublicationPlatform.instagram.value]["status"] == (
        PlatformStatus.Waiting.value
    )
    assert jobs_by_platform[PublicationPlatform.vk.value]["status"] == (
        PlatformStatus.Success.value
    )
    assert jobs_by_platform[PublicationPlatform.facebook.value]["status"] == (
        PlatformStatus.Publishing.value
    )
    assert body["post"]["status"] == PostStatus.partially_published.value


def test_retry_failed_post_jobs_returns_zero_when_nothing_matches(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = admin_client.post(
        f"/admin/posts/{post.id}/retry-failed",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["retried_count"] == 0
    assert body["retried_platforms"] == []
    assert body["post"]["status"] == PostStatus.queued.value


def test_run_post_platform_requires_token(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = admin_client.post(f"/admin/posts/{post.id}/run/website")

    assert response.status_code == 403


def test_run_post_platform_executes_website_connector_and_returns_detail(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = admin_client.post(
        f"/admin/posts/{post.id}/run/website",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(post.id)
    assert body["website_status"] == PlatformStatus.Success.value
    website_job = next(
        job
        for job in body["jobs"]
        if job["platform"] == PublicationPlatform.website.value
    )
    assert website_job["status"] == PlatformStatus.Success.value
    assert website_job["external_post_id"] == str(post.id)
    assert website_job["external_url"] == f"/news/{post.slug}"


def test_run_post_platform_unknown_post_returns_404(
    admin_client: TestClient,
) -> None:
    response = admin_client.post(
        f"/admin/posts/{uuid.uuid4()}/run/website",
        headers=admin_headers(),
    )

    assert response.status_code == 404


def test_run_post_platform_unknown_job_returns_404(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = admin_client.post(
        f"/admin/posts/{post.id}/run/telegram_story",
        headers=admin_headers(),
    )

    assert response.status_code == 404
