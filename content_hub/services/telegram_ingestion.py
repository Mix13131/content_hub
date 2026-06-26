from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from content_hub.enums import (
    ContentSource,
    MediaType,
    PlatformStatus,
    PostStatus,
    PostType,
    PublicationLogLevel,
)
from content_hub.models import Media, Post, PublicationLog
from content_hub.services.publication_queue import PublicationQueueService


@dataclass(frozen=True)
class TelegramIngestionResult:
    ignored: bool
    created: bool
    post_id: str | None = None
    reason: str | None = None


class TelegramIngestionService:
    def __init__(
        self,
        publication_queue_service: PublicationQueueService | None = None,
    ) -> None:
        self.publication_queue_service = (
            publication_queue_service or PublicationQueueService()
        )

    def ingest_update(
        self,
        update: dict[str, Any],
        db: Session,
    ) -> TelegramIngestionResult:
        message = update.get("channel_post")
        if not isinstance(message, dict):
            return TelegramIngestionResult(
                ignored=True,
                created=False,
                reason="update_without_channel_post",
            )

        chat = message.get("chat") or {}
        telegram_chat_id = chat.get("id")
        telegram_post_id = message.get("message_id")
        if telegram_chat_id is None or telegram_post_id is None:
            return TelegramIngestionResult(
                ignored=True,
                created=False,
                reason="missing_chat_or_message_id",
            )

        existing_post = db.scalar(
            select(Post).where(
                Post.telegram_chat_id == int(telegram_chat_id),
                Post.telegram_post_id == int(telegram_post_id),
            )
        )
        if existing_post is not None:
            return TelegramIngestionResult(
                ignored=False,
                created=False,
                post_id=str(existing_post.id),
                reason="duplicate",
            )

        post = self._build_post(message)
        db.add(post)
        db.flush()
        db.add_all(self._build_media_records(message, post.id))
        db.add(
            PublicationLog(
                post_id=post.id,
                service="telegram",
                level=PublicationLogLevel.info,
                event="post_received",
                message="Telegram channel post saved",
                api_response={"update_id": update.get("update_id")},
            )
        )
        self.publication_queue_service.create_jobs_for_post(post, db)
        db.commit()
        db.refresh(post)
        return TelegramIngestionResult(ignored=False, created=True, post_id=str(post.id))

    def _build_post(self, message: dict[str, Any]) -> Post:
        chat = message.get("chat") or {}
        telegram_post_id = int(message["message_id"])
        telegram_chat_id = int(chat["id"])
        photo_count = self._photo_count(message)
        video_count = self._video_count(message)

        return Post(
            telegram_chat_id=telegram_chat_id,
            telegram_post_id=telegram_post_id,
            telegram_media_group_id=message.get("media_group_id"),
            telegram_message_ids=[telegram_post_id],
            telegram_url=self._build_telegram_url(chat, telegram_post_id),
            text=self._extract_text(message),
            author=self._extract_author(message),
            telegram_posted_at=datetime.fromtimestamp(
                int(message["date"]),
                tz=timezone.utc,
            ),
            post_type=self._detect_post_type(photo_count, video_count),
            photo_count=photo_count,
            video_count=video_count,
            source=ContentSource.telegram_channel,
            status=PostStatus.saved,
            website_status=PlatformStatus.Waiting,
            instagram_status=PlatformStatus.Waiting,
            facebook_status=PlatformStatus.Waiting,
            vk_status=PlatformStatus.Waiting,
            story_status=None,
        )

    def _build_media_records(
        self,
        message: dict[str, Any],
        post_id: object,
    ) -> list[Media]:
        media_records: list[Media] = []
        photo = self._largest_photo_size(message)
        if photo is not None:
            media_records.append(
                Media(
                    post_id=post_id,
                    type=MediaType.photo,
                    file_url=None,
                    storage_key=None,
                    telegram_file_id=str(photo["file_id"]),
                    telegram_file_unique_id=self._optional_str(
                        photo.get("file_unique_id")
                    ),
                    sort_order=0,
                    size_bytes=self._optional_int(photo.get("file_size")),
                    width=self._optional_int(photo.get("width")),
                    height=self._optional_int(photo.get("height")),
                )
            )

        video = message.get("video")
        if isinstance(video, dict) and video.get("file_id"):
            media_records.append(
                Media(
                    post_id=post_id,
                    type=MediaType.video,
                    file_url=None,
                    storage_key=None,
                    telegram_file_id=str(video["file_id"]),
                    telegram_file_unique_id=self._optional_str(
                        video.get("file_unique_id")
                    ),
                    sort_order=0,
                    mime_type=self._optional_str(video.get("mime_type")),
                    size_bytes=self._optional_int(video.get("file_size")),
                    width=self._optional_int(video.get("width")),
                    height=self._optional_int(video.get("height")),
                    duration_seconds=self._optional_int(video.get("duration")),
                )
            )

        return media_records

    def _extract_text(self, message: dict[str, Any]) -> str:
        text = message.get("text")
        if isinstance(text, str):
            return text
        caption = message.get("caption")
        if isinstance(caption, str):
            return caption
        return ""

    def _extract_author(self, message: dict[str, Any]) -> str | None:
        author_signature = message.get("author_signature")
        if isinstance(author_signature, str) and author_signature:
            return author_signature
        sender_chat = message.get("sender_chat")
        if isinstance(sender_chat, dict) and sender_chat.get("title"):
            return str(sender_chat["title"])
        chat = message.get("chat")
        if isinstance(chat, dict) and chat.get("title"):
            return str(chat["title"])
        return None

    def _detect_post_type(self, photo_count: int, video_count: int) -> PostType:
        if photo_count and video_count:
            return PostType.mixed
        if photo_count:
            return PostType.photo
        if video_count:
            return PostType.video
        return PostType.text

    def _photo_count(self, message: dict[str, Any]) -> int:
        return 1 if self._largest_photo_size(message) is not None else 0

    def _video_count(self, message: dict[str, Any]) -> int:
        video = message.get("video")
        return 1 if isinstance(video, dict) and video.get("file_id") else 0

    def _largest_photo_size(self, message: dict[str, Any]) -> dict[str, Any] | None:
        photos = message.get("photo")
        if not isinstance(photos, list):
            return None
        valid_photos = [
            photo
            for photo in photos
            if isinstance(photo, dict) and photo.get("file_id")
        ]
        if not valid_photos:
            return None
        return max(valid_photos, key=self._photo_sort_key)

    def _photo_sort_key(self, photo: dict[str, Any]) -> tuple[int, int]:
        file_size = self._optional_int(photo.get("file_size")) or 0
        width = self._optional_int(photo.get("width")) or 0
        height = self._optional_int(photo.get("height")) or 0
        return (file_size, width * height)

    def _optional_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    def _build_telegram_url(
        self,
        chat: dict[str, Any],
        telegram_post_id: int,
    ) -> str | None:
        username = chat.get("username")
        if not username:
            return None
        return f"https://t.me/{username}/{telegram_post_id}"
