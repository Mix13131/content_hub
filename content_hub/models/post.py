from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from content_hub.enums import ContentSource, PlatformStatus, PostStatus, PostType
from content_hub.models.base import Base
from content_hub.models.types import JSONB, enum_values


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
        Index("ix_posts_slug_unique", "slug", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_post_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_media_group_id: Mapped[str | None] = mapped_column(String(255))
    telegram_message_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    telegram_url: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author: Mapped[str | None] = mapped_column(String(255))
    slug: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    meta_description: Mapped[str | None] = mapped_column(String(300))
    image_alt_text: Mapped[str | None] = mapped_column(String(255))
    telegram_posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    post_type: Mapped[PostType] = mapped_column(
        Enum(PostType, name="post_type", native_enum=False, values_callable=enum_values),
        nullable=False,
        default=PostType.text,
    )
    photo_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[ContentSource] = mapped_column(
        Enum(
            ContentSource,
            name="post_source",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=ContentSource.telegram_channel,
    )
    status: Mapped[PostStatus] = mapped_column(
        Enum(
            PostStatus,
            name="post_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=PostStatus.saved,
    )
    website_status: Mapped[PlatformStatus] = mapped_column(
        Enum(
            PlatformStatus,
            name="platform_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=PlatformStatus.Waiting,
    )
    instagram_status: Mapped[PlatformStatus] = mapped_column(
        Enum(
            PlatformStatus,
            name="platform_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=PlatformStatus.Waiting,
    )
    facebook_status: Mapped[PlatformStatus] = mapped_column(
        Enum(
            PlatformStatus,
            name="platform_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=PlatformStatus.Waiting,
    )
    vk_status: Mapped[PlatformStatus] = mapped_column(
        Enum(
            PlatformStatus,
            name="platform_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=PlatformStatus.Waiting,
    )
    story_status: Mapped[PlatformStatus | None] = mapped_column(
        Enum(
            PlatformStatus,
            name="platform_status",
            native_enum=False,
            values_callable=enum_values,
        )
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
