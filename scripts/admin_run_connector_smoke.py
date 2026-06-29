from __future__ import annotations

import copy
import json
import sys
import time
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
from content_hub.enums import PlatformStatus, PostStatus, PublicationPlatform
from content_hub.models import Post, PublicationJob, PublicationLog
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

        post_id = webhook_body["post_id"]
        post_detail_before_response = client.get(
            f"/admin/posts/{post_id}",
            headers=admin_headers,
        )
        post_detail_before_response.raise_for_status()
        assert post_detail_before_response.json()["is_public"] is False

        run_response = client.post(
            f"/admin/posts/{post_id}/run/{PublicationPlatform.website.value}",
            headers=admin_headers,
        )
        run_response.raise_for_status()
        run_body = run_response.json()
        assert run_body["id"] == post_id
        assert run_body["is_public"] is True
        assert run_body["published_at"] is not None
        assert run_body["website_status"] == PlatformStatus.Success.value
        website_job = next(
            job
            for job in run_body["jobs"]
            if job["platform"] == PublicationPlatform.website.value
        )
        assert website_job["status"] == PlatformStatus.Success.value
        assert website_job["external_post_id"] == post_id
        assert website_job["external_url"] == f"/news/{run_body['slug']}"

        public_list_response = client.get("/api/posts/public")
        public_list_response.raise_for_status()
        assert post_id in {post["id"] for post in public_list_response.json()}

        public_slug_response = client.get(
            f"/api/posts/public/slug/{run_body['slug']}"
        )
        public_slug_response.raise_for_status()
        assert public_slug_response.json()["id"] == post_id

        news_response = client.get("/news")
        news_response.raise_for_status()
        assert run_body["title"] in news_response.text

        news_detail_response = client.get(f"/news/{run_body['slug']}")
        news_detail_response.raise_for_status()
        assert run_body["title"] in news_detail_response.text

    with SessionLocal() as db:
        post = get_post(db, payload)
        website_job = db.scalar(
            select(PublicationJob).where(
                PublicationJob.post_id == post.id,
                PublicationJob.platform == PublicationPlatform.website,
            )
        )
        assert website_job is not None
        assert website_job.status == PlatformStatus.Success
        assert website_job.external_post_id == str(post.id)
        assert website_job.external_url == f"/news/{post.slug}"
        assert post.is_public is True
        assert post.published_at is not None
        assert post.website_status == PlatformStatus.Success
        assert post.status == PostStatus.partially_published
        assert has_log(db, website_job, "job_started")
        assert has_log(db, website_job, "job_succeeded")
        post_id = post.id
        job_id = website_job.id

    print("Admin connector run PostgreSQL smoke passed.")
    print(f"post: {post_id}")
    print(f"website job: {job_id}")
    return 0


def build_payload() -> dict[str, Any]:
    payload = json.loads(
        (FIXTURES_DIR / "telegram_text_channel_post.json").read_text(encoding="utf-8")
    )
    payload = copy.deepcopy(payload)
    now = datetime.now(timezone.utc)
    unique_id = int(time.time_ns() // 1000)
    payload["update_id"] = unique_id
    message = payload["channel_post"]
    message["message_id"] = unique_id
    message["date"] = int(now.timestamp())
    message["text"] = f"Admin connector run smoke {now.isoformat()}"
    return payload


def get_post(db, payload: dict[str, Any]) -> Post:
    message = payload["channel_post"]
    post = db.scalar(
        select(Post).where(
            Post.telegram_chat_id == int(message["chat"]["id"]),
            Post.telegram_post_id == int(message["message_id"]),
        )
    )
    assert post is not None
    return post


def has_log(db, job: PublicationJob, event: str) -> bool:
    return (
        db.scalar(
            select(PublicationLog).where(
                PublicationLog.job_id == job.id,
                PublicationLog.event == event,
            )
        )
        is not None
    )


if __name__ == "__main__":
    raise SystemExit(main())
