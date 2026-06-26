# Content Hub

Content Hub is a FastAPI backend for ingesting posts from a Telegram channel and preparing them for automatic publication to a website and social platforms.

Current implementation covers metadata-only core ingestion:

- FastAPI application;
- `/healthz`;
- `/webhooks/telegram`;
- Pydantic Settings;
- SQLAlchemy models;
- Alembic migration;
- text/photo/video `channel_post` ingestion;
- media metadata for Telegram photo/video posts;
- PublicationJob creation for website, Instagram, VK, and Facebook via Instagram sync;
- idempotency by `telegram_chat_id + telegram_post_id`;
- tests for health, ingestion, idempotency, media metadata, PublicationJob rows, and saved Post fields.

Not implemented yet:

- Telegram file download;
- S3-compatible storage;
- Dramatiq workers;
- publisher workers;
- Instagram, VK, Facebook publishing;
- admin panel;
- AI, Stories, WhatsApp.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

MVP media handling is metadata-only: Content Hub stores Telegram `file_id`, `file_unique_id`, dimensions, MIME type, duration, and source Telegram URL. It does not download Telegram files or upload them to S3-compatible storage.

## Run Tests

```bash
.venv/bin/python -m pytest tests/content_hub -q
```

## PostgreSQL / Neon Smoke

Core ingestion should be checked against a real PostgreSQL-compatible database before worker or publisher work.

See [docs/postgres_smoke.md](docs/postgres_smoke.md).

## Run App

```bash
.venv/bin/uvicorn content_hub.main:app --reload
```

## Run Migrations

```bash
CONTENT_HUB_DATABASE_URL=postgresql+psycopg://user:password@host:5432/db \
  .venv/bin/alembic -c content_hub/alembic.ini upgrade head
```
