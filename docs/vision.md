# Vision

## One-Sentence Purpose

A **single source of truth** for everything in your life — capture, organize,
and act on thoughts, commitments, and events — built for an ADHD brain, on
TerminusDB, with AI as the processing layer, a modular plugin-extensible
service architecture, and a frontend that's just one possible client.

## The Core Problem

Standard productivity systems assume a linear brain: capture → organize →
execute → review.  ADHD brains work differently:

- Thoughts are **fleeting** and must be captured in seconds or they vanish.
- Things have **multiple contexts** simultaneously — a book can be `#learning`
  and `#reading` and connected to a specific person.
- Rigid hierarchies feel suffocating; flat, multi-tagged relationships feel
  natural.
- **Traceability matters** — "why did I write down 'buy Briefkastenkleber'?
  Oh, it came from that voice note about Topias."
- **Reminders need to nag** — a single notification is not enough.
- **Organizing is the bottleneck** — the ADHD brain is great at capturing and
  terrible at filing, so filing is delegated to AI; the human only supervises.

TerminusDB is the foundation because it models reality as a **graph of
connected documents** — exactly how the ADHD brain makes associations — and
its **commit graph** gives every change an author, a message, and a way back.

## What This System Is

| Principle | Implementation |
|---|---|
| **SSOT (Single Source of Truth)** | TerminusDB stores everything: tasks, events, reminders, captured items, people, locations, routines, triggers. No scattering across apps. |
| **Frictionless Capture** | Voice memos and text notes arrive as `Captured` documents via a capture endpoint or watched directories. Capture costs < 5 seconds. |
| **AI does the filing** | `ingestd` polls `Captured` documents, sends text to an LLM with a typed output schema, and materializes validated `Task`/`Event`/`Reminder`/`Person` documents — dates resolved, known entities linked, `derived_from` referencing the source `Captured` document. |
| **AI acts, never invisibly** | Every AI write is a distinct TerminusDB commit with `author=service:ingestd`, full `Provenance` on each document (agent, at, method, confidence — every Entity has exactly one birth certificate), and one commit per captured item — attributable, auditable, and revertible. The commit graph is the biography: updates are attributed there, not on the document. Writes can be pointed at a staging branch; dry-run mode exists for trust-building. |
| **Ask your life anything** | `queryd` exposes a conversational agent ("was steht diese Woche an?", "when did I last plan something with Anna?") over the graph, with a small set of explicitly gated write actions. |
| **Everything is traceable** | The `Entity` base carries a **required** `Provenance` subdocument (birth certificate: agent, at, method, confidence). Multi-source derivation lives in `Entity.derived_from: Set<Source>` (n-ary). Every Task and Event knows where it came from — an audio, a note, a routine, or another entity. The source chain is always walkable. The agent naming grammar is reserved: `service:<name>`, `user:<name>`, `ext:<name>`. |
| **Everything is remindable** | Reminders are an extension concern, not kernel. The triggers module provides `Triggerable` (a mixin for things that own a trigger) and an `Anchored` pure role marker for temporal anchoring. Concrete classes implementing `Anchored` declare a class-level `@metadata.anchor_field` naming an `xsd:dateTime` field. A rich `Trigger` model (schedule/rrule, relative offsets over Anchored entities, event-based triggers over the kernel change feed, boolean composition) drives when they fire. If an anchor's `anchor_field` is unset, relative triggers are **dormant** — evaluators skip them explicitly (triggerd logs `trigger_dormant`). `triggerd` materialises `TriggerFiring` records; `notifyd` executes the nag policy (renotify, expire, snooze) and delivers via notification channels. |
| **Multiple contexts, no hierarchies** | The `Context` marker lets a Task be tagged with `Person`, `Location`, `Event`, or custom contexts — as many as needed. |
| **Processing pipeline** | Captured documents flow through explicit statuses (`new → transcribed → processed / failed / archived`), spawning core entities along the way. Statuses *are* the queue; the database is the only integration point. Capture is a kernel schema module (`schema/modules/capture`) — the capture raison d'être ships with core. |
| **Modular by design** | The schema is split into versioned **modules** (core, capture, triggers, planning, people, …) composed at build time; services load **plugins** via Python entry points. New domains = new module + plugins, no core changes. |
| **Open to contributors** | A third party can ship one installable package containing a schema module, an extractor plugin, and query tools — and the whole vertical (capture → extraction → storage → query) works. |

## What This System Is NOT

- **Not just another to-do app** — the backend is headless; two HTTP APIs
  consumable by any client or automation.
- **Not gamified** — no points, streaks, or dopamine engineering.
- **Not opinionated about methodology** — GTD, Time-Blocking, Eisenhower
  Matrix — implement whatever on top.
- **Not a calendar** — it stores time-bound data; rich calendar rendering
  happens elsewhere.
- **Not silently autonomous AI** — every AI action is attributed,
  provenance-linked, and undoable via the commit graph; write capabilities are
  opt-in, off by default.
- **Not a monolith** — no module may depend on another module's internals;
  the database and declared plugin/module contracts are the only coupling
  allowed.

## The Entity Model

Four abstract markers structure everything:

- **`Source`** — "things other things can be derived from" (traceability)
- **`Context`** — "things other things can be tagged with" (flat association)
- **`Anchored`** — "things with a canonical temporal instant" (pure role marker; concrete classes declare the anchor field via `@metadata.anchor_field`)
- **`Trigger`** — "conditions that fire" (abstract root of the trigger family)

`Remindable` has been **removed** from core — reminders are an extension concern, not kernel. Extensions that need reminder-attachment semantics define their own markers or use `Triggerable` (from triggers module).

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
│  planning:                                                         │
│   Task      ── Source+TaskSpec                                     │
│              provenance · due_date · status(open/planned/done)     │
│   Event     ── Source+Context  (an event IS a context)             │
│              start/end · location→Location · status                │
│   Reminder  ── refer_to · trigger→Trigger (optional, extension)   │
│                                                                    │
│  people:                                                           │
│   Person    ── Source+Context · Contact (@subdocument, inline)     │
│   Location  ── Context · aliases · coordinates                     │
│                                                                    │
│  routines:                                                         │
│   Routine   ── steps: List<RoutineStep> · trigger                  │
│   RoutineStep ── @oneOf task:TaskSpec | activity:ActivitySpec      │
│   Activity  ── Source+Context+ActivitySpec                         │
└────────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### Source & Provenance (traceability)

Every Entity carries exactly **one required** `Provenance` subdocument — the
birth certificate. `Provenance` fields: `agent` (reserved grammar:
`service:<name>`, `user:<name>`, `ext:<name>`), `at` (xsd:dateTime),
`method` (optional), `confidence` (optional). The `source` field is **gone** —
multi-source derivation lives in `Entity.derived_from: Set<Source>` (n-ary).
Updates are attributed via the commit graph (the biography), deliberately
not on the document. You can always answer "where did this come from?" —
and the frontend surfaces this as a one-click source chain. The
`derived_from` link doubles as the idempotency guard: before processing
a captured item, ingestd runs one GraphQL query over `Entity` /
`derived_from` to detect already-extracted documents.

### Anchored + Trigger (universal, composable reminders)

Reminders are an extension concern. The kernel provides `Anchored` (a pure
role marker — no `anchor_at` field) and the triggers module provides
`Triggerable` (a mixin for things that own a trigger). Concrete classes
implementing `Anchored` declare `"@metadata": {"anchor_field": "<xsd:dateTime field>"}`
at the class level; the composer validates this at L4/L5. If the anchor
field is unset on a document, relative triggers referencing it are
**dormant** — evaluators skip them explicitly (triggerd logs
`trigger_dormant`).

Reminders are standalone entities that refer to domain documents. *When*
they fire is fully delegated to the Trigger family — recurring schedules
(RFC 5545 rrule), offsets relative to an `Anchored` entity's anchor field,
event triggers over the kernel change feed, and boolean composition of all
of these. The trigger lifecycle (pending→notified→renotify→expire→snoozed)
is fully materialised and enforced by `triggerd` + `notifyd`.

### Context (flat, multi-valued tagging)

A Context is anything a Task or Event relates to: a Person, a Location, an
Event, a future custom context. No hierarchies — just associations, as many as
needed. The extraction layer links known contexts automatically (case-insensitive
exact match; near-misses are logged, not guessed).

### Event inherits Context

An Event (like "Dentist appointment") is both something that happens AND a
context that other things can be associated with. "Buy toothpaste" can have
`required_context: [Event:Dentist, Person:Topias]`.

### One capture type, one pipeline (kernel)

**Captured** is a single kernel schema class in `schema/modules/capture`
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

### Modules and plugins are the growth mechanism

The schema is not one file: it is composed from versioned **schema modules**
with declared dependencies, semver discipline (additive = MINOR, breaking =
MAJOR + migration), and an in-database registry. Services discover **plugins**
(extractors for ingestd, tools for queryd) via entry points and verify each
plugin's module requirements at startup.

## ADHD-Specific Design Principles

1. **Capture must be < 5 seconds** — voice memo or quick text, nothing more.
2. **Processing can happen later** — the system holds the thought; AI
   pre-chews it so acting on it is trivial.
3. **Everything is findable** — multiple contexts, traceable sources, a
   queryable graph, *and* a natural-language interface (queryd) so "finding"
   doesn't require remembering query syntax.
4. **Reminders persist** — they don't notify once and vanish; they nag until
   acknowledged (reminder engine, planned).
5. **No rigid structure** — flat tags beat hierarchies; multiple inheritance
   beats single categories.
6. **One database** — no scattered information across apps.
7. **Always usable** — every milestone ends in something that works
   end-to-end; a half-built system is an abandoned system.
8. **Guilt-free dropping** — tasks must be droppable, not just "done", so the
   list never becomes a graveyard of shame.

## Extensibility Promise

A third party can extend the system without touching core code. One installable
package containing a **schema module**, an **extractor plugin**, and a **tool
plugin** — dropped in and installed — yields a fully working new domain:
capturable, extractable, stored, queryable.

Rules that keep this safe: modules declare dependencies and exports (nothing
may reference undeclared classes); semver is enforced by tooling (breaking
changes require migrations); plugins declare module requirements (`requires`
+ `requires_classes`) checked at startup against the in-database registry's
`exports`; all host services boot through the shared `PluginHost`
(discover → validate → check_requirements → collision check → select →
log), with per-service `HostPolicy` controlling fatal-vs-degraded
behaviour.

The **firn-line law** is machine-enforced by the **melt test** (`scripts/
melt-test.sh`, wired into `validate-release.sh`): a kernel-only install must
compose the schema, run codegen, pass `uv run pytest`, and idle gracefully
— no third-party extension may be necessary for the system to start.

## Technology Foundation

| Component | Role |
|---|---|
| **TerminusDB** | Graph/document database. Schema-enforced, versioned, branchable. The sole integration point between modules. |
| **firnline-core** | Shared domain layer: async TerminusDB HTTP client, generated Pydantic models, plugin protocols, conventions. Every service imports it. |
| **firnline-schema** | Schema toolchain CLI: compose, diff, plan, apply, validate, promote, codegen. |
| **ingestd** | AI ingestion polling worker: poll Captured → LLM extraction → entity linking → one commit per item → status flip. |
| **queryd** | FastAPI conversational agent: read tools, guarded write tools (plugins), stateless `/v1/chat`. |
| **triggerd** | Trigger evaluation polling worker: poll Trigger → evaluate → materialise TriggerFiring records. |
| **notifyd** | Notification delivery daemon: consume pending TriggerFiring records, execute nag policy (pending→notified, renotify, expire, snooze wake-up), deliver via `NotificationChannel` plugins (e.g. Gotify). |
| **captured** | Minimal FastAPI capture-ingress: `POST /v1/capture/note` and `/v1/capture/file` with pluggable handlers. |
| **STT** | faster-whisper (via existing n8n pipeline); multilingual German/French/English. Swappable — it just flips `Captured` statuses. |
| **LLM access** | LiteLLM proxy (OpenAI-compatible) in front of any model — every service sees one interface. |
| **Reflex (firnline-frontend)** | Pure-Python frontend (separate repo): chat, captured items, tasks, agenda, contexts, quick capture. A client of the services, never of the database. |

## Future Directions (not yet implemented)

- **Reminder engine** — trigger evaluation and firing materialization
  implemented by `triggerd`; nag/snooze/expiry lifecycle and notification
  delivery implemented by `notifyd` (first channel: Gotify).
- **Routine engine** — Routines spawning Tasks/Activities from their steps.
- **Branch review tooling** — comfortable per-commit review + promote flow for
  staging-branch mode.
- **Semantic search** — the `indexed` grounding service now mirrors TDB
   documents and schema into a hybrid vector+lexical index; `queryd`'s
   `find_entity`/`find_class`/`find_field` tools use it to prevent the
   agent from inventing entity names or schema field names (see
   [docs/indexed.md](indexed.md)).
- **Transcriber service** — first-class replacement for the n8n STT hop.
- **Time-Block & Schedule**, **TimeLog**, **Location-based reminders**,
  **Escalation chains**.
