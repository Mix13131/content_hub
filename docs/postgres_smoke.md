# PostgreSQL / Neon smoke check

This check verifies metadata-only core ingestion against a real PostgreSQL-compatible database.

It covers:

- Alembic migration on PostgreSQL/Neon;
- PostgreSQL `uuid` columns for `id` and FK fields;
- PostgreSQL `jsonb` for `telegram_message_ids`;
- `timestamp with time zone` for Telegram and audit timestamps;
- status fields saved and read through SQLAlchemy;
- text, photo, and video webhook fixtures;
- media rows for photo/video posts;
- Telegram media metadata such as `file_id`, `file_unique_id`, dimensions, MIME type, duration, and size;
- `media.file_url IS NULL`;
- `media.storage_key IS NULL`;
- nullable database columns for `media.file_url` and `media.storage_key`;
- `/healthz`;
- `/webhooks/telegram`;
- idempotency by `telegram_chat_id + telegram_post_id`;
- four `PublicationJob` rows per new post: website, Instagram, VK, and Facebook via Instagram sync;
- no duplicate jobs after repeated webhook delivery;
- unique `publication_jobs(post_id, platform)` constraint;
- `Post.status = queued` after jobs are created;
- DB-only publication job lifecycle: start, success, error, aggregate partial status, and manual retry;
- token-protected admin job API lifecycle: list, detail, start, success, error, retry;
- saved `PublicationLog` row.

It does not perform Telegram file downloads, S3 uploads, worker execution, or publisher API calls. It also does not cover Dramatiq, Instagram, VK, Facebook API, admin UI, AI, Stories, WhatsApp, or media groups.

## Option A. Local PostgreSQL

Create a database and user by your preferred local PostgreSQL method, then export:

```bash
export CONTENT_HUB_DATABASE_URL='postgresql+psycopg://content_hub:content_hub@localhost:5432/content_hub'
export CONTENT_HUB_TELEGRAM_WEBHOOK_SECRET='local-smoke-secret'
export CONTENT_HUB_ADMIN_API_TOKEN='local-admin-token'
```

Apply the migration:

```bash
.venv/bin/alembic -c content_hub/alembic.ini upgrade head
```

Run the smoke script:

```bash
.venv/bin/python scripts/postgres_webhook_smoke.py
.venv/bin/python scripts/publication_status_smoke.py
.venv/bin/python scripts/admin_jobs_smoke.py
```

### Local PostgreSQL via Docker

If you do not have a local PostgreSQL service, use a temporary Docker container:

```bash
docker run --rm -d --name content-hub-pg-smoke \
  -e POSTGRES_DB=content_hub \
  -e POSTGRES_USER=content_hub \
  -e POSTGRES_PASSWORD=content_hub \
  -p 55432:5432 \
  postgres:16-alpine
```

Wait until PostgreSQL is ready:

```bash
docker exec content-hub-pg-smoke pg_isready -U content_hub -d content_hub
```

Export the local Docker connection string:

```bash
export CONTENT_HUB_DATABASE_URL='postgresql+psycopg://content_hub:content_hub@127.0.0.1:55432/content_hub'
export CONTENT_HUB_TELEGRAM_WEBHOOK_SECRET='local-smoke-secret'
export CONTENT_HUB_ADMIN_API_TOKEN='local-admin-token'
```

Apply migration and run smoke:

```bash
.venv/bin/alembic -c content_hub/alembic.ini upgrade head
.venv/bin/python scripts/postgres_webhook_smoke.py
.venv/bin/python scripts/publication_status_smoke.py
.venv/bin/python scripts/admin_jobs_smoke.py
```

Real Telegram or storage credentials are not required for this check.

Stop the temporary database after the check:

```bash
docker stop content-hub-pg-smoke
```

## Option B. Neon

Use a Neon connection string with the `postgresql+psycopg://` SQLAlchemy driver prefix:

```bash
export CONTENT_HUB_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST.neon.tech/DB?sslmode=require'
export CONTENT_HUB_TELEGRAM_WEBHOOK_SECRET='neon-smoke-secret'
export CONTENT_HUB_ADMIN_API_TOKEN='neon-admin-smoke-token'
```

Apply the migration:

```bash
.venv/bin/alembic -c content_hub/alembic.ini upgrade head
```

Run the smoke script:

```bash
.venv/bin/python scripts/postgres_webhook_smoke.py
.venv/bin/python scripts/publication_status_smoke.py
.venv/bin/python scripts/admin_jobs_smoke.py
```

## Run API manually

Start the app:

```bash
.venv/bin/uvicorn content_hub.main:app --reload
```

Health check:

```bash
curl -s http://127.0.0.1:8000/healthz
```

Webhook example:

```bash
curl -s -X POST http://127.0.0.1:8000/webhooks/telegram \
  -H 'Content-Type: application/json' \
  -H "X-Telegram-Bot-Api-Secret-Token: ${CONTENT_HUB_TELEGRAM_WEBHOOK_SECRET}" \
  --data-binary @tests/content_hub/fixtures/telegram_text_channel_post.json
```

Expected first response:

```json
{"ok":true,"ignored":false,"created":true,"post_id":"...","reason":null}
```

Expected repeated response for the same fixture:

```json
{"ok":true,"ignored":false,"created":false,"post_id":"...","reason":"duplicate"}
```

Admin jobs example:

```bash
curl -s http://127.0.0.1:8000/admin/jobs \
  -H "X-Content-Hub-Admin-Token: ${CONTENT_HUB_ADMIN_API_TOKEN}"
```

## Check the database manually

With `psql`:

```bash
psql "$CONTENT_HUB_DATABASE_URL" -c "
select id, telegram_chat_id, telegram_post_id, text, status, telegram_posted_at
from posts
order by created_at desc
limit 5;
"
```

Column type check:

```bash
psql "$CONTENT_HUB_DATABASE_URL" -c "
select table_name, column_name, data_type, udt_name
from information_schema.columns
where table_schema = current_schema()
  and table_name in ('posts', 'media', 'publication_jobs', 'publication_logs')
  and column_name in ('id', 'post_id', 'telegram_message_ids', 'telegram_posted_at', 'created_at', 'status')
order by table_name, column_name;
"
```

Expected highlights:

- `posts.id` -> `uuid`;
- FK ids such as `media.post_id` -> `uuid`;
- `posts.telegram_message_ids` -> `jsonb`;
- `posts.telegram_posted_at` -> `timestamptz`;
- status columns -> `character varying` with SQLAlchemy enum validation in the app layer.
- `media.file_url` and `media.storage_key` are nullable columns and stay `NULL` in MVP smoke rows.

## Future storage check

Telegram file download and S3-compatible storage are not part of the current MVP. If a future stage adds them, create a separate staging smoke with real Telegram and storage credentials. Do not commit those values.
