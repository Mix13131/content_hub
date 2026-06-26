from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from content_hub.models.base import Base
from content_hub.models.post import PLATFORM_STATUS_VALUES, utc_now
from content_hub.models.types import JSONB


PLATFORM_VALUES = (
    "website",
    "instagram",
    "facebook",
    "vk",
    "telegram_story",
    "whatsapp",
)


class PublicationJob(Base):
    __tablename__ = "publication_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    post_id: Mapped[str] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(
        Enum(*PLATFORM_VALUES, name="publication_platform", native_enum=False),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        Enum(*PLATFORM_STATUS_VALUES, name="platform_status", native_enum=False),
        nullable=False,
        default="Waiting",
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_post_id: Mapped[str | None] = mapped_column(Text)
    external_url: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[str | None] = mapped_column(Text)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    last_api_response: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    post: Mapped["Post"] = relationship(back_populates="publication_jobs")
    logs: Mapped[list["PublicationLog"]] = relationship(back_populates="job")
