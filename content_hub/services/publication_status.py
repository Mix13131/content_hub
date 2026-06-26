from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from content_hub.enums import (
    PlatformStatus,
    PostStatus,
    PublicationLogLevel,
    PublicationPlatform,
)
from content_hub.models import Post, PublicationJob, PublicationLog
from content_hub.models.post import utc_now


RETRY_DELAYS: tuple[timedelta, ...] = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=3),
)

PLATFORM_STATUS_FIELDS: dict[PublicationPlatform, str] = {
    PublicationPlatform.website: "website_status",
    PublicationPlatform.instagram: "instagram_status",
    PublicationPlatform.vk: "vk_status",
    PublicationPlatform.facebook: "facebook_status",
}


class PublicationStatusError(RuntimeError):
    """Raised when a publication job status transition is not allowed."""


class PublicationStatusService:
    def start_job(self, job_id: object, db: Session) -> PublicationJob:
        job = self._get_job(job_id, db)
        if job.status == PlatformStatus.Success:
            raise PublicationStatusError("Cannot start a successful publication job")
        if job.status == PlatformStatus.Publishing:
            raise PublicationStatusError("Publication job is already publishing")

        now = utc_now()
        job.status = PlatformStatus.Publishing
        job.started_at = now
        job.finished_at = None
        job.next_retry_at = None
        job.attempt_count += 1
        self._log(
            db,
            job,
            event="job_started",
            level=PublicationLogLevel.info,
            message=f"Publication job started for {job.platform.value}",
        )
        self._flush_and_refresh_post(job, db)
        return job

    def mark_success(
        self,
        job_id: object,
        db: Session,
        external_post_id: str | None = None,
        external_url: str | None = None,
        raw_response: dict[str, Any] | None = None,
    ) -> PublicationJob:
        job = self._get_job(job_id, db)
        job.status = PlatformStatus.Success
        job.finished_at = utc_now()
        job.next_retry_at = None
        if external_post_id is not None:
            job.external_post_id = external_post_id
        if external_url is not None:
            job.external_url = external_url
        if raw_response is not None:
            job.last_api_response = raw_response
        job.last_error_code = None
        job.last_error_message = None
        self._log(
            db,
            job,
            event="job_succeeded",
            level=PublicationLogLevel.info,
            message=f"Publication job succeeded for {job.platform.value}",
            api_response=raw_response,
        )
        self._flush_and_refresh_post(job, db)
        return job

    def mark_error(
        self,
        job_id: object,
        db: Session,
        error_code: str | None = None,
        error_message: str | None = None,
        raw_response: dict[str, Any] | None = None,
    ) -> PublicationJob:
        job = self._get_job(job_id, db)
        self._mark_error(
            job,
            db,
            event="job_failed",
            error_code=error_code,
            error_message=error_message,
            raw_response=raw_response,
        )
        self._flush_and_refresh_post(job, db)
        return job

    def schedule_retry(
        self,
        job_id: object,
        db: Session,
        error_code: str | None = None,
        error_message: str | None = None,
        raw_response: dict[str, Any] | None = None,
    ) -> PublicationJob:
        job = self._get_job(job_id, db)
        if job.attempt_count >= job.max_attempts:
            self._mark_error(
                job,
                db,
                event="job_retry_exhausted",
                error_code=error_code,
                error_message=error_message,
                raw_response=raw_response,
            )
            self._flush_and_refresh_post(job, db)
            return job

        now = utc_now()
        job.status = PlatformStatus.Retry
        job.finished_at = now
        job.next_retry_at = now + self._retry_delay(job.attempt_count)
        job.last_error_code = error_code
        job.last_error_message = error_message
        if raw_response is not None:
            job.last_api_response = raw_response
        self._log(
            db,
            job,
            event="job_retry_scheduled",
            level=PublicationLogLevel.warning,
            message=f"Publication job retry scheduled for {job.platform.value}",
            error_text=error_message,
            api_response=raw_response,
        )
        self._flush_and_refresh_post(job, db)
        return job

    def manual_retry(self, job_id: object, db: Session) -> PublicationJob:
        job = self._get_job(job_id, db)
        if job.status not in {PlatformStatus.Error, PlatformStatus.Retry}:
            raise PublicationStatusError(
                "Manual retry is allowed only for Error or Retry jobs"
            )

        job.status = PlatformStatus.Waiting
        job.next_retry_at = None
        job.last_error_code = None
        job.last_error_message = None
        self._log(
            db,
            job,
            event="job_manual_retry",
            level=PublicationLogLevel.info,
            message=f"Publication job returned to waiting for {job.platform.value}",
        )
        self._flush_and_refresh_post(job, db)
        return job

    def refresh_post_status(self, post_id: object, db: Session) -> Post | None:
        post = db.get(Post, post_id)
        if post is None:
            return None

        jobs = db.scalars(
            select(PublicationJob).where(PublicationJob.post_id == post.id)
        ).all()
        if not jobs:
            return post

        for job in jobs:
            field_name = PLATFORM_STATUS_FIELDS.get(job.platform)
            if field_name is not None:
                setattr(post, field_name, job.status)

        statuses = [job.status for job in jobs]
        if all(status == PlatformStatus.Success for status in statuses):
            post.status = PostStatus.published
        elif all(status == PlatformStatus.Error for status in statuses):
            post.status = PostStatus.error
        elif all(status == PlatformStatus.Waiting for status in statuses):
            post.status = PostStatus.queued
        elif any(status == PlatformStatus.Success for status in statuses):
            post.status = PostStatus.partially_published
        else:
            post.status = PostStatus.queued

        db.flush()
        return post

    def _get_job(self, job_id: object, db: Session) -> PublicationJob:
        job = db.get(PublicationJob, job_id)
        if job is None:
            raise PublicationStatusError("Publication job not found")
        return job

    def _mark_error(
        self,
        job: PublicationJob,
        db: Session,
        event: str,
        error_code: str | None,
        error_message: str | None,
        raw_response: dict[str, Any] | None,
    ) -> None:
        job.status = PlatformStatus.Error
        job.finished_at = utc_now()
        job.next_retry_at = None
        job.last_error_code = error_code
        job.last_error_message = error_message
        if raw_response is not None:
            job.last_api_response = raw_response
        self._log(
            db,
            job,
            event=event,
            level=PublicationLogLevel.error,
            message=f"Publication job failed for {job.platform.value}",
            error_text=error_message,
            api_response=raw_response,
        )

    def _retry_delay(self, attempt_count: int) -> timedelta:
        index = max(0, min(attempt_count - 1, len(RETRY_DELAYS) - 1))
        return RETRY_DELAYS[index]

    def _flush_and_refresh_post(self, job: PublicationJob, db: Session) -> None:
        db.flush()
        self.refresh_post_status(job.post_id, db)

    def _log(
        self,
        db: Session,
        job: PublicationJob,
        event: str,
        level: PublicationLogLevel,
        message: str,
        error_text: str | None = None,
        api_response: dict[str, Any] | None = None,
    ) -> None:
        db.add(
            PublicationLog(
                post_id=job.post_id,
                job_id=job.id,
                service="queue",
                level=level,
                event=event,
                message=message,
                error_text=error_text,
                api_response=api_response,
            )
        )
