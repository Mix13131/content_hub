import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from content_hub.models import Post, PublicationLog


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


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

    posts = db_session.scalars(select(Post)).all()
    assert len(posts) == 1


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
    assert post.post_type == "text"
    assert post.photo_count == 0
    assert post.video_count == 0
    assert post.source == "telegram_channel"
    assert post.status == "saved"
    assert post.website_status == "Waiting"
    assert post.instagram_status == "Waiting"
    assert post.facebook_status == "Waiting"
    assert post.vk_status == "Waiting"
    assert post.story_status is None

    log = db_session.scalar(select(PublicationLog))
    assert log is not None
    assert log.post_id == post.id
    assert log.service == "telegram"
    assert log.event == "post_received"
