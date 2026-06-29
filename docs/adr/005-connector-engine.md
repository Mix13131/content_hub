# ADR 005: Connector Engine

## Status

Accepted

## Context

Content Hub receives content once from Telegram and creates independent
`PublicationJob` rows for each target platform. The job table should track
publication state, retries, external IDs, URLs, and API responses, but it should
not know how a specific platform publishes content.

The original specification used the term publisher for platform adapters. We use
Connector for the integration boundary because the same boundary may later cover
more than publishing: update, delete, validation, media checks, status polling,
and vendor-specific capabilities.

## Decision

Introduce a Connector Engine that executes `PublicationJob` rows through a
registry of named connectors. The engine owns orchestration:

- load job, post, and media;
- resolve platform to connector name;
- start the job through `PublicationStatusService`;
- call the connector;
- mark success, retry, or error through `PublicationStatusService`.

The engine must not import concrete future API clients such as Tilda, WordPress,
VK, Instagram, or Facebook SDKs. It talks only to connector interfaces and a
registry.

## Consequences

`PublicationJob` remains a platform-neutral state record. Future platform
integrations can be added by implementing a connector and registering it without
rewriting queue/status logic.

The first implementation is intentionally internal-only. The Website connector
publishes into Content Hub itself by making the post public and returning the
local `/news/{slug}` URL. This keeps the interface testable on CI and staging
without requiring external credentials or network calls.
