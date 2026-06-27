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
from content_hub.enums import MediaType, PlatformStatus, PostStatus, PostType
from content_hub.enums import PublicationPlatform
from content_hub.models import Media, Post, PublicationJob, PublicationLog
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
            service = PublicationStatusService()
            website_job = get_job(db, post_id, PublicationPlatform.website)
            service.start_job(website_job.id, db)
            service.mark_error(
                website_job.id,
                db,
                error_code="ADMIN_POST_RETRY_SINGLE",
                error_message="Prepared single retry",
            )
            db.commit()

        retry_one_response = client.post(
            f"/admin/posts/{post_id}/retry/{PublicationPlatform.website.value}",
            headers=admin_headers,
        )
        retry_one_response.raise_for_status()
        retry_one_body = retry_one_response.json()
        assert retry_one_body["retried_count"] == 1
        assert retry_one_body["retried_platforms"] == [
            PublicationPlatform.website.value
        ]
        website_job_body = job_from_detail(
            retry_one_body["post"],
            PublicationPlatform.website,
        )
        assert website_job_body["status"] == PlatformStatus.Waiting.value
        assert website_job_body["attempt_count"] == 1
        assert website_job_body["last_error_code"] is None

        with SessionLocal() as db:
            service = PublicationStatusService()
            instagram_job = get_job(db, post_id, PublicationPlatform.instagram)
            vk_job = get_job(db, post_id, PublicationPlatform.vk)
            facebook_job = get_job(db, post_id, PublicationPlatform.facebook)
            service.start_job(instagram_job.id, db)
            service.mark_error(
                instagram_job.id,
                db,
                error_code="ADMIN_POST_RETRY_FAILED",
                error_message="Prepared failed retry",
            )
            service.start_job(vk_job.id, db)
            service.schedule_retry(
                vk_job.id,
                db,
                error_code="ADMIN_POST_RETRY_SCHEDULED",
                error_message="Prepared scheduled retry",
            )
            service.mark_success(facebook_job.id, db)
            db.commit()

        retry_failed_response = client.post(
            f"/admin/posts/{post_id}/retry-failed",
            headers=admin_headers,
        )
        retry_failed_response.raise_for_status()
        retry_failed_body = retry_failed_response.json()
        assert retry_failed_body["retried_count"] == 2
        assert set(retry_failed_body["retried_platforms"]) == {
            PublicationPlatform.instagram.value,
            PublicationPlatform.vk.value,
        }
        assert job_from_detail(
            retry_failed_body["post"],
            PublicationPlatform.website,
        )["status"] == PlatformStatus.Waiting.value
        assert job_from_detail(
            retry_failed_body["post"],
            PublicationPlatform.instagram,
        )["status"] == PlatformStatus.Waiting.value
        assert job_from_detail(
            retry_failed_body["post"],
            PublicationPlatform.vk,
        )["status"] == PlatformStatus.Waiting.value
        assert job_from_detail(
            retry_failed_body["post"],
            PublicationPlatform.facebook,
        )["status"] == PlatformStatus.Success.value
        assert retry_failed_body["post"]["status"] == (
            PostStatus.partially_published.value
        )

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
        jobs_by_platform = {job.platform: job for job in jobs}
        assert jobs_by_platform[PublicationPlatform.website].status == (
            PlatformStatus.Waiting
        )
        assert jobs_by_platform[PublicationPlatform.instagram].status == (
            PlatformStatus.Waiting
        )
        assert jobs_by_platform[PublicationPlatform.vk].status == (
            PlatformStatus.Waiting
        )
        assert jobs_by_platform[PublicationPlatform.facebook].status == (
            PlatformStatus.Success
        )

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


def get_job(
    db,
    post_id: uuid.UUID,
    platform: PublicationPlatform,
) -> PublicationJob:
    job = db.scalar(
        select(PublicationJob).where(
            PublicationJob.post_id == post_id,
            PublicationJob.platform == platform,
        )
    )
    assert job is not None
    return job


def job_from_detail(
    detail: dict[str, Any],
    platform: PublicationPlatform,
) -> dict[str, Any]:
    for job in detail["jobs"]:
        if job["platform"] == platform.value:
            return job
    raise AssertionError(f"Missing job for platform {platform.value}")


if __name__ == "__main__":
    raise SystemExit(main())
