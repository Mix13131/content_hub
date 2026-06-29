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
from content_hub.connectors.engine import ConnectorEngine
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
        website_job = db.scalar(
            select(PublicationJob).where(
                PublicationJob.post_id == post.id,
                PublicationJob.platform == PublicationPlatform.website,
            )
        )
        assert website_job is not None

        ConnectorEngine().publish_job(website_job.id, db)
        db.commit()
        db.refresh(post)
        db.refresh(website_job)

        assert website_job.status == PlatformStatus.Success
        assert website_job.external_post_id == str(post.id)
        assert website_job.external_url == f"/news/{post.slug}"
        assert website_job.last_api_response == {
            "mode": "dry_run",
            "connector": "website",
            "media_count": 0,
        }
        assert post.website_status == PlatformStatus.Success
        assert post.status == PostStatus.partially_published
        assert has_log(db, website_job, "job_started")
        assert has_log(db, website_job, "job_succeeded")
        post_id = post.id
        job_id = website_job.id

    print("Connector engine PostgreSQL smoke passed.")
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
    message["text"] = f"Connector engine smoke {now.isoformat()}"
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
