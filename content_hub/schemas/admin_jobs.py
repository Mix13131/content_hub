from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from content_hub.enums import (
    PlatformStatus,
    PublicationLogLevel,
    PublicationPlatform,
)


class AdminJobResponse(BaseModel):
    id: uuid.UUID
    post_id: uuid.UUID
    platform: PublicationPlatform
    status: PlatformStatus
    attempt_count: int
    max_attempts: int
    next_retry_at: datetime | None
    external_post_id: str | None
    external_url: str | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class AdminJobLogResponse(BaseModel):
    id: uuid.UUID
    post_id: uuid.UUID | None
    job_id: uuid.UUID | None
    service: str
    level: PublicationLogLevel
    event: str
    message: str
    error_text: str | None
    api_response: dict[str, Any] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminJobDetailResponse(AdminJobResponse):
    logs: list[AdminJobLogResponse]


class AdminJobSuccessRequest(BaseModel):
    external_post_id: str | None = None
    external_url: str | None = None
    raw_response: dict[str, Any] | None = None


class AdminJobErrorRequest(BaseModel):
    error_code: str | None = None
    error_message: str | None = None
    raw_response: dict[str, Any] | None = None
