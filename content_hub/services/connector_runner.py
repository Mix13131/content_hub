from __future__ import annotations

from sqlalchemy.orm import Session

from content_hub.connectors.engine import ConnectorEngine
from content_hub.enums import PlatformStatus
from content_hub.models import PublicationJob
from content_hub.services.publication_status import PublicationStatusError


RUNNABLE_CONNECTOR_JOB_STATUSES = {
    PlatformStatus.Waiting,
    PlatformStatus.Retry,
    PlatformStatus.Error,
}


class ConnectorJobRunError(RuntimeError):
    """Raised when a publication job cannot be run manually."""


def run_connector_job(job_id: object, db: Session) -> PublicationJob:
    job = db.get(PublicationJob, job_id)
    if job is None:
        raise ConnectorJobRunError("Publication job not found")
    if job.status not in RUNNABLE_CONNECTOR_JOB_STATUSES:
        raise ConnectorJobRunError(
            f"Cannot run publication job with status {job.status.value}"
        )

    try:
        updated_job = ConnectorEngine().publish_job(job.id, db)
    except PublicationStatusError as exc:
        raise ConnectorJobRunError(str(exc)) from exc

    db.commit()
    db.refresh(updated_job)
    return updated_job
