from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from content_hub.enums import MediaType, PostType


class PublicPostListMediaResponse(BaseModel):
    type: MediaType
    width: int | None
    height: int | None
    duration_seconds: int | None
    sort_order: int


class PublicPostDetailMediaResponse(BaseModel):
    type: MediaType
    sort_order: int
    mime_type: str | None
    size_bytes: int | None
    width: int | None
    height: int | None
    duration_seconds: int | None
    file_url: str | None


class PublicPostSummaryResponse(BaseModel):
    id: uuid.UUID
    telegram_url: str | None
    text_preview: str
    author: str | None
    telegram_posted_at: datetime
    post_type: PostType
    photo_count: int
    video_count: int
    created_at: datetime
    media_count: int
    has_photo: bool
    has_video: bool
    media: list[PublicPostListMediaResponse]


class PublicPostDetailResponse(BaseModel):
    id: uuid.UUID
    telegram_url: str | None
    text: str
    author: str | None
    telegram_posted_at: datetime
    post_type: PostType
    photo_count: int
    video_count: int
    created_at: datetime
    media: list[PublicPostDetailMediaResponse]
