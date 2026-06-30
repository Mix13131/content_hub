# Instagram API research

This note captures the first technical discovery for a future Instagram
Connector. It intentionally does not implement publishing, media uploads, or
worker behavior.

Official sources checked:

- Instagram Platform Content Publishing:
  https://developers.facebook.com/docs/instagram-platform/content-publishing/
- Instagram API with Instagram Login, Content Publishing:
  https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing/
- IG User media reference:
  https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media/
- IG User media_publish reference:
  https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media_publish/

## Supported account types

Instagram Content Publishing is for Instagram professional accounts:

- Instagram Business;
- Instagram Creator.

For the Facebook Login / Instagram Graph API path, the Instagram professional
account must be connected to a Facebook Page. The future connector should store
both IDs because Facebook Page discovery is often how the Instagram Business
Account ID is found and verified.

## What can be published

The documented publishing surface supports:

- single image posts;
- carousel posts with multiple child media containers;
- video/Reels posts;
- Stories.

Important details for MVP planning:

- Publishing is a two-step flow: create a media container, then publish that
  container.
- Carousel publishing creates child media containers first, then creates a parent
  `CAROUSEL` container with `children`.
- Reels and Stories use `media_type` values such as `REELS` and `STORIES`.
- Captions are passed to the media container. The exact current caption limits
  should be validated against Meta docs and staging API errors when credentials
  are available.
- Media must be accessible to Meta. For image publishing this usually means a
  public `image_url`; for videos/Reels/Stories this means a public `video_url` or
  the documented resumable upload flow.

## Main Content Hub risk

Content Hub currently stores Telegram media as metadata only:

- `telegram_file_id`;
- `telegram_file_unique_id`;
- dimensions;
- MIME type;
- duration;
- no downloaded file;
- no S3/R2 public URL.

That is not enough for Instagram publishing. The Instagram connector cannot
publish real photo/video posts until Content Hub has a media storage step that:

1. downloads media from Telegram;
2. stores it in S3/R2 or another externally reachable storage;
3. produces stable HTTPS URLs reachable by Meta;
4. keeps URLs valid long enough for retries and media processing.

## Minimal publish flow for future MVP

Single image:

1. `POST /{ig-user-id}/media`
   - `image_url=<public https image url>`;
   - optional `caption`;
   - access token.
2. Receive an Instagram container ID.
3. `POST /{ig-user-id}/media_publish`
   - `creation_id=<container id>`;
   - access token.
4. Store returned Instagram media ID and external URL if available.

Carousel:

1. Create a child container for each image/video with `is_carousel_item=true`.
2. Create parent container with `media_type=CAROUSEL` and `children=<ids>`.
3. Publish parent container through `media_publish`.

Reels:

1. Create media container with `media_type=REELS` and a public `video_url` or
   documented upload flow.
2. Publish through `media_publish`.

Stories:

1. Create media container with `media_type=STORIES` and an image/video source.
2. Publish through `media_publish`.

Stories are documented but should stay outside the first connector MVP because
the project roadmap keeps Stories out of MVP.

## Credentials and IDs needed

Environment placeholders:

```text
CONTENT_HUB_INSTAGRAM_ACCESS_TOKEN=
CONTENT_HUB_INSTAGRAM_ACCOUNT_ID=
CONTENT_HUB_FACEBOOK_PAGE_ID=
```

Operationally, the project also needs:

- Meta App with Instagram API / Instagram Graph API access configured;
- a long-lived access token suitable for server-side publishing;
- Instagram Business or Creator Account ID;
- Facebook Page ID linked to the Instagram professional account;
- app review/permissions approved for production use.

Expected permissions to verify during Meta setup:

- `instagram_basic`;
- `instagram_content_publish`;
- Facebook Page permissions needed to discover/read the linked Instagram account,
  commonly including page read/manage metadata permissions depending on the
  chosen login/token flow.

Exact permission names and app review requirements should be rechecked in the
Meta App dashboard for the selected API flow before implementation.

## Read-only proof-check

The safe local check script performs only read calls:

```bash
CONTENT_HUB_INSTAGRAM_ACCESS_TOKEN=... \
CONTENT_HUB_INSTAGRAM_ACCOUNT_ID=... \
CONTENT_HUB_FACEBOOK_PAGE_ID=... \
  .venv/bin/python scripts/instagram_api_check.py
```

It checks:

- Instagram account info by ID;
- Facebook Page info and linked Instagram business account when Page ID is set.

It must not:

- create media containers;
- publish media;
- upload files;
- delete anything.

## Open questions before real connector

- Is the client's Instagram account Business or Creator?
- Is it linked to the intended Facebook Page?
- Which token type will be used for production, and how will it be rotated?
- Which exact permissions are granted after app review?
- Will the first MVP support only single images, or also carousels and Reels?
- Which storage will provide public HTTPS media URLs: Cloudflare R2, Supabase
  Storage, or another CDN-backed option?
- How long should signed URLs live to cover container creation, media processing,
  retries, and manual retry from admin?

