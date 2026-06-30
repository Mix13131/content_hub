from __future__ import annotations

from html import escape

from content_hub.enums import MediaType
from content_hub.models import Media, Post
from content_hub.renderers.base import RenderedPage


class HtmlRenderer:
    def render(self, post: Post, media: list[Media]) -> RenderedPage:
        title = self._title(post)
        slug = self._slug(post)
        meta_description = self._meta_description(post)
        html = "\n".join(
            [
                "<!doctype html>",
                '<html lang="ru">',
                "<head>",
                '<meta charset="utf-8">',
                f"<title>{escape(title)}</title>",
                (
                    '<meta name="description" '
                    f'content="{escape(meta_description, quote=True)}">'
                ),
                "</head>",
                "<body>",
                "<article>",
                f"<h1>{escape(title)}</h1>",
                (
                    f'<p><time datetime="{post.telegram_posted_at.isoformat()}">'
                    f"{escape(post.telegram_posted_at.date().isoformat())}</time></p>"
                ),
                *self._media_html(post, media),
                *self._text_html(post.text),
                "</article>",
                "</body>",
                "</html>",
            ]
        )
        return RenderedPage(
            title=title,
            slug=slug,
            html=html,
            meta_description=meta_description,
        )

    def _title(self, post: Post) -> str:
        if post.title:
            return post.title
        preview = self._compact_text(post.text, 80)
        if preview:
            return preview
        return f"Telegram post {post.telegram_post_id}"

    def _slug(self, post: Post) -> str:
        if post.slug:
            return post.slug
        return f"post-{post.id}"

    def _meta_description(self, post: Post) -> str:
        if post.meta_description:
            return post.meta_description
        return self._compact_text(post.text, 160) or self._title(post)

    def _media_html(self, post: Post, media: list[Media]) -> list[str]:
        html: list[str] = []
        alt = self._alt_text(post)
        for item in sorted(media, key=lambda media_item: media_item.sort_order):
            source = escape(item.file_url or "", quote=True)
            if item.type == MediaType.photo:
                html.append(
                    f'<img src="{source}" alt="{escape(alt, quote=True)}" '
                    f'data-sort-order="{item.sort_order}">'
                )
            elif item.type == MediaType.video:
                html.append(
                    f'<video src="{source}" controls '
                    f'data-sort-order="{item.sort_order}">'
                    f"{escape(alt)}</video>"
                )
        return html

    def _text_html(self, text: str) -> list[str]:
        paragraphs = [
            paragraph.strip()
            for paragraph in text.splitlines()
            if paragraph.strip()
        ]
        if not paragraphs and text.strip():
            paragraphs = [text.strip()]
        return [f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs]

    def _alt_text(self, post: Post) -> str:
        return post.image_alt_text or post.title or self._title(post)

    def _compact_text(self, text: str, limit: int) -> str:
        compact_text = " ".join(text.split())
        if len(compact_text) <= limit:
            return compact_text
        return f"{compact_text[: limit - 1]}..."
