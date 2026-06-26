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
from content_hub.models import Post, PublicationJob
from content_hub.services.publication_status import PublicationStatusService
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

    payload = build_payload()
    headers = {}
    if settings.telegram_webhook_secret:
        headers["X-Telegram-Bot-Api-Secret-Token"] = settings.telegram_webhook_secret

    with TestClient(app) as client:
        response = client.post("/webhooks/telegram", json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()
        assert body["created"] is True, body

    with SessionLocal() as db:
        post = get_post(db, payload)
        jobs = {
            job.platform: job
            for job in db.scalars(
                select(PublicationJob).where(PublicationJob.post_id == post.id)
            ).all()
        }
        assert len(jobs) == 4

        service = PublicationStatusService()
        website_job = jobs[PublicationPlatform.website]
        instagram_job = jobs[PublicationPlatform.instagram]

        service.start_job(website_job.id, db)
        service.mark_success(
            website_job.id,
            db,
            external_post_id="website-smoke-id",
            external_url="https://example.test/news/website-smoke-id",
            raw_response={"smoke": "success"},
        )
        service.start_job(instagram_job.id, db)
        service.mark_error(
            instagram_job.id,
            db,
            error_code="SMOKE_ERROR",
            error_message="Simulated publisher failure",
            raw_response={"smoke": "error"},
        )
        db.commit()
        db.refresh(post)
        db.refresh(instagram_job)

        assert post.status == PostStatus.partially_published
        assert post.website_status == PlatformStatus.Success
        assert post.instagram_status == PlatformStatus.Error

        service.manual_retry(instagram_job.id, db)
        db.commit()
        db.refresh(post)
        db.refresh(instagram_job)

        assert instagram_job.status == PlatformStatus.Waiting
        assert instagram_job.attempt_count == 1
        assert instagram_job.next_retry_at is None
        assert instagram_job.last_error_code is None
        assert instagram_job.last_error_message is None
        assert post.status == PostStatus.partially_published
        post_id = post.id
        website_job_id = website_job.id
        instagram_job_id = instagram_job.id

    print("Publication status PostgreSQL smoke passed.")
    print(f"post: {post_id}")
    print(f"website job: {website_job_id}")
    print(f"instagram job retried: {instagram_job_id}")
    return 0


def build_payload() -> dict[str, Any]:
    payload = json.loads(
        (FIXTURES_DIR / "telegram_text_channel_post.json").read_text(encoding="utf-8")
    )
    payload = copy.deepcopy(payload)
    now = datetime.now(timezone.utc)
    unique_id = int(time.time() * 1000)
    payload["update_id"] = unique_id
    message = payload["channel_post"]
    message["message_id"] = unique_id
    message["date"] = int(now.timestamp())
    message["text"] = f"Publication status smoke {now.isoformat()}"
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


if __name__ == "__main__":
    raise SystemExit(main())
