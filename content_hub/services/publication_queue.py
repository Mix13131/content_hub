from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from content_hub.enums import (
    PlatformStatus,
    PostStatus,
    PublicationLogLevel,
    PublicationPlatform,
)
from content_hub.models import Post, PublicationJob, PublicationLog


MVP_PUBLICATION_PLATFORMS: tuple[PublicationPlatform, ...] = (
    PublicationPlatform.website,
    PublicationPlatform.instagram,
    PublicationPlatform.vk,
    PublicationPlatform.facebook,
)


class PublicationQueueService:
    def create_jobs_for_post(self, post: Post, db: Session) -> list[PublicationJob]:
        existing_jobs = db.scalars(
            select(PublicationJob).where(PublicationJob.post_id == post.id)
        ).all()
        existing_platforms = {job.platform for job in existing_jobs}

        created_jobs: list[PublicationJob] = []
        for platform in MVP_PUBLICATION_PLATFORMS:
            if platform in existing_platforms:
                continue
            job = PublicationJob(
                post_id=post.id,
                platform=platform,
                status=PlatformStatus.Waiting,
                attempt_count=0,
                max_attempts=5,
            )
            db.add(job)
            created_jobs.append(job)

        if created_jobs:
            db.flush()
            post.status = PostStatus.queued
            db.add(
                PublicationLog(
                    post_id=post.id,
                    service="queue",
                    level=PublicationLogLevel.info,
                    event="publication_jobs_created",
                    message=f"Created {len(created_jobs)} publication jobs",
                    api_response={
                        "platforms": [job.platform.value for job in created_jobs],
                    },
                )
            )
        elif len(existing_platforms) >= len(MVP_PUBLICATION_PLATFORMS):
            post.status = PostStatus.queued

        return created_jobs
