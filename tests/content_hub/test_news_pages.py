import json
import uuid
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from content_hub.enums import PostStatus
from content_hub.models import Post
from content_hub.services.telegram_ingestion import TelegramIngestionService


FIXTURES_DIR = Path(__file__).parent / "fixtures"


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


def test_news_list_is_available_without_admin_token(client: TestClient) -> None:
    response = client.get("/news")

    assert response.status_code == 200
    assert "No public posts yet." in response.text


def test_news_list_shows_only_public_posts(
    client: TestClient,
    db_session: Session,
) -> None:
    public_post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    private_post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")
    make_public(public_post, db_session)

    response = client.get("/news")

    assert response.status_code == 200
    assert public_post.title in response.text
    assert private_post.title not in response.text


def test_news_list_hides_error_posts(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    make_public(post, db_session)
    post.status = PostStatus.error
    db_session.flush()

    response = client.get("/news")

    assert response.status_code == 200
    assert post.title not in response.text


def test_news_list_hides_posts_without_slug(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    make_public(post, db_session)
    post.slug = None
    db_session.flush()

    response = client.get("/news")

    assert response.status_code == 200
    assert post.title not in response.text


def test_news_detail_returns_public_post_page(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    make_public(post, db_session)

    response = client.get(f"/news/{post.slug}")

    assert response.status_code == 200
    assert post.title in response.text
    assert post.meta_description in response.text
    assert post.text in response.text
    assert post.telegram_url in response.text


def test_news_detail_for_private_post_returns_404(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    response = client.get(f"/news/{post.slug}")

    assert response.status_code == 404


def test_news_detail_for_error_post_returns_404(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    make_public(post, db_session)
    post.status = PostStatus.error
    db_session.flush()

    response = client.get(f"/news/{post.slug}")

    assert response.status_code == 404


def test_news_detail_contains_title_and_meta_description(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")
    make_public(post, db_session)

    response = client.get(f"/news/{post.slug}")

    assert response.status_code == 200
    assert f"<title>{post.title}</title>" in response.text
    assert (
        f'<meta name="description" content="{post.meta_description}">'
        in response.text
    )


def test_news_pages_do_not_expose_private_media_fields(
    client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")
    make_public(post, db_session)

    list_response = client.get("/news")
    detail_response = client.get(f"/news/{post.slug}")

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    combined_html = list_response.text + detail_response.text
    assert "telegram_file_id" not in combined_html
    assert "telegram_file_unique_id" not in combined_html
    assert "storage_key" not in combined_html
    assert "photo-large-file-id" not in combined_html
    assert "photo-large-unique-id" not in combined_html
