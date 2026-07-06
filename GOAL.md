# Life-Management System — GOAL.md

## One-Sentence Purpose

A **single source of truth** for everything in my life — capture, organize, and act on thoughts, commitments, and events — built for an ADHD brain, on TerminusDB, with **AI as the processing layer**, a **modular, plugin-extensible service architecture**, and a **Python Reflex frontend** as the first (not only) surface.

---

## The Core Problem

Standard productivity systems assume a linear brain: capture → organize → execute → review.
ADHD brains work differently:

- Thoughts are **fleeting** and must be captured in seconds or they vanish
- Things have **multiple contexts** simultaneously — a book can be `#learning` and `#reading` and connected to a specific person
- Rigid hierarchies feel suffocating; flat, multi-tagged relationships feel natural
- **Traceability matters** — "why did I write down 'buy Briefkastenkleber'? Oh, it came from that voice note about Topias"
- **Reminders need to nag** — a single notification is not enough
- **Organizing is the bottleneck** — the ADHD brain is great at capturing and terrible at filing. So filing is delegated to AI; the human only supervises.

TerminusDB is the foundation because it models reality as a **graph of connected documents** — exactly how the ADHD brain makes associations — and its **commit graph** gives every change an author, a message, and a way back.

---

## What This System Is

| Principle | Implementation |
| --- | --- |
| **SSOT (Single Source of Truth)** | TerminusDB stores everything: tasks, events, reminders, inbox items, people, locations, routines, triggers. No scattering across apps. |
| **Frictionless Capture** | Voice memos (`InboxAudio`) and text notes (`InboxNote`) drop in via synced watched directories or a capture endpoint. Capture costs < 5 seconds. |
| **AI does the filing** | `ingestd` polls the inbox, sends transcriptions/notes to an LLM with a typed output schema, and materializes validated `Task`/`Event`/`Reminder`/`Person` documents — dates resolved, known entities linked, `derived_from` always set. |
| **AI acts, never invisibly** | Every AI write is a distinct TerminusDB commit with `author=ingestd`, full provenance on each document, and one commit per inbox item — attributable, auditable, and revertible. Writes can be pointed at a staging branch; dry-run mode exists for trust-building. See Design Decision 6. |
| **Ask your life anything** | `queryd` exposes a conversational agent ("was steht diese Woche an?", "when did I last plan something with Anna?") over the graph, with a small set of explicitly gated write actions. |
| **Everything is traceable** | The `Source` marker means every Task and Event knows where it came from — an audio, a note, a routine, or another entity. The source chain is always walkable. |
| **Everything is remindable** | The `Remindable` marker means reminders can attach to anything — not just events. A rich `Trigger` model (schedule/rrule, relative offsets, context entry, entity events, boolean composition) drives when they fire. |
| **Multiple contexts, no hierarchies** | The `Context` marker lets a Task be tagged with `Person`, `Location`, `Event`, or custom contexts — as many as needed. |
| **Processing pipeline** | Inbox items flow through explicit statuses (`new → transcribed → processed / failed / archived`), spawning core entities along the way. Statuses *are* the queue; the database is the only integration point between modules. |
| **Modular by design** | The schema itself is split into versioned **modules** (core, inbox, planning, people, routines, …) composed at build time; services load **plugins** via Python entry points. New domains = new module + plugins, no core changes. |
| **Open to contributors** | A third party can ship one installable package containing a schema module, an extractor plugin, and query tools — and the whole vertical (capture → extraction → storage → query) works. See "Extensibility Promise". |

---

## What This System Is NOT

- **Not just another to-do app** — the backend is headless: two HTTP/document APIs consumable by any client or automation. Reflex is the *first* frontend, not the only possible one.
- **Not gamified** — no points, streaks, or dopamine engineering (just stats and overview)
- **Not opinionated about methodology** — GTD, Time-Blocking, Eisenhower Matrix — implement whatever on top
- **Not a calendar** — it stores time-bound data; rich calendar rendering can happen elsewhere (the frontend shows a simple agenda)
- **Not silently autonomous AI** — the AI never mutates commitments invisibly or irreversibly. Every AI action is attributed, provenance-linked, and undoable via the commit graph; write capabilities are opt-in flags, off by default.
- **Not a monolith** — no module may depend on another module's internals; the database and declared plugin/module contracts are the only coupling allowed.

---

## The Entity Model (current state)

Four abstract markers structure everything:

- **`Source`** — "things other things can be derived from" (traceability)
- **`Context`** — "things other things can be tagged with" (flat association)
- **`Remindable`** — "things reminders can attach to"
- **`Trigger`** — "conditions that fire" (abstract root of the trigger family)

```
┌────────────────────────────────────────────────────────────────────┐
│ CAPTURE (module: inbox)                                            │
│   InboxAudio  ── Source   status: new→transcribed→processed        │
│   InboxNote   ── Source   status: new→processed                    │
└───────────────────────────┬────────────────────────────────────────┘
                            │ ingestd: LLM extraction + entity linking
                            ▼
┌────────────────────────────────────────────────────────────────────┐
│ CORE ENTITIES                                                      │
│                                                                    │
│  planning:                                                         │
│   Task      ── Remindable+Source+TaskSpec                          │
│              derived_from · due_date · status(open/planned/done)   │
│              required_context: Set<Context>                        │
│   Event     ── Remindable+Source+Context  (an event IS a context)  │
│              start/end · location→Location · status                │
│   Reminder  ── refers_to→Remindable · trigger→Trigger (optional)   │
│                                                                    │
│  people:                                                           │
│   Person    ── Source+Context · Contact (@subdocument, inline)     │
│   Location  ── Context · aliases · coordinates                     │
│                                                                    │
│  routines (schema present, not yet driven by any service):         │
│   Routine   ── steps: List<RoutineStep> · trigger                  │
│   RoutineStep ── @oneOf task:TaskSpec | activity:ActivitySpec      │
│   Activity  ── Remindable+Source+Context+ActivitySpec              │
└────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────┐
│ TRIGGER FAMILY (abstract Trigger + enabled/validity window)        │
│   ScheduleTrigger  dtstart + rrule                                 │
│   RelativeTrigger  anchor→Remindable + offset  ("30 min before X") │
│   ContextTrigger   fires on context (groundwork for geofencing)    │
│   EventTrigger     created/updated/completed/status_changed on doc │
│   CompositeTrigger and/or/not over other triggers                  │
└────────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Source & derived_from (traceability)

Every extracted Task/Event/Reminder carries `derived_from → Source`. InboxAudio, InboxNote, Event, Task, Person, Activity, Routine all inherit `Source`. You can always answer "where did this come from?" — and the frontend surfaces this as a one-click source chain. `derived_from` doubles as the **idempotency guard**: before processing an inbox item, ingestd checks whether documents derived from it already exist.

### 2. Remindable + Trigger (universal, composable reminders)

Reminders are standalone entities that `refer_to` anything inheriting `Remindable`. *When* they fire is fully delegated to the Trigger family — recurring schedules (RFC 5545 rrule), offsets relative to another Remindable, context entry, entity lifecycle events, and boolean composition of all of these. The reminder *lifecycle* (pending/triggered/snoozed/dismissed + nagging) belongs to the future reminder engine and its schema additions (see ARCHITECTURE.md §8).

### 3. Context (flat, multi-valued tagging)

A Context is anything a Task or Event relates to: a Person, a Location, an Event, a future custom context. No hierarchies — just associations, as many as needed. The extraction layer links known contexts automatically (case-insensitive exact match in v1; near-misses are logged, not guessed).

### 4. Event inherits Context

An Event (like "Dentist appointment") is both something that happens AND a context that other things can be associated with. "Buy toothpaste" can have `required_context: [Event:Dentist, Person:Topias]`.

### 5. Two inbox types, one pipeline

**InboxAudio** (voice, auto-uploaded, transcribed via STT) and **InboxNote** (text) flow through the same extraction pipeline, the same provenance model, and the same statuses.

### 6. AI writes with provenance; branches are the review boundary  *(supersedes "Proposal documents")*

Earlier revisions staged AI output as `Proposal` documents requiring per-item acceptance. This was **superseded**: TerminusDB already provides the staging primitive — **branches** — and the commit graph already provides per-item review units (one commit per inbox item, `author=ingestd`). The current trust ladder:

1. **Dry-run** — real reads, real LLM calls, no writes (`DRY_RUN=true`). The evaluation mode.
2. **Staging branch** — `TDB_BRANCH` points ingestd at a non-main branch; promotion to main is the "accept" action (tooling for comfortable per-commit review is a future module).
3. **Direct-to-main** — earned trust; every write remains attributed, provenance-linked, and revertible via the commit graph.

The *principle* ("no silent, irreversible AI mutation") is unchanged; the *mechanism* moved from an application-level staging table to database-level branching + commits. This removes an entire entity class, a review-queue UI blocking the ingestion vertical, and a materialization step — while keeping every guarantee that mattered.

### 7. Modules and plugins are the growth mechanism

The schema is not one file: it is composed from versioned **schema modules** with declared dependencies, semver discipline (additive = MINOR, breaking = MAJOR + migration), and an in-database registry. Services discover **plugins** (extractors for ingestd, tools for queryd) via entry points and verify each plugin's module requirements at startup. Pydantic models are **generated** from the composed schema — never hand-written, never drifting. Details in ARCHITECTURE.md §4–§7.

---

## Technology Foundation

| Component | Role |
| --- | --- |
| **TerminusDB** | Graph/document database. Schema-enforced, versioned, branchable. Stores all entities *and* the module registry. The sole integration point between modules. |
| **uv workspace (`lms/`)** | Monorepo: shared packages + services, one lockfile discipline, Python ≥ 3.12. |
| **`lms-schema`** | Schema toolchain: compose module fragments → diff against live instance → plan/apply (schema push + data migrations) → validate → promote → **codegen** Pydantic models. |
| **`lms-core`** | Shared domain layer: async TerminusDB HTTP client (thin, typed, httpx), generated Pydantic models, shared TDB settings, plugin protocols. Every service imports it; nothing else talks to TerminusDB raw. |
| **`ingestd`** | AI ingestion service: poll inbox → Pydantic AI extraction (typed, discriminated-union output) → entity linking → one provenance-carrying commit per item → status flip. Extraction targets are plugins. |
| **`queryd`** | FastAPI + Pydantic AI conversational agent: GraphQL read tools with hard guards, flag-gated typed write tools (plugins), stateless `/v1/chat` for the frontend. |
| **STT** | faster-whisper (currently via the existing n8n + Speaches pipeline); multilingual German/French/English. Swappable — it just flips `InboxAudio` statuses. |
| **LLM access** | LiteLLM proxy (OpenAI-compatible) in front of Claude API / OpenRouter / local models — every service sees one interface, temperature 0. |
| **Reflex (`lms-frontend`)** | Pure-Python frontend: chat (via queryd), inbox, tasks, agenda, contexts, quick capture. A client of the services, never of the database. |
| **Notifications** | ntfy (self-hosted push) with action buttons — consumed by the future reminder engine. |

---

## ADHD-Specific Design Principles

1. **Capture must be < 5 seconds** — voice memo or quick text, nothing more
2. **Processing can happen later** — the system holds the thought; AI pre-chews it so acting on it is trivial
3. **Everything is findable** — multiple contexts, traceable sources, a queryable graph, *and* a natural-language interface (queryd) so "finding" doesn't require remembering query syntax
4. **Reminders persist** — they don't notify once and vanish; they nag until acknowledged (reminder engine)
5. **No rigid structure** — flat tags beat hierarchies; multiple inheritance beats single categories
6. **One database** — no scattered information across apps
7. **Always usable** — every milestone ends in something that works end-to-end; a half-built system is an abandoned system. (This is why ingestd shipped *before* any review UI.)
8. **Guilt-free dropping** — tasks must be droppable, not just "done", so the list never becomes a graveyard of shame. *(Schema gap: `TaskStatus` still lacks `dropped` — tracked in ARCHITECTURE.md §8.)*

---

## Extensibility Promise

The test for "the architecture works" is concrete: **a third party can extend the system without touching core code.** One installable package containing —

1. a **schema module** (e.g. `library/` with a `Book` class inheriting `Source`+`Context`, depending on `people` for a `lent_to → Person` reference),
2. an **extractor plugin** (entry point `lms.ingestd.extractors`) so "Anna hat mir Dune ausgeliehen" in a voice note produces a `Book` document,
3. a **tool plugin** (entry point `lms.queryd.tools`) so the agent can `set_book_status`,

— dropped into `schema/modules/` and installed into the services' environments, then `compose → apply → codegen → restart`, yields a fully working new domain: capturable, extractable, stored, queryable. This scenario is a maintained end-to-end integration test, not documentation fiction.

Rules that keep this safe: modules declare dependencies and exports (nothing may reference undeclared classes); semver is enforced by tooling (breaking changes require migrations); plugins declare module requirements checked at startup against the in-database registry; unmet requirements skip the plugin with a warning instead of crashing the service.

---

## Future Directions (not yet implemented)

- **Reminder engine (`reminderd`)** — trigger evaluation, firing, nag/snooze lifecycle via ntfy; requires the ReminderStatus schema additions (ARCHITECTURE.md §8)
- **Routine engine** — Routines spawning Tasks/Activities from their steps on trigger
- **Branch review tooling** — comfortable per-commit review + promote flow for staging-branch mode (the successor to the old proposal queue idea)
- **Semantic search** — a vector-search service; queryd already carries a marked extension point in its tool registry
- **Transcriber service** — replace the n8n/Speaches pipeline with a first-class `transcriberd` worker
- **Time-Block & Schedule** — self-imposed time containers and the "what now?" function (ties into the Rust scheduler exploration)
- **TimeLog** — actual time tracking for stats and overview
- **Location-based reminders** — `ContextTrigger` + geofencing on the capture device
- **Escalation chains** — ignored reminder escalates in-app → push → email

---

_Last updated: 2026-07-05 — reconciled with the ingestd/queryd/modularization build specs: superseded the Proposal staging layer in favor of provenance + branch-based review (Decision 6), adopted the service architecture (ingestd/queryd) and uv workspace, promoted modularity from a principle to the concrete schema-module + plugin mechanism, added the Trigger family and conversational access, added the Extensibility Promise. Schema evolves with need — now via versioned modules._
