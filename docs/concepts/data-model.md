# Data model

## Purpose

This page explains the entity model at the heart of firnline — the abstract
markers that structure everything, the design ideas behind provenance and
context, and how the data-model choices support traceability, extensibility,
and trust in AI-generated content. It is for anyone designing schemas,
writing extensions, or reasoning about how data is stored and linked.

## The entity model

Four abstract markers structure everything:

- **`Source`** — "things other things can be derived from" (traceability)
- **`Context`** — "things other things can be tagged with" (flat association)
- **`Anchored`** — "things with a canonical temporal instant" (pure role marker; concrete classes declare the anchor field via `@metadata.anchor_field`)
- **`Trigger`** — "conditions that fire" (abstract root of the trigger family)

`Remindable` has been **removed** from core — reminders are an extension
concern, not kernel. Extensions that need reminder-attachment semantics define
their own markers or use `Triggerable` (from the triggers module).

```
┌────────────────────────────────────────────────────────────────────┐
│ CAPTURE (module: capture)                                          │
│   Captured  ── Source   content_type · content · blob_sha256       │
│              file_name · captured_at · transcription               │
│              status: new→transcribed→processed→failed→archived     │
└───────────────────────────┬────────────────────────────────────────┘
                            │ ingestd: LLM extraction + entity linking
                            ▼
┌────────────────────────────────────────────────────────────────────┐
│ CORE ENTITIES                                                      │
│                                                                    │
│  time_management:                                                  │
│   Task      ── Source+TaskSpec                                     │
│              provenance · due_date · status(open/planned/done)     │
│   Event     ── Source+Context  (an event IS a context)             │
│              start/end · location→Location · status                │
│   Routine   ── steps: List<RoutineStep> · trigger                  │
│   RoutineStep ── @oneOf task:TaskSpec | activity:ActivitySpec      │
│   Activity  ── Source+Context+ActivitySpec · routine→Routine       │
│   Reminder  ── refer_to · trigger→Trigger (optional, extension)   │
│                                                                    │
│  address_book:                                                     │
│   Person         ── Source+Context · Contact (@subdocument, inline)│
│   Location       ── Context · aliases · coordinates                │
│   Organization   ── Context · employees                            │
│   Affiliation    ── @subdocument · org→Organization · role         │
└────────────────────────────────────────────────────────────────────┘
```

## Design ideas

### Source & Provenance (traceability)

Every Entity carries exactly **one required** `Provenance` subdocument — the
birth certificate. Fields: `agent` (reserved grammar: `service:<name>`,
`user:<name>`, `ext:<name>`), `at` (xsd:dateTime), `method` (optional),
`confidence` (optional). Multi-source derivation lives in
`Entity.derived_from: Set<Source>` (n-ary). Updates are attributed via the
commit graph (the biography), deliberately not on the document. You can always
answer "where did this come from?" — and the frontend surfaces this as a
one-click source chain. The `derived_from` link doubles as the idempotency
guard: before processing a captured item, ingestd queries `Entity` /
`derived_from` to detect already-extracted documents.

### Anchored + Trigger

Reminders are an extension concern. The kernel provides `Anchored` (a pure
role marker — no `anchor_at` field) and the triggers module provides
`Triggerable` (a mixin for things that own a trigger). Concrete classes
implementing `Anchored` declare `@metadata.anchor_field` at the class level;
the composer validates this. If the anchor field is unset on a document,
relative triggers referencing it are **dormant** — evaluators skip them
explicitly.

Reminders are standalone entities that refer to domain documents. *When* they
fire is fully delegated to the Trigger family — recurring schedules (RFC 5545
rrule), offsets relative to an `Anchored` entity's anchor field, event triggers
over the kernel change feed, and boolean composition of all of these. The
trigger lifecycle (pending → notified → renotify → expire → snoozed) is fully
materialised and enforced by `triggerd` + `effectd`.

### Context (flat, multi-valued tagging)

A Context is anything a Task or Event relates to: a Person, a Location, an
Event, a future custom context. No hierarchies — just associations, as many as
needed. The extraction layer links known contexts automatically
(case-insensitive exact match; near-misses are logged, not guessed).

### Event inherits Context

An Event (like "Dentist appointment") is both something that happens AND a
context that other things can be associated with. "Buy toothpaste" can have
`required_context: [Event:Dentist, Person:Topias]`.

### One capture type, one pipeline

**Captured** is a single kernel schema class in `schema/modules/capture` that
subsumes all capture forms. It carries `content_type` (MIME style), `content`
(text), `blob_sha256` (binary), `file_name`, `captured_at`, `transcription`,
and `status` (new/transcribed/processed/failed/archived). All captures — text
notes, voice memos, files — flow through the same extraction pipeline, the same
provenance model, and the same statuses. The **webui inbox page** is backed
by the `Captured` class.

### AI writes with provenance; branches are the review boundary

The trust ladder controls how AI writes are accepted:

1. **Dry-run** — real reads, real LLM calls, no writes (`INGESTD_DRY_RUN=true`).
2. **Staging branch** — `TDB_BRANCH` points ingestd at a non-main branch;
   promotion to main is the "accept" action.
3. **Direct-to-main** — earned trust; every write remains attributed,
   provenance-linked, and revertible via the commit graph.

### Modules and plugins are the growth mechanism

The schema is not one file: it is composed from versioned **schema modules**
with declared dependencies, semver discipline, and an in-database registry.
Services discover **plugins** (extractors for ingestd, tools for queryd) via
entry points and verify each plugin's module requirements at startup. See
[architecture](../concepts/architecture.md) for the full extension model.

## Related documents

- [Architecture](../concepts/architecture.md) — schema module system and plugin mechanism
- [Vision](../concepts/vision.md) — design principles and the core problem
- [Design decisions](../decisions/README.md) — formalised ADRs for provenance, anchoring, and module design
- [Reference: configuration](../reference/configuration.md) — environment variables controlling dry-run mode and branch targeting
