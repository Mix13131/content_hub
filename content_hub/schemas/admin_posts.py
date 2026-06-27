from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from content_hub.enums import (
    ContentSource,
    MediaType,
    PlatformStatus,
    PostStatus,
    PostType,
    PublicationPlatform,
)
from content_hub.schemas.admin_jobs import AdminJobLogResponse, AdminJobResponse


class AdminMediaResponse(BaseModel):
    id: uuid.UUID
    post_id: uuid.UUID
    type: MediaType
    file_url: str | None
    storage_key: str | None
    telegram_file_id: str
    telegram_file_unique_id: str | None
    sort_order: int
    mime_type: str | None
    size_bytes: int | None
    width: int | None
    height: int | None
    duration_seconds: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminPostSummaryResponse(BaseModel):
    id: uuid.UUID
    telegram_chat_id: int
    telegram_post_id: int
    telegram_media_group_id: str | None
    telegram_url: str | None
    text_preview: str
    author: str | None
    telegram_posted_at: datetime
    post_type: PostType
    photo_count: int
    video_count: int
    is_public: bool
    source: ContentSource
    status: PostStatus
    website_status: PlatformStatus
    instagram_status: PlatformStatus
    facebook_status: PlatformStatus
    vk_status: PlatformStatus
    story_status: PlatformStatus | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminPostDetailResponse(AdminPostSummaryResponse):
    telegram_message_ids: list[int]
    text: str
    media: list[AdminMediaResponse]
    jobs: list[AdminJobResponse]
    logs: list[AdminJobLogResponse]


class AdminPostRetryResponse(BaseModel):
    post: AdminPostDetailResponse
    retried_count: int
    retried_platforms: list[PublicationPlatform]
