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
from content_hub.models import Post, PublicationLog
from content_hub.settings import get_settings


FIXTURE_PATH = PROJECT_ROOT / "tests" / "content_hub" / "fixtures" / "telegram_text_channel_post.json"


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
        first_response = client.post("/webhooks/telegram", json=payload, headers=headers)
        second_response = client.post("/webhooks/telegram", json=payload, headers=headers)

    first_response.raise_for_status()
    second_response.raise_for_status()
    first_body = first_response.json()
    second_body = second_response.json()

    assert first_body["created"] is True, first_body
    assert second_body["created"] is False, second_body
    assert second_body["reason"] == "duplicate", second_body
    assert first_body["post_id"] == second_body["post_id"], (first_body, second_body)

    with SessionLocal() as db:
        post = verify_post(db, payload)
        verify_postgres_column_types(db)
        print("PostgreSQL webhook smoke passed.")
        print(f"Post id: {post.id}")
        print(f"Telegram chat/post: {post.telegram_chat_id}/{post.telegram_post_id}")
        print(f"Text: {post.text}")
    return 0


def build_payload() -> dict[str, Any]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload = copy.deepcopy(payload)
    now = datetime.now(timezone.utc)
    unique_id = int(time.time() * 1000)

    payload["update_id"] = unique_id
    message = payload["channel_post"]
    message["message_id"] = unique_id
    message["date"] = int(now.timestamp())
    message["text"] = f"PostgreSQL smoke post {now.isoformat()}"
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
    assert post.text == message["text"]
    assert post.status == "saved"
    assert post.website_status == "Waiting"
    assert post.instagram_status == "Waiting"
    assert post.facebook_status == "Waiting"
    assert post.vk_status == "Waiting"
    assert post.telegram_posted_at.tzinfo is not None

    log = db.scalar(select(PublicationLog).where(PublicationLog.post_id == post.id))
    assert log is not None
    assert log.service == "telegram"
    assert log.event == "post_received"
    return post


def verify_postgres_column_types(db: Session) -> None:
    rows = db.execute(
        text(
            """
            select table_name, column_name, data_type, udt_name
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
                'vk_status'
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


if __name__ == "__main__":
    raise SystemExit(main())
