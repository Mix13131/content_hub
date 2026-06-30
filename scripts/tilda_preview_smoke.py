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
from content_hub.connectors.tilda import TildaConnector
from content_hub.db import SessionLocal
from content_hub.models import Media, Post
from content_hub.renderers.html_renderer import HtmlRenderer
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

        with SessionLocal() as db:
            post = get_post(db, payload)
            media = media_for_post(db, post)
            rendered = HtmlRenderer().render(post, media)
            connector_result = TildaConnector().publish(post, media)
            assert connector_result.success is True
            assert connector_result.external_url == f"tilda-preview://{post.slug}"
            assert connector_result.raw_response == {
                "mode": "preview",
                "html_length": len(rendered.html),
            }
            assert post.title in rendered.html
            assert post.text in rendered.html
            assert "<img " in rendered.html
            assert "photo-large-file-id" not in rendered.html

        preview_response = client.get(
            f"/preview/tilda/{post_id}",
            headers=admin_headers,
        )
        preview_response.raise_for_status()
        preview_html = preview_response.text
        assert "<img " in preview_html
        assert "Tilda preview smoke" in preview_html
        assert "photo-large-file-id" not in preview_html

    print("Tilda preview PostgreSQL smoke passed.")
    print(f"post: {post_id}")
    return 0


def build_payload() -> dict[str, Any]:
    payload = json.loads(
        (FIXTURES_DIR / "telegram_photo_channel_post.json").read_text(
            encoding="utf-8"
        )
    )
    payload = copy.deepcopy(payload)
    now = datetime.now(timezone.utc)
    unique_id = int(time.time_ns() // 1000)
    payload["update_id"] = unique_id
    message = payload["channel_post"]
    message["message_id"] = unique_id
    message["date"] = int(now.timestamp())
    message["caption"] = f"Tilda preview smoke {now.isoformat()}"
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


def media_for_post(db, post: Post) -> list[Media]:
    return db.scalars(
        select(Media).where(Media.post_id == post.id).order_by(Media.sort_order)
    ).all()


if __name__ == "__main__":
    raise SystemExit(main())
