from __future__ import annotations

from collections.abc import Collection
import logging
import re
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
from content_hub.services.seo import build_default_seo
from content_hub.services.telegram_files import (
    TelegramFileDownloadError,
    TelegramFileDownloader,
)
from content_hub.storage.base import StorageError
from content_hub.storage.engine import MediaStorageEngine


logger = logging.getLogger(__name__)
PHOTO_MIME_TYPE = "image/jpeg"
GENERIC_BINARY_MIME_TYPE = "application/octet-stream"


@dataclass(frozen=True)
class TelegramIngestionResult:
    ignored: bool
    created: bool
    post_id: str | None = None
    reason: str | None = None


class MediaStorageProcessingError(RuntimeError):
    def __init__(
        self,
        *,
        service: str,
        event: str,
        reason: str,
        message: str,
        error_type: str,
    ) -> None:
        super().__init__(message)
        self.service = service
        self.event = event
        self.reason = reason
        self.message = message
        self.error_type = error_type


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
        allowed_telegram_chat_ids: Collection[int] = (),
        storage_engine: MediaStorageEngine | None = None,
        telegram_file_downloader: TelegramFileDownloader | None = None,
    ) -> TelegramIngestionResult:
        update_id = update.get("update_id")
        update_type = self._detect_update_type(update)
        logger.info(
            "telegram_update_received update_id=%s keys=%s update_type=%s",
            update_id,
            self._top_level_keys(update),
            update_type,
        )
        result = self._ingest_update(
            update,
            db,
            update_type,
            allowed_telegram_chat_ids=allowed_telegram_chat_ids,
            storage_engine=storage_engine,
            telegram_file_downloader=telegram_file_downloader,
        )
        logger.info(
            "telegram_update_result update_id=%s ignored=%s created=%s "
            "reason=%s post_id=%s",
            update_id,
            result.ignored,
            result.created,
            result.reason,
            result.post_id,
        )
        return result

    def _ingest_update(
        self,
        update: dict[str, Any],
        db: Session,
        update_type: str,
        allowed_telegram_chat_ids: Collection[int],
        storage_engine: MediaStorageEngine | None,
        telegram_file_downloader: TelegramFileDownloader | None,
    ) -> TelegramIngestionResult:
        message = self._update_message(update, update_type)
        if not isinstance(message, dict):
            reason = (
                "empty_channel_post"
                if update_type == "channel_post"
                else "empty_message"
                if update_type == "message"
                else "unsupported_update_type"
                if update_type in {"edited_channel_post", "my_chat_member"}
                else "no_channel_post"
            )
            return TelegramIngestionResult(
                ignored=True,
                created=False,
                reason=reason,
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
        telegram_chat_id_int = int(telegram_chat_id)
        telegram_post_id_int = int(telegram_post_id)

        if (
            allowed_telegram_chat_ids
            and telegram_chat_id_int not in allowed_telegram_chat_ids
        ):
            return TelegramIngestionResult(
                ignored=True,
                created=False,
                reason="chat_not_allowed",
            )

        telegram_media_group_id = self._optional_str(message.get("media_group_id"))
        if telegram_media_group_id:
            existing_media_group_post = db.scalar(
                select(Post).where(
                    Post.telegram_chat_id == telegram_chat_id_int,
                    Post.telegram_media_group_id == telegram_media_group_id,
                )
            )
            if existing_media_group_post is not None:
                return self._append_media_group_item(
                    post=existing_media_group_post,
                    message=message,
                    update=update,
                    update_type=update_type,
                    db=db,
                    storage_engine=storage_engine,
                    telegram_file_downloader=telegram_file_downloader,
                )

        existing_post = db.scalar(
            select(Post).where(
                Post.telegram_chat_id == telegram_chat_id_int,
                Post.telegram_post_id == telegram_post_id_int,
            )
        )
        if existing_post is not None:
            return TelegramIngestionResult(
                ignored=False,
                created=False,
                post_id=str(existing_post.id),
                reason="duplicate",
            )

        source = self._source_for_update_type(update_type)
        post = self._build_post(message, source)
        db.add(post)
        db.flush()
        media_records = self._build_media_records(message, post.id)
        if storage_engine is not None and media_records:
            post.status = PostStatus.saving_media
            try:
                self._store_media_records(
                    message=message,
                    media_records=media_records,
                    storage_engine=storage_engine,
                    telegram_file_downloader=telegram_file_downloader,
                )
            except MediaStorageProcessingError as exc:
                db.add_all(media_records)
                self._record_storage_error(
                    post=post,
                    storage_engine=storage_engine,
                    error=exc,
                    db=db,
                )
                db.commit()
                db.refresh(post)
                return TelegramIngestionResult(
                    ignored=False,
                    created=True,
                    post_id=str(post.id),
                    reason=exc.reason,
                )

        db.add_all(media_records)
        db.add(
            PublicationLog(
                post_id=post.id,
                service="telegram",
                level=PublicationLogLevel.info,
                event="post_received",
                message="Telegram update saved",
                api_response={
                    "update_id": update.get("update_id"),
                    "update_type": update_type,
                },
            )
        )
        self.publication_queue_service.create_jobs_for_post(post, db)
        db.commit()
        db.refresh(post)
        return TelegramIngestionResult(ignored=False, created=True, post_id=str(post.id))

    def _append_media_group_item(
        self,
        *,
        post: Post,
        message: dict[str, Any],
        update: dict[str, Any],
        update_type: str,
        db: Session,
        storage_engine: MediaStorageEngine | None,
        telegram_file_downloader: TelegramFileDownloader | None,
    ) -> TelegramIngestionResult:
        telegram_post_id = int(message["message_id"])
        existing_message_ids = list(post.telegram_message_ids or [])
        if telegram_post_id in existing_message_ids:
            return TelegramIngestionResult(
                ignored=False,
                created=False,
                post_id=str(post.id),
                reason="duplicate",
            )

        old_text = post.text
        old_post_type = post.post_type
        post.telegram_message_ids = [*existing_message_ids, telegram_post_id]
        post.photo_count += self._photo_count(message)
        post.video_count += self._video_count(message)
        post.post_type = self._detect_post_type(post.photo_count, post.video_count)

        item_text = self._extract_text(message)
        if not post.text and item_text:
            post.text = item_text
            self._refresh_default_seo(post, old_text, old_post_type)

        next_sort_order = db.scalar(
            select(Media.sort_order)
            .where(Media.post_id == post.id)
            .order_by(Media.sort_order.desc())
            .limit(1)
        )
        sort_order_start = 0 if next_sort_order is None else next_sort_order + 1
        media_records = self._build_media_records(
            message,
            post.id,
            sort_order_start=sort_order_start,
        )
        if storage_engine is not None and media_records:
            post.status = PostStatus.saving_media
            try:
                self._store_media_records(
                    message=message,
                    media_records=media_records,
                    storage_engine=storage_engine,
                    telegram_file_downloader=telegram_file_downloader,
                )
            except MediaStorageProcessingError as exc:
                db.add_all(media_records)
                self._record_storage_error(
                    post=post,
                    storage_engine=storage_engine,
                    error=exc,
                    db=db,
                )
                db.commit()
                db.refresh(post)
                return TelegramIngestionResult(
                    ignored=False,
                    created=False,
                    post_id=str(post.id),
                    reason=exc.reason,
                )

        db.add_all(media_records)
        db.add(
            PublicationLog(
                post_id=post.id,
                service="telegram",
                level=PublicationLogLevel.info,
                event="media_group_item_appended",
                message="Telegram media group item appended",
                api_response={
                    "update_id": update.get("update_id"),
                    "update_type": update_type,
                    "telegram_post_id": telegram_post_id,
                },
            )
        )
        db.commit()
        db.refresh(post)
        return TelegramIngestionResult(
            ignored=False,
            created=False,
            post_id=str(post.id),
            reason="media_group_appended",
        )

    def _update_message(
        self,
        update: dict[str, Any],
        update_type: str,
    ) -> dict[str, Any] | None:
        if update_type == "channel_post":
            message = update.get("channel_post")
            return message if isinstance(message, dict) else None
        if update_type == "message":
            message = update.get("message")
            return message if isinstance(message, dict) else None
        return None

    def _source_for_update_type(self, update_type: str) -> ContentSource:
        if update_type == "message":
            return ContentSource.telegram_chat
        return ContentSource.telegram_channel

    def _detect_update_type(self, update: dict[str, Any]) -> str:
        for update_type in (
            "channel_post",
            "message",
            "edited_channel_post",
            "my_chat_member",
        ):
            if update_type in update:
                return update_type
        return "other"

    def _top_level_keys(self, update: dict[str, Any]) -> list[str]:
        return sorted(str(key) for key in update)

    def _build_post(self, message: dict[str, Any], source: ContentSource) -> Post:
        chat = message.get("chat") or {}
        telegram_post_id = int(message["message_id"])
        telegram_chat_id = int(chat["id"])
        photo_count = self._photo_count(message)
        video_count = self._video_count(message)
        text = self._extract_text(message)
        post_type = self._detect_post_type(photo_count, video_count)
        seo = build_default_seo(
            telegram_chat_id=telegram_chat_id,
            telegram_post_id=telegram_post_id,
            text=text,
            post_type=post_type,
        )

        return Post(
            telegram_chat_id=telegram_chat_id,
            telegram_post_id=telegram_post_id,
            telegram_media_group_id=message.get("media_group_id"),
            telegram_message_ids=[telegram_post_id],
            telegram_url=self._build_telegram_url(chat, telegram_post_id),
            text=text,
            author=self._extract_author(message),
            slug=seo.slug,
            title=seo.title,
            meta_description=seo.meta_description,
            image_alt_text=seo.image_alt_text,
            telegram_posted_at=datetime.fromtimestamp(
                int(message["date"]),
                tz=timezone.utc,
            ),
            post_type=post_type,
            photo_count=photo_count,
            video_count=video_count,
            is_public=False,
            source=source,
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
        *,
        sort_order_start: int = 0,
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
                    sort_order=sort_order_start + len(media_records),
                    mime_type=PHOTO_MIME_TYPE,
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
                    sort_order=sort_order_start + len(media_records),
                    mime_type=self._optional_str(video.get("mime_type")),
                    size_bytes=self._optional_int(video.get("file_size")),
                    width=self._optional_int(video.get("width")),
                    height=self._optional_int(video.get("height")),
                    duration_seconds=self._optional_int(video.get("duration")),
                )
            )

        return media_records

    def _store_media_records(
        self,
        *,
        message: dict[str, Any],
        media_records: list[Media],
        storage_engine: MediaStorageEngine,
        telegram_file_downloader: TelegramFileDownloader | None,
    ) -> None:
        if telegram_file_downloader is None:
            raise MediaStorageProcessingError(
                service="telegram",
                event="media_download_failed",
                reason="media_download_failed",
                message="Telegram file downloader is not configured.",
                error_type="configuration_error",
            )

        chat = message.get("chat") or {}
        telegram_chat_id = int(chat["id"])
        telegram_post_id = int(message["message_id"])

        for media in media_records:
            storage_key = self._storage_key(
                telegram_chat_id=telegram_chat_id,
                telegram_post_id=telegram_post_id,
                media=media,
            )
            media.storage_key = storage_key
            try:
                if storage_engine.exists(storage_key):
                    media.file_url = storage_engine.public_url(storage_key)
                    continue
            except StorageError as exc:
                raise MediaStorageProcessingError(
                    service="storage",
                    event="media_storage_exists_failed",
                    reason="media_storage_failed",
                    message="Media storage exists check failed.",
                    error_type=type(exc).__name__,
                ) from exc

            try:
                downloaded_file = telegram_file_downloader.download(
                    media.telegram_file_id
                )
            except TelegramFileDownloadError as exc:
                raise MediaStorageProcessingError(
                    service="telegram",
                    event="media_download_failed",
                    reason="media_download_failed",
                    message="Telegram media download failed.",
                    error_type=type(exc).__name__,
                ) from exc

            content_type = self._upload_content_type(
                media=media,
                downloaded_content_type=downloaded_file.content_type,
            )
            try:
                result = storage_engine.upload(
                    key=storage_key,
                    content=downloaded_file.content,
                    content_type=content_type,
                )
            except StorageError as exc:
                raise MediaStorageProcessingError(
                    service="storage",
                    event="media_upload_failed",
                    reason="media_upload_failed",
                    message="Media storage upload failed.",
                    error_type=type(exc).__name__,
                ) from exc

            media.storage_key = result.storage_key
            media.file_url = result.file_url
            if media.mime_type is None:
                media.mime_type = content_type
            if media.size_bytes is None:
                media.size_bytes = result.size_bytes or len(downloaded_file.content)

    def _record_storage_error(
        self,
        *,
        post: Post,
        storage_engine: MediaStorageEngine,
        error: MediaStorageProcessingError,
        db: Session,
    ) -> None:
        post.status = PostStatus.error
        db.add(
            PublicationLog(
                post_id=post.id,
                service=error.service,
                level=PublicationLogLevel.error,
                event=error.event,
                message=error.message,
                error_text=error.message,
                api_response={
                    "reason": error.reason,
                    "error_type": error.error_type,
                    "storage_provider": storage_engine.provider,
                },
            )
        )

    def _storage_key(
        self,
        *,
        telegram_chat_id: int,
        telegram_post_id: int,
        media: Media,
    ) -> str:
        file_unique_id = media.telegram_file_unique_id or f"unknown-{media.sort_order}"
        return (
            f"telegram/{telegram_chat_id}/{telegram_post_id}/"
            f"{media.type.value}-{self._safe_storage_part(file_unique_id)}"
            f".{self._storage_extension(media)}"
        )

    def _storage_extension(self, media: Media) -> str:
        if media.type == MediaType.photo:
            return "jpg"
        if media.mime_type == "video/quicktime":
            return "mov"
        return "mp4"

    def _default_content_type(self, media_type: MediaType) -> str:
        if media_type == MediaType.photo:
            return PHOTO_MIME_TYPE
        return "video/mp4"

    def _upload_content_type(
        self,
        *,
        media: Media,
        downloaded_content_type: str | None,
    ) -> str:
        if media.type == MediaType.photo:
            return PHOTO_MIME_TYPE

        if media.mime_type:
            return media.mime_type
        if (
            downloaded_content_type
            and downloaded_content_type.lower() != GENERIC_BINARY_MIME_TYPE
        ):
            return downloaded_content_type
        return self._default_content_type(media.type)

    def _safe_storage_part(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", value)

    def _refresh_default_seo(
        self,
        post: Post,
        old_text: str,
        old_post_type: PostType,
    ) -> None:
        old_seo = build_default_seo(
            telegram_chat_id=post.telegram_chat_id,
            telegram_post_id=post.telegram_post_id,
            text=old_text,
            post_type=old_post_type,
        )
        new_seo = build_default_seo(
            telegram_chat_id=post.telegram_chat_id,
            telegram_post_id=post.telegram_post_id,
            text=post.text,
            post_type=post.post_type,
        )
        if post.title in {None, "", old_seo.title}:
            post.title = new_seo.title
        if post.meta_description in {None, "", old_seo.meta_description}:
            post.meta_description = new_seo.meta_description
        if post.image_alt_text in {None, "", old_seo.image_alt_text}:
            post.image_alt_text = new_seo.image_alt_text

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
