# Entity Model

The abstract markers and design rules that structure every document in the
graph.

## Overview

Four abstract markers structure everything in the firnline graph. They are
defined in the `core` schema module, alongside the universal `Entity` base,
and deliberately carry **no fields** — they are pure role markers that enable
type-safe graph queries and composer validation.

## The Four Markers

### `Source`

> "things other things can be derived from"

A **role marker** for any document that serves as a traceability root.
`Captured`, `Task`, and `Event` all carry `Source`. The `Entity.derived_from:
Set<Source>` field (n-ary) lets any document reference the upstream things it
was derived from. This replaces the earlier single `Provenance.source` field
(removed in the marker grammar refactor).

### `Context`

> "things other things can be tagged with"

A **role marker** for things that other entities relate to. `Person`,
`Location`, and `Event` implement `Context`. The `Entity.contexts: Set<Context>`
field lets any entity carry multiple, flat associations — no hierarchies,
as many as needed. The kernel also provides `Tag(name)` as a minimal blessed
Context for frictionless cross-extension tagging (e.g. `#learning`).

### `Anchored`

> "things with a canonical temporal instant"

A **pure role marker** for documents that have a single point in time. This
marker carries **no `anchor_at` field**. Concrete classes implementing
`Anchored` declare which of their own `xsd:dateTime` fields serves as the
canonical instant via `@metadata.anchor_field` at the class level. The
composer validates this at L5 — every concrete class implementing `Anchored`
must declare a valid anchor field.

If the anchor field is **unset** on a document, relative triggers referencing
that entity are **dormant** — `triggerd` evaluators skip them explicitly and
log `trigger_dormant`.

### `Trigger`

> "conditions that fire"

The abstract root of the trigger family, defined in the `triggers` kernel
module. Concrete trigger types include `OneShotTrigger`, `ScheduleTrigger`,
`RelativeTrigger`, `EventTrigger`, and `CompositeTrigger`. Triggers are
evaluated by `triggerd`, which materialises `TriggerFiring` records consumed
by `effectd`.

### What Was Removed

- **`Remindable`** — gone from core. Reminders are an extension concern.
  Extensions that need trigger-attachment semantics use `Triggerable` (from the
  triggers module) or define their own markers.
- **`Provenance.source`** — gone. Multi-source derivation is n-ary via
  `Entity.derived_from: Set<Source>`.

## Entity Diagram

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
│  time_management (extension):                                      │
│   Task      ── Source+TaskSpec                                     │
│              provenance · due_date · status(open/planned/done)     │
│   Event     ── Source+Context  (an event IS a context)             │
│              start/end · location→Location · status                │
│   Routine   ── steps: List<RoutineStep> · trigger                  │
│   RoutineStep ── @oneOf task:TaskSpec | activity:ActivitySpec      │
│   Activity  ── Source+Context+ActivitySpec · routine→Routine       │
│   Reminder  ── refer_to · trigger→Trigger (optional, extension)   │
│                                                                    │
│  people (extension):                                               │
│   Person    ── Source+Context · Contact (@subdocument, inline)     │
│   Location  ── Context · aliases · coordinates                     │
└────────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### Provenance (mandatory birth certificate)

Every `Entity` carries exactly **one required** `Provenance` subdocument —
the birth certificate. Its fields: `agent` (reserved grammar: `service:<name>`,
`user:<name>`, `ext:<name>`), `at` (xsd:dateTime), `method` (optional),
`confidence` (optional).

Updates are attributed via the **commit graph** (the biography), deliberately
not on the document itself — the commit graph records who changed what and
when, separately from the document's birth. You can always answer "where did
this come from?" and the frontend surfaces this as a one-click source chain.

### Multi-source derivation

`Entity.derived_from: Set<Source>` is n-ary — a document can be derived from
multiple upstream sources. The `derived_from` link doubles as the
**idempotency guard**: before processing a captured item, `ingestd` runs one
GraphQL query over `Entity` / `derived_from` to detect already-extracted
documents.

### Anchoring (pure marker, annotation-driven)

`Anchored` is a pure role marker with no fields. Concrete classes declare the
anchor via `@metadata.anchor_field`. The anchor field must be `xsd:dateTime`.
If unset on a document, relative triggers are **dormant** — evaluators skip
them. This design keeps the marker clean (no runtime coupling) while letting
the composer enforce correctness at schema-apply time.

### Context (flat, multi-valued tagging)

A Context is anything a Task or Event relates to: a Person, a Location, an
Event, a custom context. No hierarchies — just associations, as many as
needed. The extraction layer links known contexts automatically
(case-insensitive exact match; near-misses are logged, not guessed).

### Event inherits Context

An Event (like "Dentist appointment") is both something that happens **and** a
context that other things can be associated with. "Buy toothpaste" can have
`required_context: [Event:Dentist, Person:Topias]`.

### One capture type, one pipeline (kernel)

**`Captured`** is a single kernel schema class in `schema/modules/capture`
that subsumes the old `InboxNote`/`InboxAudio` split. It carries
`content_type` (MIME style), `content` (text), `blob_sha256` (binary),
`file_name`, `captured_at`, `transcription`, and `status`
(new/transcribed/processed/failed/archived). All captures — text notes,
voice memos, files — flow through the same extraction pipeline, the same
provenance model, and the same statuses. Capture handlers ship inside
`captured`; ingest sources ship inside `ingestd`. The **webui inbox page**
is backed by the `Captured` class.

### AI writes with provenance; branches are the review boundary

The trust ladder:

1. **Dry-run** — real reads, real LLM calls, no writes (`INGESTD_DRY_RUN=true`).
2. **Staging branch** — `TDB_BRANCH` points ingestd at a non-main branch;
   promotion to main is the "accept" action.
3. **Direct-to-main** — earned trust; every write remains attributed,
   provenance-linked, and revertible via the commit graph.

## Related documents

- [Vision](vision.md) — the ADHD core problem and design principles you see embodied here
- [Architecture](architecture.md) — how the entity model interacts with services
- [Actions and trust](actions-and-trust.md) — `ActionMode` trust ladder for side effects
- [Schema modules reference](../reference/schema-modules.md) — module format and compose workflow
