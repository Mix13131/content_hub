from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from content_hub.models.base import Base
from content_hub.models.post import utc_now
from content_hub.models.types import JSONB


LOG_LEVEL_VALUES = ("info", "warning", "error")


class PublicationLog(Base):
    __tablename__ = "publication_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("publication_jobs.id", ondelete="CASCADE"), index=True
    )
    service: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    level: Mapped[str] = mapped_column(
        Enum(*LOG_LEVEL_VALUES, name="publication_log_level", native_enum=False),
        nullable=False,
        default="info",
    )
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    error_text: Mapped[str | None] = mapped_column(Text)
    api_response: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    post: Mapped["Post | None"] = relationship(back_populates="publication_logs")
    job: Mapped["PublicationJob | None"] = relationship(back_populates="logs")
