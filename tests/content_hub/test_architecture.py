from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_models_do_not_import_services() -> None:
    for path in (PROJECT_ROOT / "content_hub" / "models").glob("*.py"):
        assert "content_hub.services" not in path.read_text(encoding="utf-8")


def test_services_do_not_import_fastapi_http_layer() -> None:
    for path in (PROJECT_ROOT / "content_hub" / "services").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from fastapi" not in source
        assert "import fastapi" not in source
        assert "Request" not in source
        assert "Response" not in source


def test_connectors_do_not_import_fastapi_or_telegram_ingestion() -> None:
    for path in (PROJECT_ROOT / "content_hub" / "connectors").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from fastapi" not in source
        assert "import fastapi" not in source
        assert "content_hub.services.telegram_ingestion" not in source


def test_connectors_do_not_call_external_apis() -> None:
    for path in (PROJECT_ROOT / "content_hub" / "connectors").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "httpx" not in source
        assert "requests" not in source
        assert "urllib" not in source
        assert "boto3" not in source
        assert "getFile" not in source
        assert "facebook_business" not in source
        assert "wordpress_xmlrpc" not in source
        assert "tilda_api" not in source.lower()
        assert "vk_api" not in source.lower()


def test_connector_engine_does_not_import_future_api_clients() -> None:
    source = (
        PROJECT_ROOT / "content_hub" / "connectors" / "engine.py"
    ).read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "requests" not in source
    assert "urllib" not in source
    assert "boto3" not in source
    assert "facebook_business" not in source
    assert "wordpress_xmlrpc" not in source
    assert "tilda_api" not in source.lower()
    assert "vk_api" not in source.lower()


def test_webhook_endpoint_does_not_import_publishers() -> None:
    source = (PROJECT_ROOT / "content_hub" / "app.py").read_text(encoding="utf-8")
    assert "content_hub.publishers" not in source
    assert "content_hub.connectors.website" not in source


def test_queue_service_does_not_import_publishers() -> None:
    source = (
        PROJECT_ROOT / "content_hub" / "services" / "publication_queue.py"
    ).read_text(encoding="utf-8")
    assert "content_hub.publishers" not in source
    assert "content_hub.connectors.website" not in source


def test_telegram_ingestion_uses_storage_abstraction_only() -> None:
    source = (
        PROJECT_ROOT / "content_hub" / "services" / "telegram_ingestion.py"
    ).read_text(encoding="utf-8")
    assert "boto3" not in source
    assert "S3CompatibleStorage" not in source
    assert "content_hub.storage.s3" not in source
    assert "getFile" not in source


def test_status_service_does_not_import_publishers() -> None:
    source = (
        PROJECT_ROOT / "content_hub" / "services" / "publication_status.py"
    ).read_text(encoding="utf-8")
    assert "content_hub.publishers" not in source
    assert "content_hub.connectors.website" not in source


def test_admin_jobs_router_does_not_import_publishers() -> None:
    source = (
        PROJECT_ROOT / "content_hub" / "admin" / "jobs.py"
    ).read_text(encoding="utf-8")
    assert "content_hub.publishers" not in source
    assert "content_hub.connectors" not in source


def test_admin_posts_router_does_not_import_publishers() -> None:
    source = (
        PROJECT_ROOT / "content_hub" / "admin" / "posts.py"
    ).read_text(encoding="utf-8")
    assert "content_hub.publishers" not in source
    assert "content_hub.connectors" not in source


def test_admin_jobs_router_does_not_call_external_apis() -> None:
    source = (
        PROJECT_ROOT / "content_hub" / "admin" / "jobs.py"
    ).read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "requests" not in source
    assert "urllib" not in source
    assert "boto3" not in source
    assert "getFile" not in source


def test_admin_posts_router_does_not_call_external_apis() -> None:
    source = (
        PROJECT_ROOT / "content_hub" / "admin" / "posts.py"
    ).read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "requests" not in source
    assert "urllib" not in source
    assert "boto3" not in source
    assert "getFile" not in source


def test_public_posts_router_does_not_import_publishers() -> None:
    source = (
        PROJECT_ROOT / "content_hub" / "public" / "posts.py"
    ).read_text(encoding="utf-8")
    assert "content_hub.publishers" not in source
    assert "content_hub.connectors" not in source


def test_public_posts_router_does_not_call_external_apis() -> None:
    source = (
        PROJECT_ROOT / "content_hub" / "public" / "posts.py"
    ).read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "requests" not in source
    assert "urllib" not in source
    assert "boto3" not in source
    assert "getFile" not in source


def test_news_router_does_not_import_publishers() -> None:
    source = (
        PROJECT_ROOT / "content_hub" / "public" / "news.py"
    ).read_text(encoding="utf-8")
    assert "content_hub.publishers" not in source
    assert "content_hub.connectors" not in source


def test_news_router_does_not_call_external_apis() -> None:
    source = (
        PROJECT_ROOT / "content_hub" / "public" / "news.py"
    ).read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "requests" not in source
    assert "urllib" not in source
    assert "boto3" not in source
    assert "getFile" not in source


def test_admin_auth_is_shared_between_admin_routers() -> None:
    jobs_source = (
        PROJECT_ROOT / "content_hub" / "admin" / "jobs.py"
    ).read_text(encoding="utf-8")
    posts_source = (
        PROJECT_ROOT / "content_hub" / "admin" / "posts.py"
    ).read_text(encoding="utf-8")
    assert "from content_hub.admin.auth import verify_admin_token" in jobs_source
    assert "from content_hub.admin.auth import verify_admin_token" in posts_source
