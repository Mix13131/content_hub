# ADR 007: Publication Pipeline

## Status

Accepted

## Context

The publication pipeline must preserve failure isolation. A failed Instagram or
VK integration must not block website publication or other jobs. Content Hub
already models this through independent `PublicationJob` rows and platform
status fields on `Post`.

## Decision

Use this pipeline for each job:

1. Queue or admin code selects one `PublicationJob`.
2. `ConnectorEngine` maps `PublicationJob.platform` to a connector name.
3. `ConnectorRegistry` returns the connector.
4. `PublicationStatusService.start_job` marks the job as `Publishing`.
5. The connector validates and publishes the post/media.
6. `PublicationStatusService` records success, retry, or error and refreshes the
   aggregate `Post` status.

Only the Website connector is registered by default for now. Unknown connector
jobs fail in a controlled way and are retried or marked error through existing
retry logic.

## Consequences

The first pipeline is dry-run. It exercises status transitions, logs, external
ID/URL persistence, and aggregate status updates without Tilda, WordPress, VK,
Instagram, Facebook, S3, Telegram file download, workers, or Redis.
