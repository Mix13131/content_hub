import json
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from content_hub.app import create_app
from content_hub.db import get_db
from content_hub.enums import PlatformStatus, PublicationPlatform
from content_hub.models import Post, PublicationJob
from content_hub.services.publication_status import PublicationStatusService
from content_hub.services.telegram_ingestion import TelegramIngestionService
from content_hub.settings import Settings, get_settings


FIXTURES_DIR = Path(__file__).parent / "fixtures"
ADMIN_TOKEN = "local-admin-token"


@pytest.fixture()
def admin_client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    def override_get_settings() -> Settings:
        return Settings(
            database_url="sqlite://",
            telegram_webhook_secret=None,
            admin_api_token=ADMIN_TOKEN,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


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


def admin_headers() -> dict[str, str]:
    return {"X-Content-Hub-Admin-Token": ADMIN_TOKEN}


def test_admin_endpoints_allow_access_without_configured_token(
    client: TestClient,
    db_session: Session,
) -> None:
    create_post_with_jobs(db_session)

    response = client.get("/admin/jobs")

    assert response.status_code == 200
    assert len(response.json()) == 4


def test_admin_endpoints_require_token_when_configured(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    create_post_with_jobs(db_session)

    missing_response = admin_client.get("/admin/jobs")
    wrong_response = admin_client.get(
        "/admin/jobs",
        headers={"X-Content-Hub-Admin-Token": "wrong-token"},
    )
    correct_response = admin_client.get("/admin/jobs", headers=admin_headers())

    assert missing_response.status_code == 403
    assert wrong_response.status_code == 403
    assert correct_response.status_code == 200


def test_get_admin_jobs_returns_jobs_and_supports_filters(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post, _ = create_post_with_jobs(db_session)

    response = admin_client.get(
        "/admin/jobs",
        params={
            "platform": PublicationPlatform.website.value,
            "status": PlatformStatus.Waiting.value,
            "post_id": str(post.id),
        },
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["post_id"] == str(post.id)
    assert body[0]["platform"] == PublicationPlatform.website.value
    assert body[0]["status"] == PlatformStatus.Waiting.value
    assert body[0]["attempt_count"] == 0
    assert body[0]["max_attempts"] == 5


def test_get_admin_job_detail_returns_job_and_recent_logs(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.website]
    start_response = admin_client.post(
        f"/admin/jobs/{job.id}/start",
        headers=admin_headers(),
    )
    assert start_response.status_code == 200

    response = admin_client.get(f"/admin/jobs/{job.id}", headers=admin_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(job.id)
    assert body["status"] == PlatformStatus.Publishing.value
    assert body["logs"][0]["event"] == "job_started"
    assert body["logs"][0]["job_id"] == str(job.id)


def test_start_endpoint_marks_job_publishing(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.website]

    response = admin_client.post(
        f"/admin/jobs/{job.id}/start",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == PlatformStatus.Publishing.value
    assert body["attempt_count"] == 1
    assert body["started_at"] is not None


def test_success_endpoint_marks_job_success(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.instagram]
    admin_client.post(f"/admin/jobs/{job.id}/start", headers=admin_headers())

    response = admin_client.post(
        f"/admin/jobs/{job.id}/success",
        json={
            "external_post_id": "ig_123",
            "external_url": "https://instagram.example/p/ig_123",
            "raw_response": {"ok": True},
        },
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == PlatformStatus.Success.value
    assert body["external_post_id"] == "ig_123"
    assert body["external_url"] == "https://instagram.example/p/ig_123"
    assert body["last_error_code"] is None
    assert body["last_error_message"] is None


def test_error_endpoint_marks_job_error(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.vk]
    admin_client.post(f"/admin/jobs/{job.id}/start", headers=admin_headers())

    response = admin_client.post(
        f"/admin/jobs/{job.id}/error",
        json={
            "error_code": "VK_AUTH",
            "error_message": "VK token expired",
            "raw_response": {"error": "expired"},
        },
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == PlatformStatus.Error.value
    assert body["last_error_code"] == "VK_AUTH"
    assert body["last_error_message"] == "VK token expired"


def test_retry_endpoint_returns_error_job_to_waiting(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.facebook]
    admin_client.post(f"/admin/jobs/{job.id}/start", headers=admin_headers())
    admin_client.post(
        f"/admin/jobs/{job.id}/error",
        json={"error_code": "FB_SYNC", "error_message": "Sync not confirmed"},
        headers=admin_headers(),
    )

    response = admin_client.post(
        f"/admin/jobs/{job.id}/retry",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == PlatformStatus.Waiting.value
    assert body["attempt_count"] == 1
    assert body["last_error_code"] is None
    assert body["last_error_message"] is None


def test_run_job_requires_token(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.website]

    response = admin_client.post(f"/admin/jobs/{job.id}/run")

    assert response.status_code == 403


def test_run_website_job_executes_connector_engine(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    post, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.website]

    response = admin_client.post(
        f"/admin/jobs/{job.id}/run",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == PlatformStatus.Success.value
    assert body["external_post_id"] == str(post.id)
    assert body["external_url"] == f"/news/{post.slug}"
    db_session.refresh(post)
    assert post.is_public is True
    assert post.published_at is not None
    assert post.website_status == PlatformStatus.Success


def test_run_success_job_returns_409(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.website]
    PublicationStatusService().mark_success(job.id, db_session)

    response = admin_client.post(
        f"/admin/jobs/{job.id}/run",
        headers=admin_headers(),
    )

    assert response.status_code == 409
    assert "Success" in response.json()["detail"]


def test_run_publishing_job_returns_409(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.website]
    PublicationStatusService().start_job(job.id, db_session)

    response = admin_client.post(
        f"/admin/jobs/{job.id}/run",
        headers=admin_headers(),
    )

    assert response.status_code == 409
    assert "Publishing" in response.json()["detail"]


def test_run_unknown_connector_job_returns_controlled_response(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.instagram]

    response = admin_client.post(
        f"/admin/jobs/{job.id}/run",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == PlatformStatus.Retry.value
    assert body["attempt_count"] == 1
    assert body["last_error_code"] == "CONNECTOR_NOT_FOUND"
    assert body["last_error_message"] == "Connector is not registered: instagram"


def test_forbidden_transition_returns_409(
    admin_client: TestClient,
    db_session: Session,
) -> None:
    _, jobs = create_post_with_jobs(db_session)
    job = jobs[PublicationPlatform.website]
    first_response = admin_client.post(
        f"/admin/jobs/{job.id}/start",
        headers=admin_headers(),
    )
    second_response = admin_client.post(
        f"/admin/jobs/{job.id}/start",
        headers=admin_headers(),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert "already publishing" in second_response.json()["detail"]


def test_unknown_job_returns_404(admin_client: TestClient) -> None:
    unknown_job_id = uuid.uuid4()

    get_response = admin_client.get(
        f"/admin/jobs/{unknown_job_id}",
        headers=admin_headers(),
    )
    start_response = admin_client.post(
        f"/admin/jobs/{unknown_job_id}/start",
        headers=admin_headers(),
    )
    run_response = admin_client.post(
        f"/admin/jobs/{unknown_job_id}/run",
        headers=admin_headers(),
    )

    assert get_response.status_code == 404
    assert start_response.status_code == 404
    assert run_response.status_code == 404
