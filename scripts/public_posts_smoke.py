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
    headers = {}
    if settings.telegram_webhook_secret:
        headers["X-Telegram-Bot-Api-Secret-Token"] = settings.telegram_webhook_secret
    admin_headers = {"X-Content-Hub-Admin-Token": settings.admin_api_token}

    post_ids: dict[PostType, uuid.UUID] = {}
    with TestClient(app) as client:
        for payload in payloads:
            response = client.post(
                "/webhooks/telegram",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            body = response.json()
            assert body["created"] is True, body
            post_id = uuid.UUID(body["post_id"])
            post_type = detect_payload_post_type(payload)
            post_ids[post_type] = post_id

        with SessionLocal() as db:
            for post_id in post_ids.values():
                post = db.get(Post, post_id)
                assert post is not None
                assert post.is_public is False
                assert post.slug == (
                    f"telegram-c{abs(post.telegram_chat_id)}-m{post.telegram_post_id}"
                )
                assert post.title is not None
                assert post.meta_description is not None
                if post.post_type in {PostType.photo, PostType.video}:
                    assert post.image_alt_text == post.title
                else:
                    assert post.image_alt_text is None

        list_response = client.get("/api/posts/public")
        list_response.raise_for_status()
        public_posts = list_response.json()
        public_ids = {uuid.UUID(post["id"]) for post in public_posts}
        assert post_ids[PostType.text] not in public_ids
        assert post_ids[PostType.photo] not in public_ids
        assert post_ids[PostType.video] not in public_ids
        assert_response_is_public(public_posts)

        private_slug_response = client.get(
            f"/api/posts/public/slug/{post_slug(post_ids[PostType.text])}"
        )
        assert private_slug_response.status_code == 404

        publish_response = client.post(
            f"/admin/posts/{post_ids[PostType.photo]}/publish",
            headers=admin_headers,
        )
        publish_response.raise_for_status()
        assert publish_response.json()["is_public"] is True

        public_after_publish_response = client.get("/api/posts/public")
        public_after_publish_response.raise_for_status()
        public_after_publish = public_after_publish_response.json()
        public_after_publish_ids = {
            uuid.UUID(post["id"])
            for post in public_after_publish
        }
        assert post_ids[PostType.photo] in public_after_publish_ids
        assert_response_is_public(public_after_publish)
        photo_summary = next(
            post
            for post in public_after_publish
            if uuid.UUID(post["id"]) == post_ids[PostType.photo]
        )
        assert photo_summary["slug"] == post_slug(post_ids[PostType.photo])
        assert photo_summary["title"] is not None
        assert photo_summary["meta_description"] is not None
        assert photo_summary["image_alt_text"] == photo_summary["title"]

        photo_detail_response = client.get(
            f"/api/posts/public/{post_ids[PostType.photo]}"
        )
        photo_detail_response.raise_for_status()
        photo_detail = photo_detail_response.json()
        assert photo_detail["post_type"] == PostType.photo.value
        assert photo_detail["slug"] == post_slug(post_ids[PostType.photo])
        assert photo_detail["title"] == photo_summary["title"]
        assert photo_detail["meta_description"] == photo_summary["meta_description"]
        assert photo_detail["image_alt_text"] == photo_summary["image_alt_text"]
        assert photo_detail["media"][0]["file_url"] is None
        assert_response_is_public(photo_detail)

        photo_slug_detail_response = client.get(
            f"/api/posts/public/slug/{post_slug(post_ids[PostType.photo])}"
        )
        photo_slug_detail_response.raise_for_status()
        assert photo_slug_detail_response.json()["id"] == str(post_ids[PostType.photo])

        occupied_slug_response = client.patch(
            f"/admin/posts/{post_ids[PostType.video]}/seo",
            headers=admin_headers,
            json={"slug": post_slug(post_ids[PostType.text])},
        )
        assert occupied_slug_response.status_code == 409

        unpublish_response = client.post(
            f"/admin/posts/{post_ids[PostType.photo]}/unpublish",
            headers=admin_headers,
        )
        unpublish_response.raise_for_status()
        assert unpublish_response.json()["is_public"] is False

        public_after_unpublish_response = client.get("/api/posts/public")
        public_after_unpublish_response.raise_for_status()
        public_after_unpublish_ids = {
            uuid.UUID(post["id"])
            for post in public_after_unpublish_response.json()
        }
        assert post_ids[PostType.photo] not in public_after_unpublish_ids

        publish_error_response = client.post(
            f"/admin/posts/{post_ids[PostType.video]}/publish",
            headers=admin_headers,
        )
        publish_error_response.raise_for_status()
        with SessionLocal() as db:
            error_post = db.get(Post, post_ids[PostType.video])
            assert error_post is not None
            error_post.status = PostStatus.error
            assert error_post.is_public is True
            db.commit()

        public_after_error_response = client.get("/api/posts/public")
        public_after_error_response.raise_for_status()
        public_after_error_ids = {
            uuid.UUID(post["id"])
            for post in public_after_error_response.json()
        }
        assert post_ids[PostType.video] not in public_after_error_ids

        error_detail_response = client.get(
            f"/api/posts/public/{post_ids[PostType.video]}"
        )
        assert error_detail_response.status_code == 404
        error_slug_detail_response = client.get(
            f"/api/posts/public/slug/{post_slug(post_ids[PostType.video])}"
        )
        assert error_slug_detail_response.status_code == 404

    print("Public posts PostgreSQL smoke passed.")
    print(f"text private post: {post_ids[PostType.text]}")
    print(f"photo unpublished post: {post_ids[PostType.photo]}")
    print(f"video public error post: {post_ids[PostType.video]}")
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
        message["text"] = f"Public posts smoke text {now.isoformat()}"
    if "caption" in message:
        message["caption"] = f"Public posts smoke {fixture_name} {now.isoformat()}"
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


def assert_response_is_public(body: Any) -> None:
    response_json = json.dumps(body, ensure_ascii=False)
    for marker in PRIVATE_RESPONSE_MARKERS:
        assert marker not in response_json, marker


if __name__ == "__main__":
    raise SystemExit(main())
