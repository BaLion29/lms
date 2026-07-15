# Vision

A **single source of truth** for everything in your life — capture, organize,
and act on thoughts, commitments, and events — built for an ADHD brain, on
TerminusDB, with AI as the processing layer, a modular plugin-extensible
service architecture, and a frontend that's just one possible client.

## Overview

Standard productivity systems assume a linear brain: capture → organize →
execute → review. ADHD brains work differently:

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
| **Ask your life anything** | `queryd` exposes structured read/write endpoints over the graph — GraphQL, document lookup, find entity/class/field, schema introspection, and guarded write tools — that mcpd surfaces to external AI agents. |
| **Everything is traceable** | The `Entity` base carries a **required** `Provenance` subdocument (birth certificate: agent, at, method, confidence). Multi-source derivation lives in `Entity.derived_from: Set<Source>` (n-ary). Every Task and Event knows where it came from — an audio, a note, a routine, or another entity. The source chain is always walkable. The agent naming grammar is reserved: `service:<name>`, `user:<name>`, `ext:<name>`. |
| **Everything is remindable** | Reminders are an extension concern, not kernel. The triggers module provides `Triggerable` (a mixin for things that own a trigger) and an `Anchored` pure role marker for temporal anchoring. Concrete classes implementing `Anchored` declare a class-level `@metadata.anchor_field` naming an `xsd:dateTime` field. A rich `Trigger` model (schedule/rrule, relative offsets over Anchored entities, event-based triggers over the kernel change feed, boolean composition) drives when they fire. If an anchor's `anchor_field` is unset, relative triggers are **dormant** — evaluators skip them explicitly (triggerd logs `trigger_dormant`). `triggerd` materialises `TriggerFiring` records; `effectd` executes the nag policy (renotify, expire, snooze) and delivers via notification channels. |
| **Multiple contexts, no hierarchies** | The `Context` marker lets a Task be tagged with `Person`, `Location`, `Event`, or custom contexts — as many as needed. |
| **Processing pipeline** | Captured documents flow through explicit statuses (`new → transcribed → processed / failed / archived`), spawning core entities along the way. Statuses *are* the queue; the database is the only integration point. Capture is a kernel schema module (`schema/modules/capture`) — the capture raison d'être ships with core. |
| **Modular by design** | The schema is split into versioned **modules** (core, capture, triggers, time_management, people, …) composed at build time; services load **plugins** via Python entry points. New domains = new module + plugins, no core changes. |
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
| **queryd** | FastAPI read/write proxy: GraphQL, document lookup, find-entity/class/field, schema introspection, guarded write-tool endpoints. Model-free — no embedded LLM. |
| **triggerd** | Trigger evaluation polling worker: poll Trigger → evaluate → materialise TriggerFiring records. |
| **effectd** | Effect delivery daemon: plan `ActionExecution` records, execute via `ActionExecutor` plugins (webhook, Gotify, etc.), run legacy notification loop with nag policy (renotify, expire, snooze wake-up). |
| **captured** | Minimal FastAPI capture-ingress: `POST /v1/capture/note` and `/v1/capture/file` with pluggable handlers. |
| **STT** | faster-whisper (via existing n8n pipeline); multilingual German/French/English. Swappable — it just flips `Captured` statuses. |
| **LLM access** | LiteLLM proxy (OpenAI-compatible) in front of any model — every service sees one interface. |
| **WebUI (Reflex)** | Pure-Python frontend living in `services/webui/`: captured items, tasks, agenda, contexts, quick capture. A client of the services, never of the database. |

## The Entity Model

The entity model is documented in full in [entity-model.md](entity-model.md).
In brief, four abstract markers structure everything:

- **`Source`** — "things other things can be derived from" (traceability)
- **`Context`** — "things other things can be tagged with" (flat association)
- **`Anchored`** — "things with a canonical temporal instant" (pure role marker; concrete classes declare the anchor field via `@metadata.anchor_field`)
- **`Trigger`** — "conditions that fire" (abstract root of the trigger family)

`Remindable` has been **removed** from core — reminders are an extension concern, not kernel.

## Related documents

- [Entity model](entity-model.md) — the marker grammar and key design decisions
- [Architecture](architecture.md) — system overview and data flow
- [Plugin system](plugin-system.md) — extensibility in detail
- [Actions and trust](actions-and-trust.md) — action engine and trust ladder
- [Security](security.md) — auth model and trust boundaries
- [Roadmap](../roadmap.md) — future directions (moved from here)
