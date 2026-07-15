# Roadmap

Firnline is under active development (v0.1.0-alpha). This document
captures aspirational directions and ideas — **nothing here is scheduled or
committed to a specific release**. It exists to communicate intent and
invite contribution.

All items trace back to documented sources. Where an item has a concrete
anchor in code or docs, it appears under **Near-term**. Vision-level ideas
without implementation groundwork appear under **Ideas**.

## Near-term

Items with concrete anchors (code stubs, documented follow-ups, or existing
infrastructure that the item extends).

| Item | Source | Notes |
|---|---|---|
| **Nag-policy consolidation** — reimplement renotify/expire/snooze on top of `ActionExecution` documents. | [vision.md](concepts/vision.md), [actions-and-trust.md § Legacy Notification Loop](concepts/actions-and-trust.md) | Today the legacy notification loop and the action engine coexist. Consolidation would unify all side-effect delivery through the action engine, giving nag policies the same trust ladder, idempotency keys, and retry/backoff as webhook actions. Documented as an explicit follow-up. |
| **Branch review tooling** — comfortable per-commit review and promote flow for staging-branch mode. | [vision.md](concepts/vision.md) | The branch/promote infrastructure exists (firnline-schema, TerminusDB branching). Missing: a UI or CLI that presents staged commits for human review with one-click accept/reject. |
| **Transcriber service** — first-class STT service replacing the n8n pipeline. | [vision.md](concepts/vision.md) | The STT hop currently relies on an external n8n pipeline with faster-whisper. A dedicated `transcriberd` service would integrate directly with the captured pipeline, flipping `Captured` statuses from `new → transcribed` without an external orchestration tool. The swappable-STT design is already in place. |
| **Time-block planning** — schedule tasks into calendar blocks. | [vision.md](concepts/vision.md) | Time-management schema (Task, Event, Routine) provides the data foundation. Time-block planning would be a new queryd tool or a dedicated planner service. |
| **TimeLog** — record time spent on tasks/activities. | [vision.md](concepts/vision.md) | Would require a new schema module and extractor. Related to time-block planning but a distinct feature. |
| **find_* tool hardening** — graceful fallback when indexed is unavailable. | [mcpd.md § Design Notes](reference/api/mcpd.md) | The `find_entity`/`find_class`/`find_field` tools on queryd return errors when indexed is down. Future: degrade gracefully or route through raw schema introspection when the index is unavailable. |

## Ideas

Vision-level items that would be significant undertakings. No implementation
work has started.

| Item | Source | Notes |
|---|---|---|
| **Routine engine** — Routines spawning Tasks/Activities from their steps. | [vision.md](concepts/vision.md) | The `Routine`/`RoutineStep` schema exists in `firnline-ext-time-management`. The engine would be a new polling service that expands routine steps into concrete entities when the routine's trigger fires. |
| **Semantic search** — full document search beyond the `indexed` grounding service. | [vision.md](concepts/vision.md) | `indexed` already mirrors documents and schema into a hybrid vector+lexical index for precise-lookup grounding. Full semantic search (natural-language queries over all documents) would extend this with a dedicated search endpoint and ranking. |
| **Escalation chains** — if a reminder is ignored, escalate through configured channels. | [vision.md](concepts/vision.md) | Would extend the action/trigger model with escalation rules (e.g., notify me → notify partner → send email). Requires policy configuration and multi-stage action chaining. |
| **Location-based reminders** — trigger notifications based on geographic location. | [vision.md](concepts/vision.md) | Would require a location-tracking input source (mobile app, geofence) and a new trigger type that evaluates against location data. The `Location` schema class exists. |
| **Multi-user support** — per-user accounts, data isolation, shared contexts. | Implicit from single-password WebUI gate | The current system has a single shared password with no per-user accounts. Multi-user would require a fundamental re-architecture of the data model and auth layer. |
