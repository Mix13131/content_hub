from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from content_hub.admin.auth import verify_admin_token
from content_hub.db import get_db
from content_hub.models import Post
from content_hub.renderers.html_renderer import HtmlRenderer


router = APIRouter(
    prefix="/preview/tilda",
    tags=["tilda-preview"],
    dependencies=[Depends(verify_admin_token)],
)


@router.get("/{post_id}", response_class=HTMLResponse)
def get_tilda_preview(
    post_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    post = db.scalar(
        select(Post)
        .where(Post.id == post_id)
        .options(selectinload(Post.media))
    )
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    rendered = HtmlRenderer().render(post, list(post.media))
    return HTMLResponse(rendered.html)
