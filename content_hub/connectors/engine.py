from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from content_hub.connectors.registry import (
    ConnectorNotFound,
    ConnectorRegistry,
    default_connector_registry,
)
from content_hub.enums import PublicationPlatform
from content_hub.models import Media, Post, PublicationJob
from content_hub.models.post import utc_now
from content_hub.services.publication_status import PublicationStatusService


PLATFORM_CONNECTOR_NAMES: dict[PublicationPlatform, str] = {
    PublicationPlatform.website: "website",
    PublicationPlatform.instagram: "instagram",
    PublicationPlatform.vk: "vk",
    PublicationPlatform.facebook: "facebook",
}


class ConnectorEngine:
    def __init__(
        self,
        registry: ConnectorRegistry | None = None,
        status_service: PublicationStatusService | None = None,
    ) -> None:
        self.registry = registry or default_connector_registry()
        self.status_service = status_service or PublicationStatusService()

    def publish_job(self, job_id: object, db: Session) -> PublicationJob:
        job = self._get_job(job_id, db)
        post = self._get_post(job.post_id, db)
        media = self._get_media(post.id, db)

        self.status_service.start_job(job.id, db)
        connector_name = PLATFORM_CONNECTOR_NAMES.get(job.platform, job.platform.value)

        try:
            connector = self.registry.get(connector_name)
        except ConnectorNotFound:
            return self.status_service.schedule_retry(
                job.id,
                db,
                error_code="CONNECTOR_NOT_FOUND",
                error_message=f"Connector is not registered: {connector_name}",
                raw_response={
                    "mode": "dry_run",
                    "connector": connector_name,
                    "platform": job.platform.value,
                },
            )

        result = connector.publish(post, media)
        if result.success:
            if job.platform == PublicationPlatform.website:
                self._publish_post_to_internal_website(post, db)
            return self.status_service.mark_success(
                job.id,
                db,
                external_post_id=result.external_post_id,
                external_url=result.external_url,
                raw_response=result.raw_response,
            )

        if result.retryable:
            return self.status_service.schedule_retry(
                job.id,
                db,
                error_code=result.error_code,
                error_message=result.error_message,
                raw_response=result.raw_response,
            )

        return self.status_service.mark_error(
            job.id,
            db,
            error_code=result.error_code,
            error_message=result.error_message,
            raw_response=result.raw_response,
        )

    def _publish_post_to_internal_website(self, post: Post, db: Session) -> None:
        post.is_public = True
        if post.published_at is None:
            post.published_at = utc_now()
        db.flush()

    def _get_job(self, job_id: object, db: Session) -> PublicationJob:
        job = db.get(PublicationJob, job_id)
        if job is None:
            raise ValueError("Publication job not found")
        return job

    def _get_post(self, post_id: object, db: Session) -> Post:
        post = db.get(Post, post_id)
        if post is None:
            raise ValueError("Publication job post not found")
        return post

    def _get_media(self, post_id: object, db: Session) -> list[Media]:
        return db.scalars(
            select(Media).where(Media.post_id == post_id).order_by(Media.sort_order)
        ).all()
