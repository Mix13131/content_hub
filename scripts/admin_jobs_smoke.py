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
from content_hub.enums import PlatformStatus, PostStatus, PublicationPlatform
from content_hub.models import Post, PublicationJob
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

        jobs_response = client.get("/admin/jobs", headers=admin_headers)
        jobs_response.raise_for_status()
        jobs = [
            job
            for job in jobs_response.json()
            if job["post_id"] == webhook_body["post_id"]
        ]
        assert len(jobs) == 4, jobs
        jobs_by_platform = {job["platform"]: job for job in jobs}

        website_job_id = uuid.UUID(
            jobs_by_platform[PublicationPlatform.website.value]["id"]
        )
        instagram_job_id = uuid.UUID(
            jobs_by_platform[PublicationPlatform.instagram.value]["id"]
        )

        start_response = client.post(
            f"/admin/jobs/{website_job_id}/start",
            headers=admin_headers,
        )
        start_response.raise_for_status()
        assert start_response.json()["status"] == PlatformStatus.Publishing.value

        success_response = client.post(
            f"/admin/jobs/{website_job_id}/success",
            json={
                "external_post_id": "website-admin-smoke-id",
                "external_url": "https://example.test/news/admin-smoke",
                "raw_response": {"smoke": "success"},
            },
            headers=admin_headers,
        )
        success_response.raise_for_status()
        assert success_response.json()["status"] == PlatformStatus.Success.value

        error_start_response = client.post(
            f"/admin/jobs/{instagram_job_id}/start",
            headers=admin_headers,
        )
        error_start_response.raise_for_status()
        error_response = client.post(
            f"/admin/jobs/{instagram_job_id}/error",
            json={
                "error_code": "ADMIN_SMOKE_ERROR",
                "error_message": "Simulated admin endpoint failure",
                "raw_response": {"smoke": "error"},
            },
            headers=admin_headers,
        )
        error_response.raise_for_status()
        assert error_response.json()["status"] == PlatformStatus.Error.value

        retry_response = client.post(
            f"/admin/jobs/{instagram_job_id}/retry",
            headers=admin_headers,
        )
        retry_response.raise_for_status()
        assert retry_response.json()["status"] == PlatformStatus.Waiting.value

        detail_response = client.get(
            f"/admin/jobs/{instagram_job_id}",
            headers=admin_headers,
        )
        detail_response.raise_for_status()
        detail_body = detail_response.json()
        assert detail_body["logs"][0]["event"] == "job_manual_retry"

    with SessionLocal() as db:
        post = get_post(db, payload)
        assert post.status == PostStatus.partially_published
        assert post.website_status == PlatformStatus.Success
        assert post.instagram_status == PlatformStatus.Waiting

        website_job = db.get(PublicationJob, website_job_id)
        instagram_job = db.get(PublicationJob, instagram_job_id)
        assert website_job is not None
        assert instagram_job is not None
        assert website_job.status == PlatformStatus.Success
        assert website_job.external_post_id == "website-admin-smoke-id"
        assert instagram_job.status == PlatformStatus.Waiting
        assert instagram_job.attempt_count == 1
        assert instagram_job.last_error_code is None
        assert instagram_job.last_error_message is None
        post_id = post.id

    print("Admin jobs PostgreSQL smoke passed.")
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
    unique_id = int(time.time_ns() // 1000)
    payload["update_id"] = unique_id
    message = payload["channel_post"]
    message["message_id"] = unique_id
    message["date"] = int(now.timestamp())
    message["text"] = f"Admin jobs smoke {now.isoformat()}"
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
