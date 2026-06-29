from __future__ import annotations

import re
from dataclasses import dataclass

from content_hub.enums import PostType


TITLE_LIMIT = 80
META_DESCRIPTION_LIMIT = 160
SLUG_LIMIT = 255


@dataclass(frozen=True)
class DefaultSeo:
    slug: str
    title: str
    meta_description: str | None
    image_alt_text: str | None


def build_default_seo(
    *,
    telegram_chat_id: int,
    telegram_post_id: int,
    text: str,
    post_type: PostType,
) -> DefaultSeo:
    title = _default_title(text, post_type)
    return DefaultSeo(
        slug=build_default_slug(telegram_chat_id, telegram_post_id),
        title=title,
        meta_description=_default_meta_description(text),
        image_alt_text=title if post_type in {PostType.photo, PostType.video} else None,
    )


def build_default_slug(telegram_chat_id: int, telegram_post_id: int) -> str:
    chat_part = abs(telegram_chat_id)
    return f"telegram-c{chat_part}-m{telegram_post_id}"


def normalize_slug(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"[^a-z0-9-]+", "", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized[:SLUG_LIMIT]


def _default_title(text: str, post_type: PostType) -> str:
    first_line = _first_non_empty_line(text)
    if first_line:
        return first_line[:TITLE_LIMIT]
    if post_type == PostType.photo:
        return "Photo post"
    if post_type == PostType.video:
        return "Video post"
    return "Telegram post"


def _default_meta_description(text: str) -> str | None:
    compact_text = text.strip()
    if not compact_text:
        return None
    return compact_text[:META_DESCRIPTION_LIMIT]


def _first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        stripped_line = line.strip()
        if stripped_line:
            return stripped_line
    return text.strip()
