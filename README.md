# Content Hub

[![CI](https://github.com/Mix13131/content_hub/actions/workflows/ci.yml/badge.svg)](https://github.com/Mix13131/content_hub/actions/workflows/ci.yml)

Content Hub is a FastAPI backend for ingesting posts from a Telegram channel and preparing them for automatic publication to a website and social platforms.

Current implementation covers core ingestion with optional media storage:

- FastAPI application;
- `/healthz`;
- `/webhooks/telegram`;
- Pydantic Settings;
- SQLAlchemy models;
- Alembic migration;
- text/photo/video `channel_post` and `message` ingestion;
- optional Telegram chat ID allowlist for webhook ingestion;
- media metadata for Telegram photo/video posts;
- optional Media Storage Engine with S3-compatible first implementation;
- PublicationJob creation for website, Instagram, VK, and Facebook via Instagram sync;
- DB-only PublicationJob status and retry lifecycle service;
- Connector Engine foundation with internal website, Tilda preview, and
  Instagram single-photo connectors;
- minimal token-protected admin API endpoints for PublicationJob lifecycle checks;
- token-protected admin endpoints to run a PublicationJob manually through the Connector Engine;
- read-only admin API endpoints for Post, Media, PublicationJob, and PublicationLog inspection;
- token-protected admin endpoints to publish/unpublish posts in the public API;
- public read-only posts API for future site sections;
- idempotency by `telegram_chat_id + telegram_post_id`;
- tests for health, ingestion, idempotency, media metadata, PublicationJob rows, status lifecycle, public posts, and saved Post fields.

Not implemented yet:

- Dramatiq workers;
- publisher workers;
- Instagram carousel/video/Reels publishing;
- VK and Facebook publishing;
- admin panel;
- AI, Stories, WhatsApp.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

By default media handling is metadata-only: Content Hub stores Telegram `file_id`,
`file_unique_id`, dimensions, MIME type, duration, and source Telegram URL.
Set `CONTENT_HUB_STORAGE_ENABLED=true` to enable the Media Storage Engine. The
first provider is S3-compatible storage; it downloads media through Telegram Bot
API and stores externally reachable `file_url` / `storage_key` values.

## Run Tests

```bash
.venv/bin/python -m pytest tests/content_hub -q
```

## PostgreSQL / Neon Smoke

Core ingestion should be checked against a real PostgreSQL-compatible database before worker or publisher work.

The optional publication status smoke checks DB-only status transitions and manual retry without starting workers or external publisher API calls.

Admin job endpoints are protected by `CONTENT_HUB_ADMIN_API_TOKEN` when it is set. In local development, if the token is empty, the endpoints are open for manual smoke checks.

Manual Connector Engine run endpoints execute existing `PublicationJob` rows without a
worker, Redis, or external API calls. The website connector is internal: it publishes
a post to the Content Hub website by setting `is_public=true`, preserving the job
result, and returning an internal `/news/{slug}` URL:

```bash
curl -s -X POST https://web-production-6c604.up.railway.app/admin/posts/{post_id}/run/website \
  -H "X-Content-Hub-Admin-Token: ${CONTENT_HUB_ADMIN_API_TOKEN}"
```

After a successful website run, verify the public page:

```bash
curl -s https://web-production-6c604.up.railway.app/news/{slug}
```

Tilda preview is internal-only and does not call Tilda API. It renders the
generated page HTML for an existing post:

```bash
curl -s https://web-production-6c604.up.railway.app/preview/tilda/{post_id} \
  -H "X-Content-Hub-Admin-Token: ${CONTENT_HUB_ADMIN_API_TOKEN}"
```

Tilda API research notes are in [docs/tilda_api_research.md](docs/tilda_api_research.md).
The optional read-only API check is not part of CI and does not create, update,
publish, or delete Tilda pages:

```bash
CONTENT_HUB_TILDA_PUBLIC_KEY=... \
CONTENT_HUB_TILDA_SECRET_KEY=... \
CONTENT_HUB_TILDA_PROJECT_ID=... \
  .venv/bin/python scripts/tilda_api_check.py
```

Instagram Connector MVP supports only single-photo feed posts. It requires an
existing `Media.file_url` with a public HTTPS URL reachable by Meta. The
connector creates an Instagram media container, publishes it, and stores the
returned Instagram media ID plus permalink when Meta returns one. Carousel,
video, Reels, Stories, and Facebook sync are intentionally outside this MVP.

Required Instagram env vars:

```text
CONTENT_HUB_INSTAGRAM_ACCESS_TOKEN=
CONTENT_HUB_INSTAGRAM_ACCOUNT_ID=
CONTENT_HUB_FACEBOOK_PAGE_ID=
CONTENT_HUB_META_GRAPH_API_BASE_URL=https://graph.facebook.com/v25.0
```

Manual run through the existing admin connector endpoint:

```bash
curl -s -X POST https://hub.zubdakosti.ru/admin/posts/{post_id}/run/instagram \
  -H "X-Content-Hub-Admin-Token: ${CONTENT_HUB_ADMIN_API_TOKEN}"
```

The fake Instagram connector smoke is part of CI and does not call Meta. The
read-only Instagram account check remains optional and outside CI:

```bash
CONTENT_HUB_INSTAGRAM_ACCESS_TOKEN=... \
CONTENT_HUB_INSTAGRAM_ACCOUNT_ID=... \
CONTENT_HUB_FACEBOOK_PAGE_ID=... \
  .venv/bin/python scripts/instagram_api_check.py
```

Public post endpoints do not require an admin token and return only posts with
`is_public=true` and `status!=error`. Responses include `is_public` and safe
media fields such as `file_url`, but do not expose Telegram file identifiers or
storage keys.

See [docs/postgres_smoke.md](docs/postgres_smoke.md).

## CI

GitHub Actions runs on every push and pull request. The CI installs dependencies, runs the Content Hub pytest suite, compiles Python files, checks whitespace, applies Alembic migrations to a local PostgreSQL service, and runs the PostgreSQL smoke scripts.

CI uses test fixtures and a local `postgres:16-alpine` service only. It does not require real Telegram, Neon, S3, Instagram, VK, or Facebook credentials.

Branch protection requires the GitHub Actions `test` check before merging into `main`.

## Run App

```bash
.venv/bin/uvicorn content_hub.main:app --reload
```

Railway can run the app through the included `Procfile`:

```text
web: uvicorn content_hub.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Required staging env vars are listed in `.env.example`:

```text
CONTENT_HUB_ENVIRONMENT=staging
CONTENT_HUB_DATABASE_URL=
CONTENT_HUB_TELEGRAM_WEBHOOK_SECRET=
CONTENT_HUB_TELEGRAM_BOT_TOKEN=
CONTENT_HUB_ADMIN_API_TOKEN=
CONTENT_HUB_ALLOWED_TELEGRAM_CHAT_IDS=-1003777865636
CONTENT_HUB_MEDIA_STORAGE_PROVIDER=s3
CONTENT_HUB_STORAGE_ENABLED=false
CONTENT_HUB_S3_ENDPOINT_URL=
CONTENT_HUB_S3_ACCESS_KEY_ID=
CONTENT_HUB_S3_SECRET_ACCESS_KEY=
CONTENT_HUB_S3_BUCKET=
CONTENT_HUB_S3_REGION=
CONTENT_HUB_S3_PUBLIC_BASE_URL=
CONTENT_HUB_TILDA_PUBLIC_KEY=
CONTENT_HUB_TILDA_SECRET_KEY=
CONTENT_HUB_TILDA_PROJECT_ID=
CONTENT_HUB_TILDA_TARGET_PAGE_ID=
CONTENT_HUB_INSTAGRAM_ACCESS_TOKEN=
CONTENT_HUB_INSTAGRAM_ACCOUNT_ID=
CONTENT_HUB_FACEBOOK_PAGE_ID=
CONTENT_HUB_META_GRAPH_API_BASE_URL=https://graph.facebook.com/v25.0
```

`CONTENT_HUB_ALLOWED_TELEGRAM_CHAT_IDS` is optional. Leave it empty to accept
all Telegram `channel_post` and `message` updates. Set one ID or a comma-separated
list, for example `-1003777865636,-1234567890`, to ignore updates from any other
Telegram chat with `reason=chat_not_allowed`.

When `CONTENT_HUB_STORAGE_ENABLED=false`, the app keeps the metadata-only
behavior and does not call Telegram file download or S3-compatible storage. The
manual S3-compatible check is outside CI:

```bash
CONTENT_HUB_STORAGE_ENABLED=true \
CONTENT_HUB_MEDIA_STORAGE_PROVIDER=s3 \
CONTENT_HUB_S3_ENDPOINT_URL=... \
CONTENT_HUB_S3_ACCESS_KEY_ID=... \
CONTENT_HUB_S3_SECRET_ACCESS_KEY=... \
CONTENT_HUB_S3_BUCKET=... \
CONTENT_HUB_S3_PUBLIC_BASE_URL=... \
  .venv/bin/python scripts/media_storage_s3_check.py
```

## Run Migrations

```bash
CONTENT_HUB_DATABASE_URL=postgresql+psycopg://user:password@host:5432/db \
  .venv/bin/alembic -c content_hub/alembic.ini upgrade head
```

The same migration can be run through:

```bash
CONTENT_HUB_DATABASE_URL=postgresql+psycopg://user:password@host:5432/db \
  .venv/bin/python scripts/run_migrations.py
```

## Deployment

Railway staging deployment notes are in
[docs/deployment_railway.md](docs/deployment_railway.md).

After deploy, run a public HTTP smoke check:

```bash
CONTENT_HUB_BASE_URL=https://example.up.railway.app \
CONTENT_HUB_ADMIN_API_TOKEN=admin-token \
  .venv/bin/python scripts/deployed_smoke.py
```
