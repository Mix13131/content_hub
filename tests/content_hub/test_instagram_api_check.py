from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from scripts import instagram_api_check


def test_missing_instagram_credentials_skip_without_error(capsys) -> None:
    assert instagram_api_check.main({}) == 0

    output = capsys.readouterr().out
    assert "Instagram credentials are not configured" in output


def test_reads_instagram_env_names() -> None:
    config = instagram_api_check.read_config_from_env(
        {
            "CONTENT_HUB_INSTAGRAM_ACCESS_TOKEN": " token ",
            "CONTENT_HUB_INSTAGRAM_ACCOUNT_ID": " 17841400000000000 ",
            "CONTENT_HUB_FACEBOOK_PAGE_ID": " 123456789 ",
        }
    )

    assert config is not None
    assert config.access_token == "token"
    assert config.instagram_account_id == "17841400000000000"
    assert config.facebook_page_id == "123456789"


def test_build_api_url_allows_only_read_only_targets() -> None:
    config = instagram_api_check.InstagramApiConfig(
        access_token="token",
        instagram_account_id="17841400000000000",
    )

    url = instagram_api_check.build_api_url(
        "instagram_account",
        config,
        "17841400000000000",
        {"fields": "id,username"},
    )

    assert url == (
        "https://graph.facebook.com/v25.0/17841400000000000"
        "?access_token=token&fields=id%2Cusername"
    )


def test_build_api_url_rejects_write_like_targets() -> None:
    config = instagram_api_check.InstagramApiConfig(
        access_token="token",
        instagram_account_id="17841400000000000",
    )

    try:
        instagram_api_check.build_api_url(
            "media_publish",
            config,
            "17841400000000000",
        )
    except ValueError as exc:
        assert "Unsupported or unsafe" in str(exc)
    else:
        raise AssertionError("media_publish should be rejected")


def test_read_only_check_uses_expected_safe_targets(capsys) -> None:
    calls: list[tuple[str, str, Mapping[str, str] | None]] = []

    def fake_fetch(
        target: str,
        config: instagram_api_check.InstagramApiConfig,
        object_id: str,
        params: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        calls.append((target, object_id, params))
        if target == "instagram_account":
            return {
                "id": "17841400000000000",
                "username": "contenthub",
                "media_count": 12,
            }
        if target == "facebook_page":
            return {
                "id": "123456789",
                "name": "Content Hub Page",
                "instagram_business_account": {"id": "17841400000000000"},
            }
        raise AssertionError(f"Unexpected target: {target}")

    config = instagram_api_check.InstagramApiConfig(
        access_token="token",
        instagram_account_id="17841400000000000",
        facebook_page_id="123456789",
    )

    assert instagram_api_check.run_read_only_check(config, fake_fetch) == 0

    assert calls == [
        (
            "instagram_account",
            "17841400000000000",
            {"fields": "id,username,name,media_count"},
        ),
        (
            "facebook_page",
            "123456789",
            {"fields": "id,name,instagram_business_account"},
        ),
    ]
    output = capsys.readouterr().out
    assert "Instagram API read-only check passed." in output
    assert "token" not in output
