from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote, urlencode
from urllib.request import urlopen


class TelegramFileDownloadError(RuntimeError):
    """Safe Telegram file download error without token or payload details."""


@dataclass(frozen=True)
class TelegramDownloadedFile:
    content: bytes
    file_path: str | None = None
    content_type: str | None = None


class TelegramFileDownloader(Protocol):
    def download(self, file_id: str) -> TelegramDownloadedFile:
        ...


class TelegramBotFileService:
    def __init__(
        self,
        *,
        bot_token: str,
        api_base_url: str = "https://api.telegram.org",
        file_base_url: str = "https://api.telegram.org/file",
        timeout_seconds: int = 30,
    ) -> None:
        if not bot_token.strip():
            raise TelegramFileDownloadError("Telegram bot token is not configured.")
        self._bot_token = bot_token.strip()
        self._api_base_url = api_base_url.rstrip("/")
        self._file_base_url = file_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def download(self, file_id: str) -> TelegramDownloadedFile:
        file_path = self._get_file_path(file_id)
        content_url = self._file_url(file_path)
        try:
            with urlopen(content_url, timeout=self._timeout_seconds) as response:
                content = response.read()
                content_type = response.headers.get("Content-Type")
        except Exception as exc:
            raise TelegramFileDownloadError("Telegram file download failed.") from exc
        return TelegramDownloadedFile(
            content=content,
            file_path=file_path,
            content_type=content_type,
        )

    def _get_file_path(self, file_id: str) -> str:
        if not file_id.strip():
            raise TelegramFileDownloadError("Telegram file_id is missing.")
        query = urlencode({"file_id": file_id})
        url = f"{self._api_base_url}/bot{self._bot_token}/getFile?{query}"
        try:
            with urlopen(url, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise TelegramFileDownloadError("Telegram getFile request failed.") from exc

        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise TelegramFileDownloadError("Telegram getFile returned an error.")
        result = payload.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("file_path"), str):
            raise TelegramFileDownloadError("Telegram getFile returned no file path.")
        return result["file_path"]

    def _file_url(self, file_path: str) -> str:
        return f"{self._file_base_url}/bot{self._bot_token}/{quote(file_path, safe='/')}"


def create_telegram_file_downloader(settings: Any) -> TelegramFileDownloader | None:
    if not settings.storage_enabled:
        return None
    if not settings.telegram_bot_token:
        return None
    return TelegramBotFileService(bot_token=settings.telegram_bot_token)
