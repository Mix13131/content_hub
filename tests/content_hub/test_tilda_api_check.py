from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from scripts import tilda_api_check


def test_missing_tilda_credentials_skip_without_error(capsys) -> None:
    assert tilda_api_check.main({}) == 0

    output = capsys.readouterr().out
    assert "Tilda credentials are not configured" in output


def test_reads_content_hub_tilda_env_names() -> None:
    config = tilda_api_check.read_config_from_env(
        {
            "CONTENT_HUB_TILDA_PUBLIC_KEY": " public ",
            "CONTENT_HUB_TILDA_SECRET_KEY": " secret ",
            "CONTENT_HUB_TILDA_PROJECT_ID": " 123 ",
            "CONTENT_HUB_TILDA_TARGET_PAGE_ID": " 456 ",
        }
    )

    assert config is not None
    assert config.public_key == "public"
    assert config.secret_key == "secret"
    assert config.project_id == "123"
    assert config.target_page_id == "456"


def test_reads_local_tilda_env_aliases() -> None:
    config = tilda_api_check.read_config_from_env(
        {
            "TILDA_PUBLIC_KEY": "public",
            "TILDA_SECRET_KEY": "secret",
            "TILDA_PROJECT_ID": "123",
            "TILDA_TARGET_PAGE_ID": "456",
        }
    )

    assert config is not None
    assert config.public_key == "public"
    assert config.secret_key == "secret"
    assert config.project_id == "123"
    assert config.target_page_id == "456"


def test_build_api_url_allows_only_read_only_methods() -> None:
    config = tilda_api_check.TildaApiConfig(
        public_key="public",
        secret_key="secret",
    )

    url = tilda_api_check.build_api_url(
        "getpageslist",
        config,
        {"projectid": "123"},
    )

    assert url == (
        "https://api.tildacdn.info/v1/getpageslist/"
        "?publickey=public&secretkey=secret&projectid=123"
    )


def test_build_api_url_rejects_write_like_methods() -> None:
    config = tilda_api_check.TildaApiConfig(
        public_key="public",
        secret_key="secret",
    )

    try:
        tilda_api_check.build_api_url("createpage", config)
    except ValueError as exc:
        assert "Unsupported or unsafe" in str(exc)
    else:
        raise AssertionError("createpage should be rejected")


def test_read_only_check_uses_expected_safe_methods(capsys) -> None:
    calls: list[tuple[str, Mapping[str, str] | None]] = []

    def fake_fetch(
        method: str,
        config: tilda_api_check.TildaApiConfig,
        params: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        calls.append((method, params))
        if method == "getprojectslist":
            return {"status": "FOUND", "result": [{"id": "123"}]}
        if method == "getprojectinfo":
            return {"status": "FOUND", "result": {"id": "123", "title": "Site"}}
        if method == "getpageslist":
            return {"status": "FOUND", "result": [{"id": "456"}]}
        if method == "getpagefull":
            return {
                "status": "FOUND",
                "result": {"id": "456", "title": "Page", "html": "<html></html>"},
            }
        raise AssertionError(f"Unexpected method: {method}")

    config = tilda_api_check.TildaApiConfig(
        public_key="public",
        secret_key="secret",
        project_id="123",
        target_page_id="456",
    )

    assert tilda_api_check.run_read_only_check(config, fake_fetch) == 0

    assert calls == [
        ("getprojectslist", None),
        ("getprojectinfo", {"projectid": "123"}),
        ("getpageslist", {"projectid": "123"}),
        ("getpagefull", {"pageid": "456"}),
    ]
    output = capsys.readouterr().out
    assert "Tilda API read-only check passed." in output
    assert "public" not in output
    assert "secret" not in output
