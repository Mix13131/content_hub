from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from content_hub.models import Post, PublicationLog


@dataclass(frozen=True)
class TelegramIngestionResult:
    ignored: bool
    created: bool
    post_id: str | None = None
    reason: str | None = None


class TelegramIngestionService:
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
                post_id=existing_post.id,
                reason="duplicate",
            )

        post = self._build_post(message)
        db.add(post)
        db.flush()
        db.add(
            PublicationLog(
                post_id=post.id,
                service="telegram",
                level="info",
                event="post_received",
                message="Telegram channel post saved",
                api_response={"update_id": update.get("update_id")},
            )
        )
        db.commit()
        db.refresh(post)
        return TelegramIngestionResult(ignored=False, created=True, post_id=post.id)

    def _build_post(self, message: dict[str, Any]) -> Post:
        chat = message.get("chat") or {}
        telegram_post_id = int(message["message_id"])
        telegram_chat_id = int(chat["id"])
        photo_count = 1 if message.get("photo") else 0
        video_count = 1 if message.get("video") else 0

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
            source="telegram_channel",
            status="saved",
            website_status="Waiting",
            instagram_status="Waiting",
            facebook_status="Waiting",
            vk_status="Waiting",
            story_status=None,
        )

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

    def _detect_post_type(self, photo_count: int, video_count: int) -> str:
        if photo_count and video_count:
            return "mixed"
        if photo_count:
            return "photo"
        if video_count:
            return "video"
        return "text"

    def _build_telegram_url(
        self,
        chat: dict[str, Any],
        telegram_post_id: int,
    ) -> str | None:
        username = chat.get("username")
        if not username:
            return None
        return f"https://t.me/{username}/{telegram_post_id}"
