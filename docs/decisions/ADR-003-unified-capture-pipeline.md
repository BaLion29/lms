# ADR-003: Unified Capture Pipeline

**Status:** Accepted (recorded retroactively)

**Date:** 2026-07-15

## Context

The core user experience for an ADHD brain is *frictionless capture*:
thoughts are fleeting and must be recorded in under 5 seconds. The user
should not need to classify, tag, or structure anything at capture time —
that work is delegated to AI. The original design had separate document
types for text notes (`InboxNote`) and audio memos (`InboxAudio`), and
potentially different pipelines for each, but this created divergent code
paths and status flows.

## Decision

A **single `Captured` kernel schema class** subsumes all capture types. It
lives in `schema/modules/capture` (a kernel module — capture ships with core
because the capture raison d'être is fundamental). Every capture — text
note, voice memo, file upload — becomes a `Captured` document with:

- `content_type` (MIME style) — distinguishes text vs audio vs other.
- `content` (text) — the raw or transcribed text.
- `blob_sha256` — content-addressed binary storage for audio/files.
- `file_name`, `captured_at`, `transcription`.
- `status`: `new → transcribed → processed → failed → archived`.

All captures flow through the **same extraction pipeline**: `ingestd` polls
for `Captured` documents, sends the text to an LLM with typed output schemas
(provided by extractor plugins), and materializes validated `Task`, `Event`,
`Reminder`, `Person` documents. Statuses *are* the work queue — the database
is the only integration point.

Capture ingress is through a minimal FastAPI service (`captured`) with
two endpoints — `POST /v1/capture/note` and `POST /v1/capture/file` — each
dispatched to pluggable handler plugins.

## Alternatives considered (reconstructed)

| Alternative | Why rejected |
|---|---|
| **Per-type forms/endpoints (note endpoint, audio endpoint, photo endpoint…)** | Requires UI and API surface growth for every new capture medium. Forces the user to choose a type at capture time, adding friction. Divergent status flows and processing logic per type. |
| **Client-side structuring** | Shifts classification burden to the user at the moment of capture — the exact friction the system exists to eliminate. Requires a rich capture UI that knows about all entity types. |
| **Separate inbox and audio tables** | The original `InboxNote`/`InboxAudio` split. Created two classes, two polling loops, two status graphs. Unifying into `Captured` with `content_type` eliminated all duplication while preserving type-specific handling at the extraction layer. |
| **Event-sourcing / append-only log without status fields** | Would require external queue infrastructure. Status-in-document means the database *is* the queue — one fewer moving part. |

## Consequences

- **Easier:** One class means one polling source, one status lifecycle, one
  provenance path. New capture media types (screen recording, photo+text) add
  a MIME type, not a new schema class. The WebUI inbox page is backed by a
  single class query. Extraction plugins receive uniform `Captured` documents.
- **Harder:** The `content_type` field must be kept in sync with extraction
  logic — extractors may need to handle different content shapes. Binary
  blobs require the `BlobStore` abstraction alongside text content.
- **ADHD-specific:** Capture costs < 5 seconds because the user just speaks
  or types — no decisions, no forms, no categories. Processing happens later.

## References

- [Vision](../concepts/vision.md) — One capture type, one pipeline
- [Architecture](../concepts/architecture.md) — Data Flow, captured service
- [Plugin System](../concepts/plugin-system.md) — CaptureHandler protocol
