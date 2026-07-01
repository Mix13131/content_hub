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

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from content_hub.models import Base, Media, Post, PublicationJob
from content_hub.services.telegram_files import TelegramDownloadedFile
from content_hub.services.telegram_ingestion import TelegramIngestionService
from content_hub.storage.base import StorageResult
from content_hub.storage.engine import MediaStorageEngine


FIXTURES_DIR = PROJECT_ROOT / "tests" / "content_hub" / "fixtures"


class FakeStorage:
    def __init__(self) -> None:
        self.uploaded: list[tuple[str, str | None]] = []

    def upload(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> StorageResult:
        self.uploaded.append((key, content_type))
        return StorageResult(
            storage_key=key,
            file_url=self.public_url(key),
            provider="fake",
            content_type=content_type,
            size_bytes=len(content),
        )

    def delete(self, key: str) -> None:
        return None

    def exists(self, key: str) -> bool:
        return False

    def public_url(self, key: str) -> str:
        return f"https://cdn.example/{key}"


class FakeTelegramDownloader:
    def __init__(self) -> None:
        self.downloaded: list[str] = []

    def download(self, file_id: str) -> TelegramDownloadedFile:
        self.downloaded.append(file_id)
        return TelegramDownloadedFile(
            content=b"fake image bytes",
            file_path="photos/content-hub.jpg",
            content_type="application/octet-stream",
        )


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
            storage = FakeStorage()
            downloader = FakeTelegramDownloader()
            result = TelegramIngestionService().ingest_update(
                payload,
                db,
                storage_engine=MediaStorageEngine("fake", storage),
                telegram_file_downloader=downloader,
            )

            assert result.created is True, result
            post = db.scalar(select(Post))
            assert post is not None
            assert post.status == "queued"
            media = db.scalar(select(Media))
            assert media is not None
            expected_key = (
                f"telegram/{post.telegram_chat_id}/{post.telegram_post_id}/"
                "photo-photo-large-unique-id.jpg"
            )
            assert media.storage_key == expected_key
            assert media.file_url == f"https://cdn.example/{expected_key}"
            assert media.mime_type == "image/jpeg"
            assert downloader.downloaded == ["photo-large-file-id"]
            assert storage.uploaded == [(expected_key, "image/jpeg")]
            assert len(db.scalars(select(PublicationJob)).all()) == 4
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()

    print("Media storage fake smoke passed.")
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
    message["caption"] = f"Media storage smoke {now.isoformat()}"
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
