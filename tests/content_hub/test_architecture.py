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


def test_webhook_endpoint_does_not_import_publishers() -> None:
    source = (PROJECT_ROOT / "content_hub" / "app.py").read_text(encoding="utf-8")
    assert "content_hub.publishers" not in source
