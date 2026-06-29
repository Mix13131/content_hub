from __future__ import annotations

import copy
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from content_hub.app import app
from content_hub.db import SessionLocal
from content_hub.enums import PostStatus, PostType
from content_hub.models import Post
from content_hub.settings import get_settings


FIXTURES_DIR = PROJECT_ROOT / "tests" / "content_hub" / "fixtures"
PRIVATE_RESPONSE_MARKERS: tuple[str, ...] = (
    "telegram_file_id",
    "telegram_file_unique_id",
    "storage_key",
    "photo-large-file-id",
    "photo-large-unique-id",
    "video-file-id",
    "video-unique-id",
)


def main() -> int:
    settings = get_settings()
    url = make_url(settings.database_url)
    if not url.drivername.startswith("postgresql"):
        print(
            "Refusing to run: CONTENT_HUB_DATABASE_URL must point to PostgreSQL/Neon.",
            file=sys.stderr,
        )
        print(f"Current driver: {url.drivername}", file=sys.stderr)
        return 2
    if not settings.admin_api_token:
        print(
            "Refusing to run: CONTENT_HUB_ADMIN_API_TOKEN must be set.",
            file=sys.stderr,
        )
        return 2

    payloads = [
        build_payload("telegram_text_channel_post.json", offset=1),
        build_payload("telegram_photo_channel_post.json", offset=2),
        build_payload("telegram_video_channel_post.json", offset=3),
    ]
    webhook_headers = {}
    if settings.telegram_webhook_secret:
        webhook_headers["X-Telegram-Bot-Api-Secret-Token"] = (
            settings.telegram_webhook_secret
        )
    admin_headers = {"X-Content-Hub-Admin-Token": settings.admin_api_token}

    post_ids: dict[PostType, uuid.UUID] = {}
    with TestClient(app) as client:
        for payload in payloads:
            response = client.post(
                "/webhooks/telegram",
                json=payload,
                headers=webhook_headers,
            )
            response.raise_for_status()
            body = response.json()
            assert body["created"] is True, body
            post_ids[detect_payload_post_type(payload)] = uuid.UUID(body["post_id"])

        publish_response = client.post(
            f"/admin/posts/{post_ids[PostType.photo]}/publish",
            headers=admin_headers,
        )
        publish_response.raise_for_status()

        video_publish_response = client.post(
            f"/admin/posts/{post_ids[PostType.video]}/publish",
            headers=admin_headers,
        )
        video_publish_response.raise_for_status()
        with SessionLocal() as db:
            error_post = db.get(Post, post_ids[PostType.video])
            assert error_post is not None
            error_post.status = PostStatus.error
            db.commit()

        news_response = client.get("/news")
        news_response.raise_for_status()
        news_html = news_response.text
        photo_slug = post_slug(post_ids[PostType.photo])
        text_slug = post_slug(post_ids[PostType.text])
        video_slug = post_slug(post_ids[PostType.video])
        assert f"/news/{photo_slug}" in news_html
        assert f"/news/{text_slug}" not in news_html
        assert f"/news/{video_slug}" not in news_html
        assert_response_is_public(news_html)

        detail_response = client.get(f"/news/{photo_slug}")
        detail_response.raise_for_status()
        detail_html = detail_response.text
        assert "<title>" in detail_html
        assert '<meta name="description"' in detail_html
        assert post_title(post_ids[PostType.photo]) in detail_html
        assert_response_is_public(detail_html)

        private_detail_response = client.get(f"/news/{text_slug}")
        assert private_detail_response.status_code == 404
        error_detail_response = client.get(f"/news/{video_slug}")
        assert error_detail_response.status_code == 404

    print("News PostgreSQL smoke passed.")
    print(f"private text post: {post_ids[PostType.text]}")
    print(f"public photo post: {post_ids[PostType.photo]}")
    print(f"public error video post: {post_ids[PostType.video]}")
    return 0


def build_payload(fixture_name: str, offset: int) -> dict[str, Any]:
    payload = json.loads((FIXTURES_DIR / fixture_name).read_text(encoding="utf-8"))
    payload = copy.deepcopy(payload)
    now = datetime.now(timezone.utc)
    unique_id = int(time.time_ns() // 1000) + offset

    payload["update_id"] = unique_id
    message = payload["channel_post"]
    message["message_id"] = unique_id
    message["date"] = int(now.timestamp()) + offset
    if "text" in message:
        message["text"] = f"News smoke text {now.isoformat()}"
    if "caption" in message:
        message["caption"] = f"News smoke {fixture_name} {now.isoformat()}"
    return payload


def detect_payload_post_type(payload: dict[str, Any]) -> PostType:
    message = payload["channel_post"]
    if "photo" in message:
        return PostType.photo
    if "video" in message:
        return PostType.video
    return PostType.text


def post_slug(post_id: uuid.UUID) -> str:
    with SessionLocal() as db:
        post = db.get(Post, post_id)
        assert post is not None
        assert post.slug is not None
        return post.slug


def post_title(post_id: uuid.UUID) -> str:
    with SessionLocal() as db:
        post = db.get(Post, post_id)
        assert post is not None
        assert post.title is not None
        return post.title


def assert_response_is_public(html: str) -> None:
    for marker in PRIVATE_RESPONSE_MARKERS:
        assert marker not in html, marker


if __name__ == "__main__":
    raise SystemExit(main())
