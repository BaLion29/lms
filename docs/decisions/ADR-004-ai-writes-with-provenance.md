# ADR-004: AI writes with provenance

> **Note:** Backfilled from vision documentation; decision predates this record.

## Status

Accepted

## Date

2026-07-15

## Context

The system delegates entity extraction to LLMs — `ingestd` sends captured text
to an AI model and materializes `Task`, `Event`, `Person`, and `Reminder`
documents from the output.  Without attribution, an AI-created document is
indistinguishable from a human-created one, making it impossible to audit,
review, or revert.

The user must always be able to answer "where did this come from?" and trace
any document back through the capture → extraction → storage chain.  AI
actions must never be invisible or unattributed.

## Decision

Every `Entity` carries exactly **one required `Provenance`** subdocument — the
birth certificate.  `Provenance` fields:

- `agent` — reserved naming grammar: `service:<name>`, `user:<name>`,
  `ext:<name>`.  Helper functions `agent_id()` / `parse_agent()` in
  `firnline_core.conventions` enforce this.
- `at` — `xsd:dateTime` (when the document was created)
- `method` — optional (e.g. `gpt-4o`, `manual`)
- `confidence` — optional (0–1, AI confidence)

Multi-source derivation lives in `Entity.derived_from: Set<Source>` (n-ary),
not on the provenance subdocument.  The `source` field was removed — a
document can be derived from multiple sources (e.g. a voice memo *and* a
calendar event).

AI commits use `author=<service>` (e.g. `author=service:ingestd`) and one
commit per captured item.  The **commit graph is the biography**: updates are
attributed there, deliberately not on the document.  Branch promotion to
`main` is the "accept" action.

The trust ladder: dry-run (real reads, real LLM calls, no writes) → staging
branch (review before promote) → direct-to-main (earned trust).

## Alternatives considered

- **Soft provenance (optional field, best-effort)** — rejected because
  optional provenance means some documents will be unattributed, defeating the
  audit trail.
- **Provenance on the commit only, not the document** — rejected because
  commit-level attribution requires walking the commit graph to answer "who
  created this?" — the document-level birth certificate gives a direct answer.
- **Separate audit log service** — rejected as over-engineering when
  TerminusDB's commit graph already provides immutable history.

## Consequences

- **Easier**: one-click source chain in the UI, idempotency via
  `derived_from` lookup, audit trail for every document, branch-based review
  workflow.
- **Harder**: every `Repository.create()` call must supply provenance.
  Extractor plugins must populate provenance correctly.  The agent grammar
  (`service:`, `user:`, `ext:`) is a system-wide convention that all code
  must respect.
- **Constraint**: provenance fields cannot be removed or relaxed — they are
  a kernel schema guarantee.

## References

- [Architecture](../concepts/architecture.md) — Principles, Source Code Layout
- [Data Model](../concepts/data-model.md)
- [Vision](../concepts/vision.md) — Source & Provenance section
