# ADR-002: One capture type, one pipeline

> **Note:** Backfilled from vision documentation; decision predates this record.

## Status

Accepted

## Date

2026-07-15

## Context

Early designs had separate `InboxNote` and `InboxAudio` classes with
independent processing paths — text notes went one way, audio transcriptions
another.  This duplicated the extraction pipeline, the provenance model, and
the status transitions.

The ADHD brain captures thoughts in many forms (text, voice, file uploads),
but the goal is always the same: turn a raw capture into structured, linked,
queryable entities.  Multiple capture types created friction — different
statuses, different polling sources, different idempotency guards.

## Decision

Use a single **`Captured`** kernel schema class (in `schema/modules/capture`)
that subsumes all capture forms. It carries:

- `content_type` (MIME style — `text/plain`, `audio/webm`, etc.)
- `content` (text, or transcription once available)
- `blob_sha256` (binary payload reference for file uploads)
- `file_name`, `captured_at`, `transcription`
- `status` — a single state machine: `new → transcribed → processed / failed / archived`

All captures — text notes, voice memos, files — flow through the same
extraction pipeline in `ingestd`, share the same `derived_from` provenance
chain, and use the same idempotency guard (check `Entity.derived_from` for
already-processed capture IRIs).

The **webui inbox page** is backed directly by the `Captured` class.

## Alternatives considered

- **Multiple capture sub-classes** (one per content type) — rejected because
  it would duplicate the pipeline and status machine for every new capture
  format.
- **Generic `InboxItem` with pluggable type handlers** — closer to the chosen
  design, but the single `Captured` class with a discriminator field is
  simpler and avoids extra schema complexity.
- **Separate services per capture type** — not recorded.

## Consequences

- **Easier**: one status state machine, one idempotency guard, one extraction
  loop to maintain. Adding a new capture format means adding a handler plugin
  (in `captured`) and optionally an ingest source plugin (in `ingestd`) — no
  schema changes.
- **Harder**: the single `Captured` class must carry fields for every capture
  form (e.g. `transcription` for audio, `blob_sha256` for files). Some fields
  will be null for some content types; the schema documents which fields
  apply when.
- **Constraint**: all capture handlers and ingest sources must agree on the
  `Captured` schema; changing it is a kernel schema change.

## References

- [Architecture](../concepts/architecture.md)
- [Data Model](../concepts/data-model.md)
