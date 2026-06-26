from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from content_hub.enums import PlatformStatus, PublicationPlatform
from content_hub.models.base import Base
from content_hub.models.post import utc_now
from content_hub.models.types import JSONB, enum_values


class PublicationJob(Base):
    __tablename__ = "publication_jobs"
    __table_args__ = (
        UniqueConstraint(
            "post_id",
            "platform",
            name="uq_publication_jobs_post_platform",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    post_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[PublicationPlatform] = mapped_column(
        Enum(
            PublicationPlatform,
            name="publication_platform",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        index=True,
    )
    status: Mapped[PlatformStatus] = mapped_column(
        Enum(
            PlatformStatus,
            name="platform_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=PlatformStatus.Waiting,
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
