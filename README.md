# Content Hub

[![CI](https://github.com/Mix13131/content_hub/actions/workflows/ci.yml/badge.svg)](https://github.com/Mix13131/content_hub/actions/workflows/ci.yml)

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
- DB-only PublicationJob status and retry lifecycle service;
- minimal token-protected admin API endpoints for PublicationJob lifecycle checks;
- read-only admin API endpoints for Post, Media, PublicationJob, and PublicationLog inspection;
- token-protected admin endpoints to publish/unpublish posts in the public API;
- public read-only posts API for future site sections;
- idempotency by `telegram_chat_id + telegram_post_id`;
- tests for health, ingestion, idempotency, media metadata, PublicationJob rows, status lifecycle, public posts, and saved Post fields.

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

The optional publication status smoke checks DB-only status transitions and manual retry without starting workers or external publisher API calls.

Admin job endpoints are protected by `CONTENT_HUB_ADMIN_API_TOKEN` when it is set. In local development, if the token is empty, the endpoints are open for manual smoke checks.

Public post endpoints do not require an admin token and return only posts with `is_public=true` and `status!=error`. Responses include `is_public`, return metadata-only media fields, and do not expose Telegram file identifiers or storage keys.

See [docs/postgres_smoke.md](docs/postgres_smoke.md).

## CI

GitHub Actions runs on every push and pull request. The CI installs dependencies, runs the Content Hub pytest suite, compiles Python files, checks whitespace, applies Alembic migrations to a local PostgreSQL service, and runs the PostgreSQL smoke scripts.

CI uses test fixtures and a local `postgres:16-alpine` service only. It does not require real Telegram, Neon, S3, Instagram, VK, or Facebook credentials.

Branch protection requires the GitHub Actions `test` check before merging into `main`.

## Run App

```bash
.venv/bin/uvicorn content_hub.main:app --reload
```

## Run Migrations

```bash
CONTENT_HUB_DATABASE_URL=postgresql+psycopg://user:password@host:5432/db \
  .venv/bin/alembic -c content_hub/alembic.ini upgrade head
```
