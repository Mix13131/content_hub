# Content Hub

Content Hub is a FastAPI backend for ingesting posts from a Telegram channel and preparing them for automatic publication to a website and social platforms.

Current implementation covers Stage 1 Core ingestion only:

- FastAPI application;
- `/healthz`;
- `/webhooks/telegram`;
- Pydantic Settings;
- SQLAlchemy models;
- Alembic migration;
- text `channel_post` ingestion;
- idempotency by `telegram_chat_id + telegram_post_id`;
- tests for health, ingestion, idempotency, and saved Post fields.

Not implemented yet:

- media download;
- S3-compatible storage;
- Dramatiq workers;
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

## Run Tests

```bash
.venv/bin/python -m pytest tests/content_hub -q
```

## PostgreSQL / Neon Smoke

Stage 1 should be checked against a real PostgreSQL-compatible database before moving to media storage and queue work.

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
