# PostgreSQL / Neon smoke check

This check verifies Stage 1 Core ingestion against a real PostgreSQL-compatible database.

It covers:

- Alembic migration on PostgreSQL/Neon;
- PostgreSQL `uuid` columns for `id` and FK fields;
- PostgreSQL `jsonb` for `telegram_message_ids`;
- `timestamp with time zone` for Telegram and audit timestamps;
- status fields saved and read through SQLAlchemy;
- `/healthz`;
- `/webhooks/telegram`;
- idempotency by `telegram_chat_id + telegram_post_id`;
- saved `PublicationLog` row.

It does not cover media download, S3, Dramatiq, Instagram, VK, Facebook, admin UI, AI, Stories, WhatsApp, or media groups.

## Option A. Local PostgreSQL

Create a database and user by your preferred local PostgreSQL method, then export:

```bash
export CONTENT_HUB_DATABASE_URL='postgresql+psycopg://content_hub:content_hub@localhost:5432/content_hub'
export CONTENT_HUB_TELEGRAM_WEBHOOK_SECRET='local-smoke-secret'
```

Apply the migration:

```bash
.venv/bin/alembic -c content_hub/alembic.ini upgrade head
```

Run the smoke script:

```bash
.venv/bin/python scripts/postgres_webhook_smoke.py
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
```

Apply migration and run smoke:

```bash
.venv/bin/alembic -c content_hub/alembic.ini upgrade head
.venv/bin/python scripts/postgres_webhook_smoke.py
```

Stop the temporary database after the check:

```bash
docker stop content-hub-pg-smoke
```

## Option B. Neon

Use a Neon connection string with the `postgresql+psycopg://` SQLAlchemy driver prefix:

```bash
export CONTENT_HUB_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST.neon.tech/DB?sslmode=require'
export CONTENT_HUB_TELEGRAM_WEBHOOK_SECRET='neon-smoke-secret'
```

Apply the migration:

```bash
.venv/bin/alembic -c content_hub/alembic.ini upgrade head
```

Run the smoke script:

```bash
.venv/bin/python scripts/postgres_webhook_smoke.py
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
