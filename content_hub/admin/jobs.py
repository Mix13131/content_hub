from __future__ import annotations

import uuid
from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from content_hub.db import get_db
from content_hub.enums import PlatformStatus, PublicationPlatform
from content_hub.models import PublicationJob, PublicationLog
from content_hub.schemas.admin_jobs import (
    AdminJobDetailResponse,
    AdminJobErrorRequest,
    AdminJobLogResponse,
    AdminJobResponse,
    AdminJobSuccessRequest,
)
from content_hub.services.publication_status import (
    PublicationStatusError,
    PublicationStatusService,
)
from content_hub.settings import Settings, get_settings


def _verify_admin_token(
    settings: Annotated[Settings, Depends(get_settings)],
    admin_token: Annotated[
        str | None,
        Header(alias="X-Content-Hub-Admin-Token"),
    ] = None,
) -> None:
    if not settings.admin_api_token:
        return
    if admin_token and compare_digest(settings.admin_api_token, admin_token):
        return
    raise HTTPException(status_code=403, detail="Invalid admin token")


router = APIRouter(
    prefix="/admin/jobs",
    tags=["admin-jobs"],
    dependencies=[Depends(_verify_admin_token)],
)


@router.get("", response_model=list[AdminJobResponse])
def list_jobs(
    db: Annotated[Session, Depends(get_db)],
    status: PlatformStatus | None = None,
    platform: PublicationPlatform | None = None,
    post_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AdminJobResponse]:
    statement = select(PublicationJob).order_by(PublicationJob.created_at.desc())
    if status is not None:
        statement = statement.where(PublicationJob.status == status)
    if platform is not None:
        statement = statement.where(PublicationJob.platform == platform)
    if post_id is not None:
        statement = statement.where(PublicationJob.post_id == post_id)

    jobs = db.scalars(statement.limit(limit)).all()
    return [AdminJobResponse.model_validate(job) for job in jobs]


@router.get("/{job_id}", response_model=AdminJobDetailResponse)
def get_job_detail(
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> AdminJobDetailResponse:
    job = _get_job_or_404(job_id, db)
    return _build_job_detail(job, db)


@router.post("/{job_id}/start", response_model=AdminJobResponse)
def start_job(
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> AdminJobResponse:
    job = _run_status_transition(job_id, db, "start")
    return AdminJobResponse.model_validate(job)


@router.post("/{job_id}/success", response_model=AdminJobResponse)
def mark_job_success(
    job_id: uuid.UUID,
    payload: AdminJobSuccessRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AdminJobResponse:
    job = _run_status_transition(job_id, db, "success", payload)
    return AdminJobResponse.model_validate(job)


@router.post("/{job_id}/error", response_model=AdminJobResponse)
def mark_job_error(
    job_id: uuid.UUID,
    payload: AdminJobErrorRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AdminJobResponse:
    job = _run_status_transition(job_id, db, "error", payload)
    return AdminJobResponse.model_validate(job)


@router.post("/{job_id}/retry", response_model=AdminJobResponse)
def retry_job(
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> AdminJobResponse:
    job = _run_status_transition(job_id, db, "retry")
    return AdminJobResponse.model_validate(job)


def _run_status_transition(
    job_id: uuid.UUID,
    db: Session,
    transition: str,
    payload: AdminJobSuccessRequest | AdminJobErrorRequest | None = None,
) -> PublicationJob:
    _get_job_or_404(job_id, db)
    service = PublicationStatusService()
    try:
        if transition == "start":
            job = service.start_job(job_id, db)
        elif transition == "success" and isinstance(payload, AdminJobSuccessRequest):
            job = service.mark_success(
                job_id,
                db,
                external_post_id=payload.external_post_id,
                external_url=payload.external_url,
                raw_response=payload.raw_response,
            )
        elif transition == "error" and isinstance(payload, AdminJobErrorRequest):
            job = service.mark_error(
                job_id,
                db,
                error_code=payload.error_code,
                error_message=payload.error_message,
                raw_response=payload.raw_response,
            )
        elif transition == "retry":
            job = service.manual_retry(job_id, db)
        else:
            raise RuntimeError(f"Unsupported transition: {transition}")
    except PublicationStatusError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    db.refresh(job)
    return job


def _get_job_or_404(job_id: uuid.UUID, db: Session) -> PublicationJob:
    job = db.get(PublicationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Publication job not found")
    return job


def _build_job_detail(
    job: PublicationJob,
    db: Session,
) -> AdminJobDetailResponse:
    logs = db.scalars(
        select(PublicationLog)
        .where(PublicationLog.job_id == job.id)
        .order_by(PublicationLog.created_at.desc())
        .limit(20)
    ).all()
    job_data = AdminJobResponse.model_validate(job).model_dump()
    return AdminJobDetailResponse(
        **job_data,
        logs=[AdminJobLogResponse.model_validate(log) for log in logs],
    )
