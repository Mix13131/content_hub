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
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from content_hub.app import app
from content_hub.db import SessionLocal
from content_hub.enums import (
    MediaType,
    PlatformStatus,
    PostType,
    PublicationPlatform,
)
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

    payloads = [
        build_payload("telegram_text_channel_post.json", offset=1),
        build_payload("telegram_photo_channel_post.json", offset=2),
        build_payload("telegram_video_channel_post.json", offset=3),
    ]
    headers = {}
    if settings.telegram_webhook_secret:
        headers["X-Telegram-Bot-Api-Secret-Token"] = settings.telegram_webhook_secret

    with TestClient(app) as client:
        for payload in payloads:
            first_response = client.post(
                "/webhooks/telegram", json=payload, headers=headers
            )
            second_response = client.post(
                "/webhooks/telegram", json=payload, headers=headers
            )

            first_response.raise_for_status()
            second_response.raise_for_status()
            first_body = first_response.json()
            second_body = second_response.json()

            assert first_body["created"] is True, first_body
            assert second_body["created"] is False, second_body
            assert second_body["reason"] == "duplicate", second_body
            assert first_body["post_id"] == second_body["post_id"], (
                first_body,
                second_body,
            )

    with SessionLocal() as db:
        posts = [verify_post(db, payload) for payload in payloads]
        verify_postgres_column_types(db)
        verify_postgres_constraints(db)
        print("PostgreSQL webhook smoke passed.")
        for post in posts:
            print(
                f"{post.post_type.value}: {post.id} "
                f"{post.telegram_chat_id}/{post.telegram_post_id}"
            )
    return 0


def build_payload(fixture_name: str, offset: int) -> dict[str, Any]:
    payload = json.loads((FIXTURES_DIR / fixture_name).read_text(encoding="utf-8"))
    payload = copy.deepcopy(payload)
    now = datetime.now(timezone.utc)
    unique_id = int(time.time_ns() // 1000) + offset

    payload["update_id"] = unique_id
    message = payload["channel_post"]
    message["message_id"] = unique_id
    message["date"] = int(now.timestamp())
    if "text" in message:
        message["text"] = f"PostgreSQL smoke text post {now.isoformat()}"
    if "caption" in message:
        message["caption"] = f"PostgreSQL smoke {fixture_name} {now.isoformat()}"
    return payload


def verify_post(db: Session, payload: dict[str, Any]) -> Post:
    message = payload["channel_post"]
    chat_id = int(message["chat"]["id"])
    message_id = int(message["message_id"])

    post = db.scalar(
        select(Post).where(
            Post.telegram_chat_id == chat_id,
            Post.telegram_post_id == message_id,
        )
    )
    assert post is not None
    assert isinstance(post.id, uuid.UUID), type(post.id)
    assert post.telegram_message_ids == [message_id]
    assert post.text == (message.get("text") or message.get("caption") or "")
    assert post.status == "queued"
    assert post.website_status == "Waiting"
    assert post.instagram_status == "Waiting"
    assert post.facebook_status == "Waiting"
    assert post.vk_status == "Waiting"
    assert post.telegram_posted_at.tzinfo is not None

    log = db.scalar(
        select(PublicationLog).where(
            PublicationLog.post_id == post.id,
            PublicationLog.event == "post_received",
        )
    )
    assert log is not None
    assert log.service == "telegram"
    assert log.event == "post_received"
    verify_publication_jobs(db, post)
    verify_media(db, post, message)
    return post


def verify_publication_jobs(db: Session, post: Post) -> None:
    jobs = db.scalars(
        select(PublicationJob).where(PublicationJob.post_id == post.id)
    ).all()
    assert len(jobs) == 4
    assert {job.platform for job in jobs} == {
        PublicationPlatform.website,
        PublicationPlatform.instagram,
        PublicationPlatform.vk,
        PublicationPlatform.facebook,
    }
    for job in jobs:
        assert job.status == PlatformStatus.Waiting
        assert job.attempt_count == 0
        assert job.max_attempts == 5
        assert job.next_retry_at is None
        assert job.external_post_id is None
        assert job.external_url is None
        assert job.last_error_code is None
        assert job.last_error_message is None
        assert job.last_api_response is None

    queue_log = db.scalar(
        select(PublicationLog).where(
            PublicationLog.post_id == post.id,
            PublicationLog.event == "publication_jobs_created",
        )
    )
    assert queue_log is not None
    assert queue_log.service == "queue"
    assert "4" in queue_log.message


def verify_media(db: Session, post: Post, message: dict[str, Any]) -> None:
    media_rows = db.scalars(select(Media).where(Media.post_id == post.id)).all()
    if "photo" in message:
        assert post.post_type == PostType.photo
        assert post.photo_count == 1
        assert post.video_count == 0
        assert len(media_rows) == 1
        media = media_rows[0]
        assert media.type == MediaType.photo
        assert media.telegram_file_id == "photo-large-file-id"
        assert media.telegram_file_unique_id == "photo-large-unique-id"
        assert media.file_url is None
        assert media.storage_key is None
        return

    if "video" in message:
        assert post.post_type == PostType.video
        assert post.photo_count == 0
        assert post.video_count == 1
        assert len(media_rows) == 1
        media = media_rows[0]
        assert media.type == MediaType.video
        assert media.telegram_file_id == "video-file-id"
        assert media.telegram_file_unique_id == "video-unique-id"
        assert media.mime_type == "video/mp4"
        assert media.duration_seconds == 27
        assert media.file_url is None
        assert media.storage_key is None
        return

    assert post.post_type == PostType.text
    assert post.photo_count == 0
    assert post.video_count == 0
    assert media_rows == []


def verify_postgres_column_types(db: Session) -> None:
    rows = db.execute(
        text(
            """
            select table_name, column_name, data_type, udt_name, is_nullable
            from information_schema.columns
            where table_schema = current_schema()
              and table_name in ('posts', 'media', 'publication_jobs', 'publication_logs')
              and column_name in (
                'id',
                'post_id',
                'job_id',
                'telegram_message_ids',
                'telegram_posted_at',
                'created_at',
                'updated_at',
                'status',
                'website_status',
                'instagram_status',
                'facebook_status',
                'vk_status',
                'file_url',
                'storage_key'
              )
            """
        )
    ).mappings()

    columns = {
        (row["table_name"], row["column_name"]): row
        for row in rows
    }

    assert columns[("posts", "id")]["udt_name"] == "uuid"
    assert columns[("media", "id")]["udt_name"] == "uuid"
    assert columns[("media", "post_id")]["udt_name"] == "uuid"
    assert columns[("publication_jobs", "id")]["udt_name"] == "uuid"
    assert columns[("publication_logs", "id")]["udt_name"] == "uuid"
    assert columns[("posts", "telegram_message_ids")]["udt_name"] == "jsonb"
    assert columns[("posts", "telegram_posted_at")]["udt_name"] == "timestamptz"
    assert columns[("posts", "created_at")]["udt_name"] == "timestamptz"
    assert columns[("posts", "updated_at")]["udt_name"] == "timestamptz"
    assert columns[("posts", "status")]["data_type"] == "character varying"
    assert columns[("posts", "website_status")]["data_type"] == "character varying"
    assert columns[("media", "file_url")]["is_nullable"] == "YES"
    assert columns[("media", "storage_key")]["is_nullable"] == "YES"


def verify_postgres_constraints(db: Session) -> None:
    constraint_exists = db.scalar(
        text(
            """
            select exists (
                select 1
                from information_schema.table_constraints
                where table_schema = current_schema()
                  and table_name = 'publication_jobs'
                  and constraint_name = 'uq_publication_jobs_post_platform'
                  and constraint_type = 'UNIQUE'
            )
            """
        )
    )
    assert constraint_exists is True


if __name__ == "__main__":
    raise SystemExit(main())
