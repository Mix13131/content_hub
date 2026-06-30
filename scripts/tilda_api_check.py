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


API_BASE_URL = "https://api.tildacdn.info/v1"
TIMEOUT_SECONDS = 15
READ_ONLY_METHODS = frozenset(
    {
        "getprojectslist",
        "getprojectinfo",
        "getpageslist",
        "getpagefull",
    }
)


@dataclass(frozen=True)
class TildaApiConfig:
    public_key: str
    secret_key: str
    project_id: str | None = None
    target_page_id: str | None = None
    base_url: str = API_BASE_URL


FetchJson = Callable[[str, TildaApiConfig, Mapping[str, str] | None], dict[str, Any]]


def read_config_from_env(
    env: Mapping[str, str] | None = None,
) -> TildaApiConfig | None:
    env = env or os.environ
    public_key = _first_env(
        env,
        "CONTENT_HUB_TILDA_PUBLIC_KEY",
        "TILDA_PUBLIC_KEY",
    )
    secret_key = _first_env(
        env,
        "CONTENT_HUB_TILDA_SECRET_KEY",
        "TILDA_SECRET_KEY",
    )
    if not public_key or not secret_key:
        return None

    return TildaApiConfig(
        public_key=public_key,
        secret_key=secret_key,
        project_id=_first_env(
            env,
            "CONTENT_HUB_TILDA_PROJECT_ID",
            "TILDA_PROJECT_ID",
        )
        or None,
        target_page_id=_first_env(
            env,
            "CONTENT_HUB_TILDA_TARGET_PAGE_ID",
            "TILDA_TARGET_PAGE_ID",
        )
        or None,
        base_url=_first_env(
            env,
            "CONTENT_HUB_TILDA_API_BASE_URL",
            "TILDA_API_BASE_URL",
        )
        or API_BASE_URL,
    )


def build_api_url(
    method: str,
    config: TildaApiConfig,
    params: Mapping[str, str] | None = None,
) -> str:
    if method not in READ_ONLY_METHODS:
        raise ValueError(f"Unsupported or unsafe Tilda API method: {method}")

    query_params = {
        "publickey": config.public_key,
        "secretkey": config.secret_key,
    }
    if params:
        query_params.update(params)

    return f"{config.base_url.rstrip('/')}/{method}/?{urlencode(query_params)}"


def request_json(
    method: str,
    config: TildaApiConfig,
    params: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    url = build_api_url(method, config, params)
    request = Request(url, headers={"Accept": "application/json"})

    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        summary = _safe_response_summary(_parse_json(body))
        raise RuntimeError(f"Tilda API {method} failed with HTTP {exc.code}: {summary}") from exc
    except URLError as exc:
        raise RuntimeError(f"Tilda API {method} request failed: {exc.reason}") from exc

    payload = _parse_json(body)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Tilda API {method} returned non-object JSON.")
    return payload


def run_read_only_check(
    config: TildaApiConfig,
    fetch_json: FetchJson = request_json,
) -> int:
    projects_payload = _expect_found(
        "getprojectslist",
        fetch_json("getprojectslist", config, None),
    )
    projects = projects_payload.get("result")
    projects_count = len(projects) if isinstance(projects, list) else "unknown"
    print(f"Tilda API auth check passed. projects_count={projects_count}")

    if config.project_id:
        project_payload = _expect_found(
            "getprojectinfo",
            fetch_json(
                "getprojectinfo",
                config,
                {"projectid": config.project_id},
            ),
        )
        project = project_payload.get("result")
        project_title = _safe_result_title(project)
        print(
            "Tilda project check passed. "
            f"project_id={config.project_id} title={project_title}"
        )

        pages_payload = _expect_found(
            "getpageslist",
            fetch_json(
                "getpageslist",
                config,
                {"projectid": config.project_id},
            ),
        )
        pages = pages_payload.get("result")
        pages_count = len(pages) if isinstance(pages, list) else "unknown"
        print(
            "Tilda pages list check passed. "
            f"project_id={config.project_id} pages_count={pages_count}"
        )
    else:
        print("Skipping project/pages check: CONTENT_HUB_TILDA_PROJECT_ID is not set.")

    if config.target_page_id:
        page_payload = _expect_found(
            "getpagefull",
            fetch_json(
                "getpagefull",
                config,
                {"pageid": config.target_page_id},
            ),
        )
        page = page_payload.get("result")
        page_title = _safe_result_title(page)
        html_length = _safe_html_length(page)
        print(
            "Tilda target page check passed. "
            f"page_id={config.target_page_id} title={page_title} "
            f"html_length={html_length}"
        )
    else:
        print(
            "Skipping target page check: CONTENT_HUB_TILDA_TARGET_PAGE_ID is not set."
        )

    print("Tilda API read-only check passed.")
    return 0


def main(env: Mapping[str, str] | None = None) -> int:
    config = read_config_from_env(env)
    if config is None:
        print("Tilda credentials are not configured; skipping read-only API check.")
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
        raise RuntimeError("Tilda API returned invalid JSON.") from exc


def _expect_found(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "FOUND":
        return payload
    raise RuntimeError(
        f"Tilda API {method} returned {_safe_response_summary(payload)}"
    )


def _safe_response_summary(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "non-object response"
    status = str(payload.get("status", "unknown"))[:80]
    message = str(payload.get("message", ""))[:240]
    code = str(payload.get("code", ""))[:80]
    parts = [f"status={status!r}"]
    if code:
        parts.append(f"code={code!r}")
    if message:
        parts.append(f"message={message!r}")
    return " ".join(parts)


def _safe_result_title(result: Any) -> str:
    if not isinstance(result, dict):
        return "unknown"
    title = str(result.get("title") or "").strip()
    return title[:120] or "unknown"


def _safe_html_length(result: Any) -> int | str:
    if not isinstance(result, dict):
        return "unknown"
    html = result.get("html")
    return len(html) if isinstance(html, str) else "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
