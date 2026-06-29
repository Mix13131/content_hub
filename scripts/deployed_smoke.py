from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TIMEOUT_SECONDS = 15


def main() -> int:
    base_url = os.getenv("CONTENT_HUB_BASE_URL", "").strip().rstrip("/")
    admin_token = os.getenv("CONTENT_HUB_ADMIN_API_TOKEN", "").strip()
    if not base_url:
        print("CONTENT_HUB_BASE_URL must be set.", file=sys.stderr)
        return 2

    health = get_json(f"{base_url}/healthz")
    assert health == {"status": "ok"}, health

    news_html = get_text(f"{base_url}/news")
    assert "<html" in news_html.lower(), "/news did not return HTML"

    public_posts = get_json(f"{base_url}/api/posts/public")
    assert isinstance(public_posts, list), public_posts

    if admin_token:
        admin_posts = get_json(
            f"{base_url}/admin/posts",
            headers={"X-Content-Hub-Admin-Token": admin_token},
        )
        assert isinstance(admin_posts, list), admin_posts
    else:
        print("Skipping /admin/posts check: CONTENT_HUB_ADMIN_API_TOKEN is not set.")

    print("Deployed Content Hub smoke passed.")
    print(f"base_url: {base_url}")
    return 0


def get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    response_text = get_text(url, headers=headers)
    return json.loads(response_text)


def get_text(url: str, headers: dict[str, str] | None = None) -> str:
    request = Request(url, headers=headers or {})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"GET {url} failed with {exc.code}: {body}") from exc
    except URLError as exc:
        raise AssertionError(f"GET {url} failed: {exc}") from exc

    if status < 200 or status >= 300:
        raise AssertionError(f"GET {url} failed with {status}: {body}")
    return body


if __name__ == "__main__":
    raise SystemExit(main())
