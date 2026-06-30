# Railway deployment

This guide prepares a staging deployment for Content Hub on Railway with a
PostgreSQL-compatible database, such as Neon.

## 1. Create the Railway project

1. Open Railway and create a new project.
2. Choose **Deploy from GitHub repo**.
3. Select `Mix13131/content_hub`.
4. Use the `main` branch for staging unless a separate staging branch is created.

## 2. Service start command

The repository includes a `Procfile`:

```text
web: uvicorn content_hub.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

If Railway asks for a start command explicitly, use:

```bash
uvicorn content_hub.main:app --host 0.0.0.0 --port $PORT
```

## 3. Environment variables

Set these variables in Railway. Do not commit real secrets to the repository.

```text
CONTENT_HUB_ENVIRONMENT=staging
CONTENT_HUB_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require
CONTENT_HUB_TELEGRAM_WEBHOOK_SECRET=<random webhook secret>
CONTENT_HUB_ADMIN_API_TOKEN=<random admin token>
CONTENT_HUB_ALLOWED_TELEGRAM_CHAT_IDS=-1003777865636
CONTENT_HUB_TILDA_PUBLIC_KEY=
CONTENT_HUB_TILDA_SECRET_KEY=
CONTENT_HUB_TILDA_PROJECT_ID=
CONTENT_HUB_TILDA_TARGET_PAGE_ID=
```

`CONTENT_HUB_DATABASE_URL` should point to Neon or another PostgreSQL-compatible
database. Use the SQLAlchemy `postgresql+psycopg://` driver prefix.

`CONTENT_HUB_ALLOWED_TELEGRAM_CHAT_IDS` is optional. When it is empty or unset,
Content Hub accepts Telegram `channel_post` and `message` updates from any chat.
When it is set, use one Telegram chat ID or a comma-separated list. Updates from
other chats are ignored with `reason=chat_not_allowed` and do not create posts,
media, or publication jobs. Invalid values fail settings validation on startup so
the deployment shows a configuration error instead of silently accepting all
sources.

Tilda variables are placeholders for a future real connector. The current Tilda
connector is preview-only and does not call Tilda API. Do not add real Tilda
keys until a read-only check or a future connector task needs them.

## 4. Run migrations

Migrations are intentionally not run automatically during web app startup.

Run this Railway command after setting `CONTENT_HUB_DATABASE_URL`:

```bash
python scripts/run_migrations.py
```

Equivalent direct Alembic command:

```bash
python -m alembic -c content_hub/alembic.ini upgrade head
```

## 5. Healthcheck

Use this endpoint for Railway health checks:

```text
/healthz
```

Expected response:

```json
{"status":"ok"}
```

## 6. Verify staging

After deployment and migrations, open:

```text
https://<railway-domain>/healthz
https://<railway-domain>/news
https://<railway-domain>/api/posts/public
```

Check the admin endpoint with the token:

```bash
curl -H "X-Content-Hub-Admin-Token: $CONTENT_HUB_ADMIN_API_TOKEN" \
  https://<railway-domain>/admin/posts
```

Run a website publication job manually through the internal Connector Engine:

```bash
curl -s -X POST https://<railway-domain>/admin/posts/{post_id}/run/website \
  -H "X-Content-Hub-Admin-Token: ${CONTENT_HUB_ADMIN_API_TOKEN}"
```

After success, the connector sets `is_public=true` and the page should be visible:

```bash
curl -s https://<railway-domain>/news/{slug}
```

You can also run the deployed smoke script from a local machine:

```bash
CONTENT_HUB_BASE_URL=https://<railway-domain> \
CONTENT_HUB_ADMIN_API_TOKEN=<admin token> \
  .venv/bin/python scripts/deployed_smoke.py
```

If `CONTENT_HUB_ADMIN_API_TOKEN` is omitted, the smoke script skips the admin
endpoint and checks only public endpoints.

Optional read-only Tilda API check, when credentials are available:

```bash
CONTENT_HUB_TILDA_PUBLIC_KEY=<public key> \
CONTENT_HUB_TILDA_SECRET_KEY=<secret key> \
CONTENT_HUB_TILDA_PROJECT_ID=<project id> \
  python scripts/tilda_api_check.py
```

This script only calls documented read/export discovery endpoints. It must not
be used as a deployment healthcheck because it depends on an external service.

## 7. Telegram webhook later

After the staging URL is stable, configure the Telegram bot webhook with the same
secret as `CONTENT_HUB_TELEGRAM_WEBHOOK_SECRET`.

Example shape:

```bash
curl "https://api.telegram.org/bot<bot-token>/setWebhook" \
  -d "url=https://<railway-domain>/webhooks/telegram" \
  -d "secret_token=$CONTENT_HUB_TELEGRAM_WEBHOOK_SECRET" \
  -d 'allowed_updates=["channel_post","message","edited_channel_post"]'
```

Do not store the bot token in GitHub or documentation.
