import json
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from content_hub.app import create_app
from content_hub.connectors.registry import default_connector_registry
from content_hub.connectors.tilda import TildaConnector
from content_hub.db import get_db
from content_hub.models import Media, Post
from content_hub.renderers.html_renderer import HtmlRenderer
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


def admin_headers() -> dict[str, str]:
    return {"X-Content-Hub-Admin-Token": ADMIN_TOKEN}


def create_post_from_fixture(db_session: Session, fixture_name: str) -> Post:
    result = TelegramIngestionService().ingest_update(
        load_fixture(fixture_name),
        db_session,
    )
    assert result.post_id is not None
    post = db_session.get(Post, uuid.UUID(result.post_id))
    assert post is not None
    return post


def create_album_post(db_session: Session) -> Post:
    result = TelegramIngestionService().ingest_update(
        load_fixture("telegram_media_group_photo_1_message.json"),
        db_session,
    )
    assert result.post_id is not None
    append_result = TelegramIngestionService().ingest_update(
        load_fixture("telegram_media_group_photo_2_message.json"),
        db_session,
    )
    assert append_result.post_id == result.post_id
    post = db_session.get(Post, uuid.UUID(result.post_id))
    assert post is not None
    return post


def media_for_post(db_session: Session, post: Post) -> list[Media]:
    return db_session.scalars(
        select(Media).where(Media.post_id == post.id).order_by(Media.sort_order)
    ).all()


def test_html_renderer_renders_text_post_seo(db_session: Session) -> None:
    post = create_post_from_fixture(db_session, "telegram_text_channel_post.json")

    page = HtmlRenderer().render(post, media_for_post(db_session, post))

    assert page.title == post.title
    assert page.slug == post.slug
    assert page.meta_description == post.meta_description
    assert f"<title>{post.title}</title>" in page.html
    assert f'<meta name="description" content="{post.meta_description}">' in page.html
    assert f"<h1>{post.title}</h1>" in page.html
    assert f"<p>{post.text}</p>" in page.html


def test_html_renderer_renders_photo_without_private_file_ids(
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")

    page = HtmlRenderer().render(post, media_for_post(db_session, post))

    assert "<img " in page.html
    assert f'alt="{post.image_alt_text}"' in page.html
    assert f"<p>{post.text}</p>" in page.html
    assert "photo-large-file-id" not in page.html
    assert "photo-large-unique-id" not in page.html
    assert "storage_key" not in page.html


def test_html_renderer_preserves_album_photo_order(db_session: Session) -> None:
    post = create_album_post(db_session)

    page = HtmlRenderer().render(post, media_for_post(db_session, post))

    assert post.text == "Альбом спальни с новым матрасом"
    assert page.html.count("<img ") == 2
    assert page.html.index('data-sort-order="0"') < page.html.index(
        'data-sort-order="1"'
    )
    assert post.title in page.html
    assert post.meta_description in page.html


def test_tilda_connector_returns_preview_url_and_html_length(
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")
    media = media_for_post(db_session, post)
    page = HtmlRenderer().render(post, media)

    result = TildaConnector().publish(post, media)

    assert result.success is True
    assert result.external_url == f"tilda-preview://{post.slug}"
    assert result.raw_response == {
        "mode": "preview",
        "html_length": len(page.html),
    }


def test_default_registry_contains_tilda_connector() -> None:
    connector = default_connector_registry().get("tilda")

    assert isinstance(connector, TildaConnector)


def test_tilda_preview_endpoint_requires_admin_token(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")

    response = admin_client.get(f"/preview/tilda/{post.id}")

    assert response.status_code == 403


def test_tilda_preview_endpoint_returns_generated_html(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post = create_post_from_fixture(db_session, "telegram_photo_channel_post.json")

    response = admin_client.get(
        f"/preview/tilda/{post.id}",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    assert post.title in response.text
    assert post.text in response.text
    assert "<img " in response.text
    assert "photo-large-file-id" not in response.text


def test_tilda_preview_unknown_post_returns_404(admin_client: TestClient) -> None:
    response = admin_client.get(
        f"/preview/tilda/{uuid.uuid4()}",
        headers=admin_headers(),
    )

    assert response.status_code == 404
