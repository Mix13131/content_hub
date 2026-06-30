from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from content_hub.models import Media, Post


@dataclass(frozen=True)
class RenderedPage:
    title: str
    slug: str
    html: str
    meta_description: str


class PageRenderer(Protocol):
    def render(self, post: Post, media: list[Media]) -> RenderedPage:
        ...
