from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from content_hub.admin.auth import verify_admin_token
from content_hub.db import get_db
from content_hub.enums import (
    PlatformStatus,
    PostStatus,
    PostType,
    PublicationLogLevel,
    PublicationPlatform,
)
from content_hub.models import Post, PublicationJob, PublicationLog
from content_hub.schemas.admin_jobs import AdminJobLogResponse, AdminJobResponse
from content_hub.schemas.admin_posts import (
    AdminMediaResponse,
    AdminPostDetailResponse,
    AdminPostRetryResponse,
    AdminPostSeoUpdateRequest,
    AdminPostSummaryResponse,
)
from content_hub.services.seo import normalize_slug
from content_hub.services.publication_status import (
    PublicationStatusError,
    PublicationStatusService,
)


router = APIRouter(
    prefix="/admin/posts",
    tags=["admin-posts"],
    dependencies=[Depends(verify_admin_token)],
)


@router.get("", response_model=list[AdminPostSummaryResponse])
def list_posts(
    db: Annotated[Session, Depends(get_db)],
    status: PostStatus | None = None,
    post_type: PostType | None = None,
    platform: PublicationPlatform | None = None,
    platform_status: PlatformStatus | None = None,
    is_public: bool | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AdminPostSummaryResponse]:
    statement = select(Post).order_by(
        Post.telegram_posted_at.desc(),
        Post.created_at.desc(),
    )
    if platform is not None or platform_status is not None:
        statement = statement.join(PublicationJob, PublicationJob.post_id == Post.id)
    if status is not None:
        statement = statement.where(Post.status == status)
    if post_type is not None:
        statement = statement.where(Post.post_type == post_type)
    if platform is not None:
        statement = statement.where(PublicationJob.platform == platform)
    if platform_status is not None:
        statement = statement.where(PublicationJob.status == platform_status)
    if is_public is not None:
        statement = statement.where(Post.is_public.is_(is_public))
    if date_from is not None:
        statement = statement.where(Post.telegram_posted_at >= date_from)
    if date_to is not None:
        statement = statement.where(Post.telegram_posted_at <= date_to)

    posts = db.scalars(statement.distinct().limit(limit)).all()
    return [_build_post_summary(post) for post in posts]


@router.get("/{post_id}", response_model=AdminPostDetailResponse)
def get_post_detail(
    post_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> AdminPostDetailResponse:
    return _build_post_detail_response(post_id, db)


@router.post("/{post_id}/publish", response_model=AdminPostDetailResponse)
def publish_post(
    post_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> AdminPostDetailResponse:
    return _set_post_public_visibility(
        post_id=post_id,
        db=db,
        is_public=True,
        event="post_published_publicly",
        message="Post made public",
    )


@router.post("/{post_id}/unpublish", response_model=AdminPostDetailResponse)
def unpublish_post(
    post_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> AdminPostDetailResponse:
    return _set_post_public_visibility(
        post_id=post_id,
        db=db,
        is_public=False,
        event="post_unpublished_publicly",
        message="Post hidden from public API",
    )


@router.patch("/{post_id}/seo", response_model=AdminPostDetailResponse)
def update_post_seo(
    post_id: uuid.UUID,
    payload: AdminPostSeoUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AdminPostDetailResponse:
    post = _get_post_or_404(post_id, db)

    if "slug" in payload.model_fields_set:
        post.slug = _normalize_requested_slug(payload.slug, post.id, db)
    if "title" in payload.model_fields_set:
        post.title = payload.title
    if "meta_description" in payload.model_fields_set:
        post.meta_description = payload.meta_description
    if "image_alt_text" in payload.model_fields_set:
        post.image_alt_text = payload.image_alt_text

    db.add(
        PublicationLog(
            post_id=post.id,
            service="admin",
            level=PublicationLogLevel.info,
            event="post_seo_updated",
            message="Post SEO fields updated",
        )
    )
    db.commit()
    return _build_post_detail_response(post_id, db)


@router.post("/{post_id}/retry/{platform}", response_model=AdminPostRetryResponse)
def retry_post_platform(
    post_id: uuid.UUID,
    platform: PublicationPlatform,
    db: Annotated[Session, Depends(get_db)],
) -> AdminPostRetryResponse:
    _get_post_or_404(post_id, db)
    job = _get_job_or_404(post_id, platform, db)
    try:
        PublicationStatusService().manual_retry(job.id, db)
    except PublicationStatusError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    return AdminPostRetryResponse(
        post=_build_post_detail_response(post_id, db),
        retried_count=1,
        retried_platforms=[platform],
    )


@router.post("/{post_id}/retry-failed", response_model=AdminPostRetryResponse)
def retry_failed_post_jobs(
    post_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> AdminPostRetryResponse:
    _get_post_or_404(post_id, db)
    jobs = db.scalars(
        select(PublicationJob)
        .where(PublicationJob.post_id == post_id)
        .where(PublicationJob.status.in_([PlatformStatus.Error, PlatformStatus.Retry]))
        .order_by(PublicationJob.platform)
    ).all()

    retried_platforms: list[PublicationPlatform] = []
    service = PublicationStatusService()
    for job in jobs:
        service.manual_retry(job.id, db)
        retried_platforms.append(job.platform)

    db.commit()
    return AdminPostRetryResponse(
        post=_build_post_detail_response(post_id, db),
        retried_count=len(retried_platforms),
        retried_platforms=retried_platforms,
    )


def _get_post_or_404(post_id: uuid.UUID, db: Session) -> Post:
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


def _get_job_or_404(
    post_id: uuid.UUID,
    platform: PublicationPlatform,
    db: Session,
) -> PublicationJob:
    job = db.scalar(
        select(PublicationJob).where(
            PublicationJob.post_id == post_id,
            PublicationJob.platform == platform,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Publication job not found")
    return job


def _set_post_public_visibility(
    post_id: uuid.UUID,
    db: Session,
    is_public: bool,
    event: str,
    message: str,
) -> AdminPostDetailResponse:
    post = _get_post_or_404(post_id, db)
    post.is_public = is_public
    db.add(
        PublicationLog(
            post_id=post.id,
            service="admin",
            level=PublicationLogLevel.info,
            event=event,
            message=message,
        )
    )
    db.commit()
    return _build_post_detail_response(post_id, db)


def _normalize_requested_slug(
    slug: str | None,
    post_id: uuid.UUID,
    db: Session,
) -> str | None:
    if slug is None:
        return None

    normalized_slug = normalize_slug(slug)
    if not normalized_slug:
        raise HTTPException(status_code=422, detail="Slug cannot be empty")

    existing_post = db.scalar(
        select(Post).where(
            Post.slug == normalized_slug,
            Post.id != post_id,
        )
    )
    if existing_post is not None:
        raise HTTPException(status_code=409, detail="Slug is already used")
    return normalized_slug


def _build_post_detail_response(
    post_id: uuid.UUID,
    db: Session,
) -> AdminPostDetailResponse:
    post = db.scalar(
        select(Post)
        .where(Post.id == post_id)
        .options(
            selectinload(Post.media),
            selectinload(Post.publication_jobs),
        )
    )
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    logs = db.scalars(
        select(PublicationLog)
        .where(PublicationLog.post_id == post.id)
        .order_by(PublicationLog.created_at.desc())
        .limit(20)
    ).all()
    summary = _build_post_summary(post).model_dump()
    return AdminPostDetailResponse(
        **summary,
        telegram_message_ids=post.telegram_message_ids,
        text=post.text,
        media=[
            AdminMediaResponse.model_validate(media)
            for media in sorted(post.media, key=lambda media: media.sort_order)
        ],
        jobs=[
            AdminJobResponse.model_validate(job)
            for job in sorted(post.publication_jobs, key=lambda job: job.platform.value)
        ],
        logs=[AdminJobLogResponse.model_validate(log) for log in logs],
    )


def _build_post_summary(post: Post) -> AdminPostSummaryResponse:
    return AdminPostSummaryResponse(
        id=post.id,
        telegram_chat_id=post.telegram_chat_id,
        telegram_post_id=post.telegram_post_id,
        telegram_media_group_id=post.telegram_media_group_id,
        telegram_url=post.telegram_url,
        text_preview=_preview(post.text),
        author=post.author,
        slug=post.slug,
        title=post.title,
        meta_description=post.meta_description,
        image_alt_text=post.image_alt_text,
        telegram_posted_at=post.telegram_posted_at,
        post_type=post.post_type,
        photo_count=post.photo_count,
        video_count=post.video_count,
        is_public=post.is_public,
        source=post.source,
        status=post.status,
        website_status=post.website_status,
        instagram_status=post.instagram_status,
        facebook_status=post.facebook_status,
        vk_status=post.vk_status,
        story_status=post.story_status,
        published_at=post.published_at,
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


def _preview(text: str, limit: int = 120) -> str:
    compact_text = " ".join(text.split())
    if len(compact_text) <= limit:
        return compact_text
    return f"{compact_text[: limit - 1]}..."
