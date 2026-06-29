import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from content_hub.connectors.base import (
    ConnectorCapabilities,
    ConnectorResult,
)
from content_hub.connectors.engine import ConnectorEngine
from content_hub.connectors.registry import ConnectorNotFound, ConnectorRegistry
from content_hub.connectors.website import WebsiteConnector
from content_hub.enums import (
    PlatformStatus,
    PostStatus,
    PublicationLogLevel,
    PublicationPlatform,
)
from content_hub.models import Media, Post, PublicationJob, PublicationLog
from content_hub.services.telegram_ingestion import TelegramIngestionService


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@dataclass
class DummyConnector:
    name: str = "dummy"

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            can_publish=True,
            can_update=False,
            can_delete=False,
            supports_media=False,
            supports_albums=False,
            supports_video=False,
        )

    def validate(self, post: Post, media: list[Media]) -> ConnectorResult:
        return ConnectorResult(success=True)

    def publish(self, post: Post, media: list[Media]) -> ConnectorResult:
        return ConnectorResult(
            success=True,
            external_post_id="dummy-id",
            external_url="/dummy",
            raw_response={"connector": self.name},
        )

    def update(self, post: Post, media: list[Media]) -> ConnectorResult:
        return ConnectorResult(success=False)

    def delete(self, external_post_id: str) -> ConnectorResult:
        return ConnectorResult(success=False)


def create_post_with_jobs(
    db_session: Session,
) -> tuple[Post, dict[PublicationPlatform, PublicationJob]]:
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


def logs_for_job(db_session: Session, job: PublicationJob) -> list[PublicationLog]:
    return db_session.scalars(
        select(PublicationLog)
        .where(PublicationLog.job_id == job.id)
        .order_by(PublicationLog.created_at)
    ).all()


def test_connector_registry_registers_and_returns_connector() -> None:
    registry = ConnectorRegistry()
    connector = DummyConnector()

    registry.register(connector)

    assert registry.get("dummy") is connector


def test_connector_registry_unknown_connector_raises() -> None:
    registry = ConnectorRegistry()

    with pytest.raises(ConnectorNotFound):
        registry.get("missing")


def test_website_connector_capabilities() -> None:
    capabilities = WebsiteConnector().capabilities()

    assert capabilities.can_publish is True
    assert capabilities.can_update is False
    assert capabilities.can_delete is False
    assert capabilities.supports_media is True
    assert capabilities.supports_albums is True
    assert capabilities.supports_video is True


def test_website_connector_publish_returns_dry_run_url(
    db_session: Session,
) -> None:
    post, _ = create_post_with_jobs(db_session)

    result = WebsiteConnector().publish(post, [])

    assert result.success is True
    assert result.external_post_id == str(post.id)
    assert result.external_url == f"/news/{post.slug}"
    assert result.raw_response == {
        "mode": "dry_run",
        "connector": "website",
        "media_count": 0,
    }


def test_connector_engine_publishes_website_job_successfully(
    db_session: Session,
) -> None:
    post, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.website]

    ConnectorEngine().publish_job(job.id, db_session)

    db_session.refresh(job)
    db_session.refresh(post)
    assert job.status == PlatformStatus.Success
    assert job.attempt_count == 1
    assert job.external_post_id == str(post.id)
    assert job.external_url == f"/news/{post.slug}"
    assert job.last_api_response == {
        "mode": "dry_run",
        "connector": "website",
        "media_count": 0,
    }
    assert post.website_status == PlatformStatus.Success
    assert post.status == PostStatus.partially_published

    logs = logs_for_job(db_session, job)
    assert [log.event for log in logs] == ["job_started", "job_succeeded"]
    assert logs[0].level == PublicationLogLevel.info
    assert logs[1].level == PublicationLogLevel.info


def test_connector_engine_unknown_connector_is_controlled_retry(
    db_session: Session,
) -> None:
    post, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.instagram]

    ConnectorEngine().publish_job(job.id, db_session)

    db_session.refresh(job)
    db_session.refresh(post)
    assert job.status == PlatformStatus.Retry
    assert job.attempt_count == 1
    assert job.next_retry_at is not None
    assert job.last_error_code == "CONNECTOR_NOT_FOUND"
    assert job.last_error_message == "Connector is not registered: instagram"
    assert job.last_api_response == {
        "mode": "dry_run",
        "connector": "instagram",
        "platform": "instagram",
    }
    assert post.instagram_status == PlatformStatus.Retry
    assert post.status == PostStatus.queued

    logs = logs_for_job(db_session, job)
    assert [log.event for log in logs] == ["job_started", "job_retry_scheduled"]
    assert logs[1].level == PublicationLogLevel.warning
