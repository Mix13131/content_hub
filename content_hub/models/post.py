from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Enum, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from content_hub.models.base import Base
from content_hub.models.types import JSONB


POST_TYPE_VALUES = ("text", "photo", "video", "carousel", "mixed")
POST_SOURCE_VALUES = ("telegram_channel",)
POST_STATUS_VALUES = (
    "received",
    "saving_media",
    "saved",
    "queued",
    "partially_published",
    "published",
    "error",
)
PLATFORM_STATUS_VALUES = ("Waiting", "Publishing", "Success", "Error", "Retry")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint(
            "telegram_chat_id",
            "telegram_post_id",
            name="uq_posts_telegram_chat_post",
        ),
        UniqueConstraint(
            "telegram_chat_id",
            "telegram_media_group_id",
            name="uq_posts_telegram_media_group",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_post_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_media_group_id: Mapped[str | None] = mapped_column(String(255))
    telegram_message_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    telegram_url: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author: Mapped[str | None] = mapped_column(String(255))
    telegram_posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    post_type: Mapped[str] = mapped_column(
        Enum(*POST_TYPE_VALUES, name="post_type", native_enum=False),
        nullable=False,
        default="text",
    )
    photo_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(
        Enum(*POST_SOURCE_VALUES, name="post_source", native_enum=False),
        nullable=False,
        default="telegram_channel",
    )
    status: Mapped[str] = mapped_column(
        Enum(*POST_STATUS_VALUES, name="post_status", native_enum=False),
        nullable=False,
        default="saved",
    )
    website_status: Mapped[str] = mapped_column(
        Enum(*PLATFORM_STATUS_VALUES, name="platform_status", native_enum=False),
        nullable=False,
        default="Waiting",
    )
    instagram_status: Mapped[str] = mapped_column(
        Enum(*PLATFORM_STATUS_VALUES, name="platform_status", native_enum=False),
        nullable=False,
        default="Waiting",
    )
    facebook_status: Mapped[str] = mapped_column(
        Enum(*PLATFORM_STATUS_VALUES, name="platform_status", native_enum=False),
        nullable=False,
        default="Waiting",
    )
    vk_status: Mapped[str] = mapped_column(
        Enum(*PLATFORM_STATUS_VALUES, name="platform_status", native_enum=False),
        nullable=False,
        default="Waiting",
    )
    story_status: Mapped[str | None] = mapped_column(
        Enum(*PLATFORM_STATUS_VALUES, name="platform_status", native_enum=False)
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    media: Mapped[list["Media"]] = relationship(back_populates="post")
    publication_jobs: Mapped[list["PublicationJob"]] = relationship(back_populates="post")
    publication_logs: Mapped[list["PublicationLog"]] = relationship(back_populates="post")
