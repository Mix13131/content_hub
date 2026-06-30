# Tilda API research

This note captures the first technical discovery for a future real Tilda
Connector. It intentionally does not define or implement write calls.

Official sources checked:

- Tilda API Help Center: https://help.tilda.cc/api
- Tilda API landing page: https://tilda.cc/lp/api/

## What the public API documentation supports

The documented API base URL is:

```text
https://api.tildacdn.info/v1
```

All documented requests use `GET` and require:

- `publickey`;
- `secretkey`;
- optionally `projectid`;
- optionally `pageid`.

Documented read/export endpoints relevant to Content Hub:

| Need | Endpoint | Notes |
|---|---|---|
| List projects | `/v1/getprojectslist/` | Auth check and project discovery. |
| Project info | `/v1/getprojectinfo/` | Requires `projectid`; returns project metadata and export paths. |
| List project pages | `/v1/getpageslist/` | Requires `projectid`; returns page IDs, titles, aliases, filenames, published timestamps. |
| Page body HTML | `/v1/getpage/` | Requires `pageid`; returns page metadata, body HTML, JS/CSS references. |
| Full page HTML | `/v1/getpagefull/` | Requires `pageid`; returns page metadata and full-page HTML. |
| Page export body HTML | `/v1/getpageexport/` | Requires `pageid`; intended for exporting a page and related assets. |
| Page export full HTML | `/v1/getpagefullexport/` | Requires `pageid`; intended for exporting a full page and related assets. |

Successful responses use `status="FOUND"`. Error responses use
`status="ERROR"` with additional error details.

## Write capabilities discovery

The public Help Center API page does not document endpoints for:

- creating a new page in Tilda;
- updating an existing Tilda page;
- adding or replacing a Tilda HTML block;
- publishing a Tilda page through the API.

The documented flow is the opposite direction: a page is created and published in
Tilda, then Tilda can notify an external server with a callback, and the external
server can read/export the published content via API.

Because of that, a real Content Hub -> Tilda publishing connector should not be
built until one of these is confirmed:

1. Tilda support/account documentation provides a write API for this account.
2. The project accepts a manual Tilda step where a target page/block is prepared
   and updated by some supported non-public mechanism.
3. The MVP changes direction and uses Tilda as a source/export system rather
   than as a destination.

## Tariff and rate limits

The official Help Center states that API access is available for Tilda Business
Plan subscribers. It also documents a request limit of 150 API requests per hour
and warns against requesting Tilda API on every visitor page view.

For Content Hub this means:

- never call Tilda API from public page rendering;
- keep Tilda API calls in admin/manual/worker flows only;
- cache or persist any data needed for public display;
- keep future smoke checks read-only and optional.

## Callback behavior

Tilda can call a configured webhook/callback when a page is published in Tilda.
The documented callback uses `GET` and includes:

- `pageid`;
- `projectid`;
- `published`;
- `publickey`.

The receiver should respond with `ok`. Tilda may retry if the response is not
received, and the callback can arrive with a delay after page publishing.

This callback is useful if Content Hub later needs to synchronize Tilda-created
pages into Content Hub. It does not solve Content Hub publishing generated pages
to Tilda.

## Environment variables for future integration

Content Hub placeholders:

```text
CONTENT_HUB_TILDA_PUBLIC_KEY=
CONTENT_HUB_TILDA_SECRET_KEY=
CONTENT_HUB_TILDA_PROJECT_ID=
CONTENT_HUB_TILDA_TARGET_PAGE_ID=
```

The local read-only check script also accepts legacy/local aliases:

```text
TILDA_PUBLIC_KEY=
TILDA_SECRET_KEY=
TILDA_PROJECT_ID=
TILDA_TARGET_PAGE_ID=
```

Secrets must stay in local shell or deployment secret storage only.

## What should exist in Tilda before real implementation

Before implementing a real connector, prepare or confirm:

- Business Plan with API access enabled;
- Public Key and Secret Key from Site Settings -> Export -> API Integration;
- project ID for the target site;
- target page ID if the future flow updates or inspects a specific page;
- confirmation from Tilda support/docs that write operations are available, if
  Content Hub must create or update Tilda pages automatically.

## Proposed first MVP flow

Safe first step:

1. Keep current `TildaConnector` in preview mode.
2. Render Content Hub HTML locally with the existing renderer.
3. Use `scripts/tilda_api_check.py` only for read-only account/project/page
   discovery.
4. Ask Tilda/support or verify account docs for real write/publish capability.

Only after write support is confirmed:

1. Decide whether the connector creates a new Tilda page or updates a manually
   prepared target page.
2. Add a dedicated adapter method with idempotency and audit logs.
3. Keep all write calls outside CI and behind explicit admin/worker actions.
