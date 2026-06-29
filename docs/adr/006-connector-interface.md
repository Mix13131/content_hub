# ADR 006: Connector Interface

## Status

Accepted

## Context

Content Hub needs a stable boundary between publication orchestration and
platform-specific integrations. Different services have different capabilities:
some can publish, update, or delete content; some support albums or videos; some
need preflight validation before publication.

## Decision

Define a `Connector` protocol with:

- `name`;
- `capabilities()`;
- `validate(post, media)`;
- `publish(post, media)`;
- `update(post, media)`;
- `delete(external_post_id)`.

Connector methods return `ConnectorResult`, not ORM objects or raw exceptions as
their primary contract. A connector can report success, external IDs and URLs, a
safe raw response, or a controlled error.

## Consequences

The interface allows adding Tilda, WordPress, VK, Instagram, and other
connectors later with the same engine. Platform-specific details stay inside the
connector implementation. The dry-run Website connector proves the interface
without making external API calls.
