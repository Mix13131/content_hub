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
CONTENT_HUB_TELEGRAM_BOT_TOKEN=
CONTENT_HUB_ADMIN_API_TOKEN=<random admin token>
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

Instagram variables are required only for real Instagram connector runs. The
current Instagram Connector MVP supports single-photo posts only and requires a
public HTTPS `Media.file_url` reachable by Meta. Keep these variables empty until
the Meta App, access token, Instagram Account ID, and media storage are ready.

Media storage is disabled by default. With `CONTENT_HUB_STORAGE_ENABLED=false`,
Content Hub keeps metadata-only media behavior and does not download Telegram
files or call S3-compatible storage. To enable it later, set a Telegram bot token
and S3-compatible credentials through Railway variables, then run the manual
check outside CI:

```bash
python scripts/media_storage_s3_check.py
```

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

Optional read-only Instagram API check, when credentials are available:

```bash
CONTENT_HUB_INSTAGRAM_ACCESS_TOKEN=<access token> \
CONTENT_HUB_INSTAGRAM_ACCOUNT_ID=<instagram account id> \
CONTENT_HUB_FACEBOOK_PAGE_ID=<facebook page id> \
  python scripts/instagram_api_check.py
```

This script does not create containers, publish media, upload files, or delete
anything. It must not be used as a deployment healthcheck because it depends on
Meta.

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
