from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from content_hub.db import get_db
from content_hub.enums import PostStatus
from content_hub.models import Post


router = APIRouter(tags=["news"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.get("/news", response_class=HTMLResponse)
def list_news(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    posts = db.scalars(
        _public_news_statement()
        .where(Post.slug.is_not(None))
        .where(Post.slug != "")
        .order_by(Post.telegram_posted_at.desc(), Post.created_at.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "news_list.html",
        {"posts": posts, "text_preview": _preview},
    )


@router.get("/news/{slug}", response_class=HTMLResponse)
def get_news_detail(
    slug: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    post = db.scalar(
        _public_news_statement()
        .where(Post.slug == slug)
        .options(selectinload(Post.media))
    )
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    return templates.TemplateResponse(
        request,
        "news_detail.html",
        {
            "post": post,
            "media": sorted(post.media, key=lambda media: media.sort_order),
            "meta_description": post.meta_description or _preview(post.text, 160),
        },
    )


def _public_news_statement():
    return (
        select(Post)
        .where(Post.is_public.is_(True))
        .where(Post.status != PostStatus.error)
    )


def _preview(text: str, limit: int = 160) -> str:
    compact_text = " ".join(text.split())
    if len(compact_text) <= limit:
        return compact_text
    return f"{compact_text[: limit - 1]}..."
