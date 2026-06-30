from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE_URL = "https://graph.facebook.com"
TIMEOUT_SECONDS = 15
READ_ONLY_TARGETS = frozenset({"instagram_account", "facebook_page"})


@dataclass(frozen=True)
class InstagramApiConfig:
    access_token: str
    instagram_account_id: str
    facebook_page_id: str | None = None
    graph_api_version: str = GRAPH_API_VERSION
    graph_api_base_url: str = GRAPH_API_BASE_URL


FetchJson = Callable[
    [str, InstagramApiConfig, str, Mapping[str, str] | None],
    dict[str, Any],
]


def read_config_from_env(
    env: Mapping[str, str] | None = None,
) -> InstagramApiConfig | None:
    env = env or os.environ
    access_token = _first_env(env, "CONTENT_HUB_INSTAGRAM_ACCESS_TOKEN")
    instagram_account_id = _first_env(env, "CONTENT_HUB_INSTAGRAM_ACCOUNT_ID")
    if not access_token or not instagram_account_id:
        return None

    return InstagramApiConfig(
        access_token=access_token,
        instagram_account_id=instagram_account_id,
        facebook_page_id=_first_env(env, "CONTENT_HUB_FACEBOOK_PAGE_ID") or None,
        graph_api_version=_first_env(env, "CONTENT_HUB_META_GRAPH_API_VERSION")
        or GRAPH_API_VERSION,
        graph_api_base_url=_first_env(env, "CONTENT_HUB_META_GRAPH_API_BASE_URL")
        or GRAPH_API_BASE_URL,
    )


def build_api_url(
    target: str,
    config: InstagramApiConfig,
    object_id: str,
    params: Mapping[str, str] | None = None,
) -> str:
    if target not in READ_ONLY_TARGETS:
        raise ValueError(f"Unsupported or unsafe Instagram API target: {target}")
    if not object_id.strip():
        raise ValueError("Instagram API object_id must not be empty.")

    query_params = {"access_token": config.access_token}
    if params:
        query_params.update(params)

    base_url = config.graph_api_base_url.rstrip("/")
    version = config.graph_api_version.strip().strip("/")
    return f"{base_url}/{version}/{object_id.strip()}?{urlencode(query_params)}"


def request_json(
    target: str,
    config: InstagramApiConfig,
    object_id: str,
    params: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    url = build_api_url(target, config, object_id, params)
    request = Request(url, headers={"Accept": "application/json"})

    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        summary = _safe_response_summary(_parse_json(body))
        raise RuntimeError(
            f"Instagram API {target} failed with HTTP {exc.code}: {summary}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Instagram API {target} request failed: {exc.reason}"
        ) from exc

    payload = _parse_json(body)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Instagram API {target} returned non-object JSON.")
    return payload


def run_read_only_check(
    config: InstagramApiConfig,
    fetch_json: FetchJson = request_json,
) -> int:
    account_payload = fetch_json(
        "instagram_account",
        config,
        config.instagram_account_id,
        {"fields": "id,username,name,media_count"},
    )
    account_id = str(account_payload.get("id") or "unknown")
    username = str(account_payload.get("username") or "unknown")
    media_count = account_payload.get("media_count", "unknown")
    print(
        "Instagram account check passed. "
        f"instagram_account_id={account_id} username={username} "
        f"media_count={media_count}"
    )

    if config.facebook_page_id:
        page_payload = fetch_json(
            "facebook_page",
            config,
            config.facebook_page_id,
            {"fields": "id,name,instagram_business_account"},
        )
        page_id = str(page_payload.get("id") or "unknown")
        page_name = str(page_payload.get("name") or "unknown")[:120]
        linked_account = page_payload.get("instagram_business_account")
        linked_account_id = (
            linked_account.get("id")
            if isinstance(linked_account, dict)
            else "unknown"
        )
        print(
            "Facebook Page check passed. "
            f"facebook_page_id={page_id} name={page_name} "
            f"linked_instagram_account_id={linked_account_id}"
        )
    else:
        print("Skipping Facebook Page check: CONTENT_HUB_FACEBOOK_PAGE_ID is not set.")

    print("Instagram API read-only check passed.")
    return 0


def main(env: Mapping[str, str] | None = None) -> int:
    config = read_config_from_env(env)
    if config is None:
        print("Instagram credentials are not configured; skipping read-only API check.")
        return 0

    try:
        return run_read_only_check(config)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _first_env(env: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    return ""


def _parse_json(body: str) -> Any:
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Instagram API returned invalid JSON.") from exc


def _safe_response_summary(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "non-object response"
    error = payload.get("error")
    if not isinstance(error, dict):
        return "no error object in response"
    error_type = str(error.get("type", "unknown"))[:80]
    error_code = str(error.get("code", ""))[:80]
    error_subcode = str(error.get("error_subcode", ""))[:80]
    message = str(error.get("message", ""))[:240]
    parts = [f"type={error_type!r}"]
    if error_code:
        parts.append(f"code={error_code!r}")
    if error_subcode:
        parts.append(f"subcode={error_subcode!r}")
    if message:
        parts.append(f"message={message!r}")
    return " ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
