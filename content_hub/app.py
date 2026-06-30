from __future__ import annotations

from secrets import compare_digest
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy.orm import Session

from content_hub.admin.jobs import router as admin_jobs_router
from content_hub.admin.posts import router as admin_posts_router
from content_hub.db import get_db
from content_hub.preview.tilda import router as tilda_preview_router
from content_hub.public.news import router as news_router
from content_hub.public.posts import router as public_posts_router
from content_hub.services.telegram_diagnostics import (
    emit_update_error,
    emit_update_received,
    emit_update_result,
)
from content_hub.services.telegram_ingestion import TelegramIngestionService
from content_hub.settings import Settings, get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="Content Hub")
    app.include_router(admin_jobs_router)
    app.include_router(admin_posts_router)
    app.include_router(news_router)
    app.include_router(public_posts_router)
    app.include_router(tilda_preview_router)
    ingestion_service = TelegramIngestionService()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhooks/telegram")
    def telegram_webhook(
        payload: dict[str, Any],
        db: Annotated[Session, Depends(get_db)],
        settings: Annotated[Settings, Depends(get_settings)],
        telegram_secret: Annotated[
            str | None,
            Header(alias="X-Telegram-Bot-Api-Secret-Token"),
        ] = None,
    ) -> dict[str, Any]:
        if settings.telegram_webhook_secret and not (
            telegram_secret
            and compare_digest(settings.telegram_webhook_secret, telegram_secret)
        ):
            raise HTTPException(status_code=403, detail="Invalid Telegram secret")

        emit_update_received(payload)
        try:
            result = ingestion_service.ingest_update(
                payload,
                db,
                allowed_telegram_chat_ids=settings.allowed_telegram_chat_id_set,
            )
        except Exception as exc:
            emit_update_error(payload, exc)
            raise
        emit_update_result(
            payload,
            ignored=result.ignored,
            created=result.created,
            reason=result.reason,
            post_id=result.post_id,
        )
        return {
            "ok": True,
            "ignored": result.ignored,
            "created": result.created,
            "post_id": result.post_id,
            "reason": result.reason,
        }

    return app


app = create_app()
