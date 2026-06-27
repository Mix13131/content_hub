from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from content_hub.db import get_db
from content_hub.enums import PostStatus, PostType
from content_hub.models import Media, Post
from content_hub.schemas.public_posts import (
    PublicPostDetailMediaResponse,
    PublicPostDetailResponse,
    PublicPostListMediaResponse,
    PublicPostSummaryResponse,
)


PUBLIC_POST_STATUSES: tuple[PostStatus, ...] = (
    PostStatus.queued,
    PostStatus.partially_published,
    PostStatus.published,
)


router = APIRouter(prefix="/api/posts/public", tags=["public-posts"])


@router.get("", response_model=list[PublicPostSummaryResponse])
def list_public_posts(
    db: Annotated[Session, Depends(get_db)],
    post_type: PostType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[PublicPostSummaryResponse]:
    statement = (
        select(Post)
        .where(Post.status.in_(PUBLIC_POST_STATUSES))
        .options(selectinload(Post.media))
        .order_by(Post.telegram_posted_at.desc(), Post.created_at.desc())
    )
    if post_type is not None:
        statement = statement.where(Post.post_type == post_type)
    if date_from is not None:
        statement = statement.where(Post.telegram_posted_at >= date_from)
    if date_to is not None:
        statement = statement.where(Post.telegram_posted_at <= date_to)

    posts = db.scalars(statement.limit(limit)).all()
    return [_build_post_summary(post) for post in posts]


@router.get("/{post_id}", response_model=PublicPostDetailResponse)
def get_public_post_detail(
    post_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> PublicPostDetailResponse:
    post = db.scalar(
        select(Post)
        .where(Post.id == post_id)
        .where(Post.status.in_(PUBLIC_POST_STATUSES))
        .options(selectinload(Post.media))
    )
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return _build_post_detail(post)


def _build_post_summary(post: Post) -> PublicPostSummaryResponse:
    media = _sorted_media(post)
    return PublicPostSummaryResponse(
        id=post.id,
        telegram_url=post.telegram_url,
        text_preview=_preview(post.text),
        author=post.author,
        telegram_posted_at=post.telegram_posted_at,
        post_type=post.post_type,
        photo_count=post.photo_count,
        video_count=post.video_count,
        created_at=post.created_at,
        media_count=len(media),
        has_photo=post.photo_count > 0,
        has_video=post.video_count > 0,
        media=[_build_list_media_response(item) for item in media],
    )


def _build_post_detail(post: Post) -> PublicPostDetailResponse:
    return PublicPostDetailResponse(
        id=post.id,
        telegram_url=post.telegram_url,
        text=post.text,
        author=post.author,
        telegram_posted_at=post.telegram_posted_at,
        post_type=post.post_type,
        photo_count=post.photo_count,
        video_count=post.video_count,
        created_at=post.created_at,
        media=[
            _build_detail_media_response(item)
            for item in _sorted_media(post)
        ],
    )


def _build_list_media_response(media: Media) -> PublicPostListMediaResponse:
    return PublicPostListMediaResponse(
        type=media.type,
        width=media.width,
        height=media.height,
        duration_seconds=media.duration_seconds,
        sort_order=media.sort_order,
    )


def _build_detail_media_response(media: Media) -> PublicPostDetailMediaResponse:
    return PublicPostDetailMediaResponse(
        type=media.type,
        sort_order=media.sort_order,
        mime_type=media.mime_type,
        size_bytes=media.size_bytes,
        width=media.width,
        height=media.height,
        duration_seconds=media.duration_seconds,
        file_url=media.file_url,
    )


def _sorted_media(post: Post) -> list[Media]:
    return sorted(post.media, key=lambda media: media.sort_order)


def _preview(text: str, limit: int = 120) -> str:
    compact_text = " ".join(text.split())
    if len(compact_text) <= limit:
        return compact_text
    return f"{compact_text[: limit - 1]}..."
