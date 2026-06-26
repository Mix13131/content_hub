import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from content_hub.enums import (
    PlatformStatus,
    PostStatus,
    PublicationLogLevel,
    PublicationPlatform,
)
from content_hub.models import Post, PublicationJob, PublicationLog
from content_hub.services.publication_status import (
    PublicationStatusError,
    PublicationStatusService,
)
from content_hub.services.telegram_ingestion import TelegramIngestionService


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def create_post_with_jobs(db_session: Session) -> tuple[Post, dict[PublicationPlatform, PublicationJob]]:
    result = TelegramIngestionService().ingest_update(
        load_fixture("telegram_text_channel_post.json"),
        db_session,
    )
    assert result.post_id is not None
    post = db_session.get(Post, uuid.UUID(result.post_id))
    assert post is not None
    jobs = db_session.scalars(
        select(PublicationJob).where(PublicationJob.post_id == post.id)
    ).all()
    assert len(jobs) == 4
    return post, {job.platform: job for job in jobs}


def latest_log(db_session: Session, event: str) -> PublicationLog:
    log = db_session.scalar(
        select(PublicationLog)
        .where(PublicationLog.event == event)
        .order_by(PublicationLog.created_at.desc())
    )
    assert log is not None
    return log


def test_start_job_marks_publishing_increments_attempt_and_logs(
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.website]

    PublicationStatusService().start_job(job.id, db_session)

    assert job.status == PlatformStatus.Publishing
    assert job.attempt_count == 1
    assert job.started_at is not None
    assert job.finished_at is None
    log = latest_log(db_session, "job_started")
    assert log.job_id == job.id
    assert log.service == "queue"
    assert log.level == PublicationLogLevel.info


def test_start_job_rejects_success_and_publishing_jobs(db_session: Session) -> None:
    _, jobs = create_post_with_jobs(db_session)
    service = PublicationStatusService()
    job = jobs[PublicationPlatform.website]

    service.start_job(job.id, db_session)
    with pytest.raises(PublicationStatusError):
        service.start_job(job.id, db_session)

    job.status = PlatformStatus.Success
    db_session.flush()
    with pytest.raises(PublicationStatusError):
        service.start_job(job.id, db_session)


def test_mark_success_saves_external_fields_clears_errors_and_logs(
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    service = PublicationStatusService()
    job = jobs[PublicationPlatform.instagram]
    service.start_job(job.id, db_session)
    job.last_error_code = "old_error"
    job.last_error_message = "old message"

    service.mark_success(
        job.id,
        db_session,
        external_post_id="ig_123",
        external_url="https://instagram.example/p/ig_123",
        raw_response={"ok": True},
    )

    assert job.status == PlatformStatus.Success
    assert job.finished_at is not None
    assert job.external_post_id == "ig_123"
    assert job.external_url == "https://instagram.example/p/ig_123"
    assert job.last_api_response == {"ok": True}
    assert job.last_error_code is None
    assert job.last_error_message is None
    log = latest_log(db_session, "job_succeeded")
    assert log.job_id == job.id
    assert log.level == PublicationLogLevel.info


def test_mark_error_saves_error_fields_and_logs(db_session: Session) -> None:
    _, jobs = create_post_with_jobs(db_session)
    service = PublicationStatusService()
    job = jobs[PublicationPlatform.vk]
    service.start_job(job.id, db_session)

    service.mark_error(
        job.id,
        db_session,
        error_code="VK_AUTH",
        error_message="VK token expired",
        raw_response={"error": "expired"},
    )

    assert job.status == PlatformStatus.Error
    assert job.finished_at is not None
    assert job.last_error_code == "VK_AUTH"
    assert job.last_error_message == "VK token expired"
    assert job.last_api_response == {"error": "expired"}
    log = latest_log(db_session, "job_failed")
    assert log.job_id == job.id
    assert log.level == PublicationLogLevel.error
    assert log.error_text == "VK token expired"


def test_schedule_retry_sets_retry_timestamp_and_logs(db_session: Session) -> None:
    _, jobs = create_post_with_jobs(db_session)
    service = PublicationStatusService()
    job = jobs[PublicationPlatform.website]
    service.start_job(job.id, db_session)

    service.schedule_retry(
        job.id,
        db_session,
        error_code="TIMEOUT",
        error_message="Temporary timeout",
        raw_response={"retryable": True},
    )

    assert job.status == PlatformStatus.Retry
    assert job.finished_at is not None
    assert job.next_retry_at is not None
    assert (job.next_retry_at - job.finished_at).total_seconds() == 60
    assert job.last_error_code == "TIMEOUT"
    assert job.last_error_message == "Temporary timeout"
    log = latest_log(db_session, "job_retry_scheduled")
    assert log.job_id == job.id
    assert log.level == PublicationLogLevel.warning


def test_schedule_retry_marks_error_when_attempts_are_exhausted(
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.website]
    job.attempt_count = job.max_attempts
    db_session.flush()

    PublicationStatusService().schedule_retry(
        job.id,
        db_session,
        error_code="LIMIT",
        error_message="Attempts exhausted",
    )

    assert job.status == PlatformStatus.Error
    assert job.next_retry_at is None
    assert job.last_error_code == "LIMIT"
    assert job.last_error_message == "Attempts exhausted"
    log = latest_log(db_session, "job_retry_exhausted")
    assert log.job_id == job.id
    assert log.level == PublicationLogLevel.error


def test_manual_retry_returns_error_or_retry_job_to_waiting_without_resetting_attempts(
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    service = PublicationStatusService()
    job = jobs[PublicationPlatform.facebook]
    service.start_job(job.id, db_session)
    service.schedule_retry(
        job.id,
        db_session,
        error_code="RATE_LIMIT",
        error_message="Rate limited",
    )
    attempts = job.attempt_count

    service.manual_retry(job.id, db_session)

    assert job.status == PlatformStatus.Waiting
    assert job.attempt_count == attempts
    assert job.next_retry_at is None
    assert job.last_error_code is None
    assert job.last_error_message is None
    log = latest_log(db_session, "job_manual_retry")
    assert log.job_id == job.id
    assert log.level == PublicationLogLevel.info


def test_manual_retry_rejects_non_retryable_status(db_session: Session) -> None:
    _, jobs = create_post_with_jobs(db_session)

    with pytest.raises(PublicationStatusError):
        PublicationStatusService().manual_retry(
            jobs[PublicationPlatform.website].id,
            db_session,
        )


def test_refresh_post_status_for_waiting_success_partial_and_error(
    db_session: Session,
) -> None:
    post, jobs = create_post_with_jobs(db_session)
    service = PublicationStatusService()

    service.refresh_post_status(post.id, db_session)
    assert post.status == PostStatus.queued

    service.mark_success(jobs[PublicationPlatform.website].id, db_session)
    service.mark_error(jobs[PublicationPlatform.instagram].id, db_session)
    assert post.status == PostStatus.partially_published

    for platform in (PublicationPlatform.vk, PublicationPlatform.facebook):
        service.mark_success(jobs[platform].id, db_session)
    assert post.status == PostStatus.partially_published

    service.mark_success(jobs[PublicationPlatform.instagram].id, db_session)
    assert post.status == PostStatus.published

    for job in jobs.values():
        service.mark_error(job.id, db_session)
    assert post.status == PostStatus.error


def test_refresh_post_status_updates_platform_fields(db_session: Session) -> None:
    post, jobs = create_post_with_jobs(db_session)
    service = PublicationStatusService()

    service.start_job(jobs[PublicationPlatform.website].id, db_session)
    service.mark_success(jobs[PublicationPlatform.instagram].id, db_session)
    service.mark_error(jobs[PublicationPlatform.vk].id, db_session)
    service.start_job(jobs[PublicationPlatform.facebook].id, db_session)
    service.schedule_retry(jobs[PublicationPlatform.facebook].id, db_session)

    assert post.website_status == PlatformStatus.Publishing
    assert post.instagram_status == PlatformStatus.Success
    assert post.vk_status == PlatformStatus.Error
    assert post.facebook_status == PlatformStatus.Retry
    assert post.status == PostStatus.partially_published
