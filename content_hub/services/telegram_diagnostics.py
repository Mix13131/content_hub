from __future__ import annotations

from typing import Any


RECEIVED_PREFIX = "CONTENT_HUB_TELEGRAM_UPDATE_RECEIVED"
RESULT_PREFIX = "CONTENT_HUB_TELEGRAM_UPDATE_RESULT"
ERROR_PREFIX = "CONTENT_HUB_TELEGRAM_UPDATE_ERROR"

KNOWN_UPDATE_TYPES = (
    "channel_post",
    "message",
    "edited_channel_post",
    "my_chat_member",
)


def detect_update_type(update: dict[str, Any]) -> str:
    for update_type in KNOWN_UPDATE_TYPES:
        if update_type in update:
            return update_type
    return "other"


def safe_update_keys(update: dict[str, Any]) -> list[str]:
    return [str(key) for key in update]


def format_update_received(update: dict[str, Any]) -> str:
    return (
        f"{RECEIVED_PREFIX} "
        f"update_id={_format_update_id(update.get('update_id'))} "
        f"keys={_format_keys(safe_update_keys(update))} "
        f"update_type={detect_update_type(update)}"
    )


def format_update_result(
    update: dict[str, Any],
    *,
    ignored: bool,
    created: bool,
    reason: str | None,
    post_id: str | None,
) -> str:
    return (
        f"{RESULT_PREFIX} "
        f"update_id={_format_update_id(update.get('update_id'))} "
        f"ignored={ignored} "
        f"created={created} "
        f"reason={reason} "
        f"post_id={post_id}"
    )


def format_update_error(update: dict[str, Any], exc: Exception) -> str:
    return (
        f"{ERROR_PREFIX} "
        f"update_id={_format_update_id(update.get('update_id'))} "
        f"keys={_format_keys(safe_update_keys(update))} "
        f"update_type={detect_update_type(update)} "
        f"error_type={exc.__class__.__name__}"
    )


def emit_update_received(update: dict[str, Any]) -> None:
    print(format_update_received(update), flush=True)


def emit_update_result(
    update: dict[str, Any],
    *,
    ignored: bool,
    created: bool,
    reason: str | None,
    post_id: str | None,
) -> None:
    print(
        format_update_result(
            update,
            ignored=ignored,
            created=created,
            reason=reason,
            post_id=post_id,
        ),
        flush=True,
    )


def emit_update_error(update: dict[str, Any], exc: Exception) -> None:
    print(format_update_error(update, exc), flush=True)


def _format_update_id(value: object) -> str:
    if value is None:
        return "None"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.isdecimal():
        return value
    return "<non-integer>"


def _format_keys(keys: list[str]) -> str:
    return ",".join(keys) if keys else "-"
