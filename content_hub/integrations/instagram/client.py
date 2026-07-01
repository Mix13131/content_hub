from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


INSTAGRAM_API_ERROR_CODE = "INSTAGRAM_API_ERROR"
RETRYABLE_META_ERROR_CODES = {1, 2, 4, 17, 32, 613}
SENSITIVE_RESPONSE_KEYS = {
    "access_token",
    "token",
    "secret",
    "client_secret",
    "appsecret_proof",
}


@dataclass(frozen=True)
class InstagramApiCredentials:
    access_token: str | None
    account_id: str | None
    graph_api_base_url: str

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token and self.account_id)


@dataclass(frozen=True)
class InstagramContainerResult:
    container_id: str
    raw_response: dict[str, Any]


@dataclass(frozen=True)
class InstagramPublishResult:
    media_id: str
    raw_response: dict[str, Any]


class InstagramApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        raw_response: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.raw_response = raw_response or {}
        self.retryable = retryable


class InstagramClient(Protocol):
    def create_image_container(
        self,
        *,
        image_url: str,
        caption: str,
    ) -> InstagramContainerResult:
        ...

    def publish_container(self, *, creation_id: str) -> InstagramPublishResult:
        ...

    def get_permalink(self, *, media_id: str) -> str | None:
        ...


class HttpInstagramApiClient:
    def __init__(
        self,
        credentials: InstagramApiCredentials,
        *,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not credentials.is_configured:
            raise InstagramApiError(
                "Instagram credentials are not configured.",
                raw_response={"connector": "instagram", "configured": False},
                retryable=False,
            )
        self.credentials = credentials
        self.timeout_seconds = timeout_seconds

    def create_image_container(
        self,
        *,
        image_url: str,
        caption: str,
    ) -> InstagramContainerResult:
        payload = self._post(
            f"/{self.credentials.account_id}/media",
            data={
                "image_url": image_url,
                "caption": caption,
                "access_token": self.credentials.access_token,
            },
        )
        container_id = _extract_required_id(payload, field_name="id")
        return InstagramContainerResult(
            container_id=container_id,
            raw_response=sanitize_instagram_response(
                payload,
                secrets=(self.credentials.access_token,),
            ),
        )

    def publish_container(self, *, creation_id: str) -> InstagramPublishResult:
        payload = self._post(
            f"/{self.credentials.account_id}/media_publish",
            data={
                "creation_id": creation_id,
                "access_token": self.credentials.access_token,
            },
        )
        media_id = _extract_required_id(payload, field_name="id")
        return InstagramPublishResult(
            media_id=media_id,
            raw_response=sanitize_instagram_response(
                payload,
                secrets=(self.credentials.access_token,),
            ),
        )

    def get_permalink(self, *, media_id: str) -> str | None:
        payload = self._get(
            f"/{media_id}",
            params={
                "fields": "permalink",
                "access_token": self.credentials.access_token,
            },
        )
        permalink = payload.get("permalink")
        return str(permalink) if permalink else None

    def _post(self, path: str, *, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, data=data)

    def _get(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.credentials.graph_api_base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.request(method, url, data=data, params=params)
        except httpx.RequestError as exc:
            raise InstagramApiError(
                "Instagram API request failed due to a network error.",
                raw_response={
                    "connector": "instagram",
                    "error_type": type(exc).__name__,
                },
                retryable=True,
            ) from exc

        payload = _safe_json(response)
        safe_payload = sanitize_instagram_response(
            payload,
            secrets=(self.credentials.access_token,),
        )
        if response.status_code >= 400:
            raise InstagramApiError(
                _api_error_message(safe_payload),
                raw_response={
                    "connector": "instagram",
                    "status_code": response.status_code,
                    "response": safe_payload,
                },
                retryable=_is_retryable_error(response.status_code, payload),
            )
        return payload


def sanitize_instagram_response(
    value: Any,
    *,
    secrets: tuple[str | None, ...] = (),
) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_RESPONSE_KEYS:
                sanitized[key] = "[redacted]"
            else:
                sanitized[key] = sanitize_instagram_response(item, secrets=secrets)
        return sanitized
    if isinstance(value, list):
        return [sanitize_instagram_response(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        sanitized_value = value
        for secret in secrets:
            if secret:
                sanitized_value = sanitized_value.replace(secret, "[redacted]")
        return sanitized_value
    return value


def _extract_required_id(payload: dict[str, Any], *, field_name: str) -> str:
    value = payload.get(field_name)
    if not value:
        raise InstagramApiError(
            f"Instagram API response did not include {field_name}.",
            raw_response={"connector": "instagram", "response": payload},
            retryable=True,
        )
    return str(value)


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {
            "body_preview": response.text[:500],
        }
    return payload if isinstance(payload, dict) else {"response": payload}


def _api_error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if message:
            return f"Instagram API error: {message}"
    return "Instagram API request failed."


def _is_retryable_error(status_code: int, payload: dict[str, Any]) -> bool:
    if status_code == 429 or status_code >= 500:
        return True
    error = payload.get("error")
    if isinstance(error, dict):
        try:
            meta_code = int(error.get("code"))
        except (TypeError, ValueError):
            return False
        return meta_code in RETRYABLE_META_ERROR_CODES
    return False

