import json
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from content_hub.app import create_app
from content_hub.db import get_db
from content_hub.enums import PostStatus, PostType
from content_hub.models import Post
from content_hub.services.telegram_ingestion import TelegramIngestionService
from content_hub.settings import Settings, get_settings


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def public_client_with_admin_token(
    db_session: Session,
) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    def override_get_settings() -> Settings:
        return Settings(
            database_url="sqlite://",
            telegram_webhook_secret=None,
            admin_api_token="configured-admin-token",
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def load_fixture(name: str) -> dict[str, Any]:
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


def make_public(post: Post, db_session: Session) -> Post:
    post.is_public = True
    db_session.flush()
    return post


def test_public_posts_are_available_without_admin_token(
    public_client_with_admin_token: TestClient,
    db_session: Session,
) -> None:
    create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = public_client_with_admin_token.get("/api/posts/public")

    assert response.status_code == 200
    assert response.json() == []


def test_public_posts_do_not_show_non_public_posts(
    client: TestClient,
    db_session: Session,
) -> None:
    create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = client.get("/api/posts/public")

    assert response.status_code == 200
    assert response.json() == []


def test_public_posts_return_only_non_error_posts(
    client: TestClient,
    db_session: Session,
) -> None:
    visible_post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    error_post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")
    make_public(visible_post, db_session)
    make_public(error_post, db_session)
    error_post.status = PostStatus.error
    db_session.flush()

    response = client.get("/api/posts/public")

    assert response.status_code == 200
    body = response.json()
    assert [post["id"] for post in body] == [str(visible_post.id)]


def test_public_posts_list_returns_seo_fields(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    make_public(post, db_session)

    response = client.get("/api/posts/public")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["slug"] == "telegram-c1001234567890-m42"
    assert body[0]["title"] == "Новый пост о матрасах и уютной спальне"
    assert body[0]["meta_description"] == "Новый пост о матрасах и уютной спальне"
    assert body[0]["image_alt_text"] is None


def test_public_posts_do_not_return_telegram_file_id(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")
    make_public(post, db_session)

    body = client.get("/api/posts/public").json()

    assert_key_absent(body, "telegram_file_id")
    assert "photo-large-file-id" not in json.dumps(body)


def test_public_posts_do_not_return_telegram_file_unique_id(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")
    make_public(post, db_session)

    body = client.get("/api/posts/public").json()

    assert_key_absent(body, "telegram_file_unique_id")
    assert "photo-large-unique-id" not in json.dumps(body)


def test_public_posts_do_not_return_storage_key(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")
    make_public(post, db_session)

    body = client.get("/api/posts/public").json()

    assert_key_absent(body, "storage_key")


def test_get_public_post_detail_returns_detail(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_video_channel_post.json")
    make_public(post, db_session)

    response = client.get(f"/api/posts/public/{post.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(post.id)
    assert body["is_public"] is True
    assert body["slug"] == "telegram-c1001234567890-m44"
    assert body["title"] == "Короткое видео про интерьер"
    assert body["meta_description"] == "Короткое видео про интерьер"
    assert body["image_alt_text"] == "Короткое видео про интерьер"
    assert body["text"] == "Короткое видео про интерьер"
    assert body["post_type"] == PostType.video.value
    assert body["video_count"] == 1
    assert body["media"] == [
        {
            "type": "video",
            "sort_order": 0,
            "mime_type": "video/mp4",
            "size_bytes": 4200000,
            "width": 1080,
            "height": 1920,
            "duration_seconds": 27,
            "file_url": None,
        }
    ]
    assert_key_absent(body, "telegram_file_id")
    assert_key_absent(body, "telegram_file_unique_id")
    assert_key_absent(body, "storage_key")


def test_get_public_post_detail_by_slug_returns_detail(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")
    make_public(post, db_session)

    response = client.get(f"/api/posts/public/slug/{post.slug}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(post.id)
    assert body["slug"] == "telegram-c1001234567890-m43"
    assert body["title"] == "Фото новой спальни с матрасом"
    assert body["image_alt_text"] == "Фото новой спальни с матрасом"


def test_get_public_post_detail_by_slug_for_private_post_returns_404(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = client.get(f"/api/posts/public/slug/{post.slug}")

    assert response.status_code == 404


def test_get_public_post_detail_for_error_post_returns_404(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    make_public(post, db_session)
    post.status = PostStatus.error
    db_session.flush()

    response = client.get(f"/api/posts/public/{post.id}")

    assert response.status_code == 404


def test_get_public_post_detail_by_slug_for_error_post_returns_404(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    make_public(post, db_session)
    post.status = PostStatus.error
    db_session.flush()

    response = client.get(f"/api/posts/public/slug/{post.slug}")

    assert response.status_code == 404


def test_public_posts_filter_by_post_type(
    client: TestClient,
    db_session: Session,
) -> None:
    text_post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    photo_post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")
    make_public(text_post, db_session)
    make_public(photo_post, db_session)

    response = client.get(
        "/api/posts/public",
        params={"post_type": PostType.photo.value},
    )

    assert response.status_code == 200
    body = response.json()
    assert [post["id"] for post in body] == [str(photo_post.id)]
    assert body[0]["is_public"] is True
    assert body[0]["media_count"] == 1
    assert body[0]["has_photo"] is True
    assert body[0]["has_video"] is False


def test_public_posts_limit_works_and_is_capped_at_100(
    client: TestClient,
    db_session: Session,
) -> None:
    text_post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    photo_post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")
    video_post = create_post_from_fixture(db_session, "telegram_video_channel_post.json")
    make_public(text_post, db_session)
    make_public(photo_post, db_session)
    make_public(video_post, db_session)

    limited_response = client.get("/api/posts/public", params={"limit": 2})
    too_large_response = client.get("/api/posts/public", params={"limit": 101})

    assert limited_response.status_code == 200
    assert len(limited_response.json()) == 2
    assert too_large_response.status_code == 422


def test_public_posts_are_sorted_by_telegram_posted_at_desc(
    client: TestClient,
    db_session: Session,
) -> None:
    text_post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    photo_post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")
    video_post = create_post_from_fixture(db_session, "telegram_video_channel_post.json")
    make_public(text_post, db_session)
    make_public(photo_post, db_session)
    make_public(video_post, db_session)

    response = client.get("/api/posts/public")

    assert response.status_code == 200
    assert [post["id"] for post in response.json()] == [
        str(video_post.id),
        str(photo_post.id),
        str(text_post.id),
    ]


def assert_key_absent(value: Any, forbidden_key: str) -> None:
    if isinstance(value, dict):
        assert forbidden_key not in value
        for item in value.values():
            assert_key_absent(item, forbidden_key)
    elif isinstance(value, list):
        for item in value:
            assert_key_absent(item, forbidden_key)
