from __future__ import annotations

import copy
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from content_hub.connectors.engine import ConnectorEngine
from content_hub.connectors.instagram import InstagramConnector
from content_hub.connectors.registry import ConnectorRegistry
from content_hub.enums import PlatformStatus, PublicationPlatform
from content_hub.integrations.instagram.client import (
    InstagramContainerResult,
    InstagramPublishResult,
)
from content_hub.models import Base, Media, Post, PublicationJob
from content_hub.services.telegram_ingestion import TelegramIngestionService
from content_hub.settings import Settings


FIXTURES_DIR = PROJECT_ROOT / "tests" / "content_hub" / "fixtures"


@dataclass
class FakeInstagramClient:
    created_payloads: list[dict[str, str]] = field(default_factory=list)
    published_creation_ids: list[str] = field(default_factory=list)

    def create_image_container(
        self,
        *,
        image_url: str,
        caption: str,
    ) -> InstagramContainerResult:
        self.created_payloads.append({"image_url": image_url, "caption": caption})
        return InstagramContainerResult(
            container_id="ig-container-smoke",
            raw_response={"id": "ig-container-smoke"},
        )

    def publish_container(self, *, creation_id: str) -> InstagramPublishResult:
        self.published_creation_ids.append(creation_id)
        return InstagramPublishResult(
            media_id="ig-media-smoke",
            raw_response={"id": "ig-media-smoke"},
        )

    def get_permalink(self, *, media_id: str) -> str:
        return f"https://instagram.example/p/{media_id}"


def main() -> int:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    try:
        with SessionLocal() as db:
            payload = build_payload()
            result = TelegramIngestionService().ingest_update(payload, db)
            assert result.created is True, result

            post = get_post(db, payload)
            media = db.scalar(select(Media).where(Media.post_id == post.id))
            assert media is not None
            media.file_url = "https://cdn.example/instagram-smoke.jpg"
            media.storage_key = "telegram/smoke/instagram-smoke.jpg"
            db.commit()

            instagram_job = db.scalar(
                select(PublicationJob).where(
                    PublicationJob.post_id == post.id,
                    PublicationJob.platform == PublicationPlatform.instagram,
                )
            )
            assert instagram_job is not None

            fake_client = FakeInstagramClient()
            registry = ConnectorRegistry()
            registry.register(
                InstagramConnector(
                    client=fake_client,
                    settings=Settings(
                        database_url="sqlite://",
                        instagram_access_token="fake-token",
                        instagram_account_id="fake-account",
                    ),
                )
            )

            ConnectorEngine(registry=registry).publish_job(instagram_job.id, db)
            db.commit()
            db.refresh(post)
            db.refresh(instagram_job)

            assert instagram_job.status == PlatformStatus.Success
            assert instagram_job.external_post_id == "ig-media-smoke"
            assert instagram_job.external_url == (
                "https://instagram.example/p/ig-media-smoke"
            )
            assert post.instagram_status == PlatformStatus.Success
            assert fake_client.created_payloads == [
                {
                    "image_url": "https://cdn.example/instagram-smoke.jpg",
                    "caption": post.text,
                }
            ]
            assert fake_client.published_creation_ids == ["ig-container-smoke"]
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()

    print("Instagram connector fake smoke passed.")
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
    message["caption"] = f"Instagram connector smoke {now.isoformat()}"
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

