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
from sqlalchemy import select
from sqlalchemy.engine import make_url

from content_hub.app import app
from content_hub.db import SessionLocal
from content_hub.enums import MediaType, PostType, PublicationPlatform
from content_hub.models import Media, Post, PublicationJob, PublicationLog
from content_hub.settings import get_settings


FIXTURES_DIR = PROJECT_ROOT / "tests" / "content_hub" / "fixtures"


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

    payload = build_payload()
    webhook_headers = {}
    if settings.telegram_webhook_secret:
        webhook_headers["X-Telegram-Bot-Api-Secret-Token"] = (
            settings.telegram_webhook_secret
        )
    admin_headers = {"X-Content-Hub-Admin-Token": settings.admin_api_token}

    with TestClient(app) as client:
        webhook_response = client.post(
            "/webhooks/telegram",
            json=payload,
            headers=webhook_headers,
        )
        webhook_response.raise_for_status()
        webhook_body = webhook_response.json()
        assert webhook_body["created"] is True, webhook_body
        post_id = uuid.UUID(webhook_body["post_id"])

        forbidden_response = client.get(
            "/admin/posts",
            headers={"X-Content-Hub-Admin-Token": "wrong-token"},
        )
        assert forbidden_response.status_code == 403

        list_response = client.get(
            "/admin/posts",
            params={
                "post_type": PostType.photo.value,
                "platform": PublicationPlatform.website.value,
            },
            headers=admin_headers,
        )
        list_response.raise_for_status()
        posts = [
            post
            for post in list_response.json()
            if post["id"] == str(post_id)
        ]
        assert len(posts) == 1, list_response.json()
        assert posts[0]["photo_count"] == 1
        assert posts[0]["video_count"] == 0
        assert "PostgreSQL admin posts smoke" in posts[0]["text_preview"]

        detail_response = client.get(
            f"/admin/posts/{post_id}",
            headers=admin_headers,
        )
        detail_response.raise_for_status()
        detail_body = detail_response.json()
        assert detail_body["id"] == str(post_id)
        assert detail_body["post_type"] == PostType.photo.value
        assert len(detail_body["media"]) == 1
        assert detail_body["media"][0]["type"] == MediaType.photo.value
        assert detail_body["media"][0]["file_url"] is None
        assert detail_body["media"][0]["storage_key"] is None
        assert len(detail_body["jobs"]) == 4
        assert len(detail_body["logs"]) >= 2

    with SessionLocal() as db:
        post = db.get(Post, post_id)
        assert post is not None
        media = db.scalar(select(Media).where(Media.post_id == post_id))
        assert media is not None
        assert media.type == MediaType.photo
        assert media.file_url is None
        assert media.storage_key is None
        jobs = db.scalars(
            select(PublicationJob).where(PublicationJob.post_id == post_id)
        ).all()
        logs = db.scalars(
            select(PublicationLog).where(PublicationLog.post_id == post_id)
        ).all()
        assert len(jobs) == 4
        assert len(logs) >= 2

    print("Admin posts PostgreSQL smoke passed.")
    print(f"post: {post_id}")
    return 0


def build_payload() -> dict[str, Any]:
    payload = json.loads(
        (FIXTURES_DIR / "telegram_photo_channel_post.json").read_text(encoding="utf-8")
    )
    payload = copy.deepcopy(payload)
    now = datetime.now(timezone.utc)
    unique_id = int(time.time_ns() // 1000)
    payload["update_id"] = unique_id
    message = payload["channel_post"]
    message["message_id"] = unique_id
    message["date"] = int(now.timestamp())
    message["caption"] = f"PostgreSQL admin posts smoke {now.isoformat()}"
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
