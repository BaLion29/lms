# ADR-005: Anchored + Trigger model

> **Note:** Backfilled from vision documentation; decision predates this record.

## Status

Accepted

## Date

2026-07-15

## Context

The system needs to fire reminders and scheduled actions on entities —
notifications for due tasks, upcoming events, recurring routines.  The problem
has two halves: *what* can have a trigger (the anchor), and *when* does it
fire (the trigger logic).

Early designs embedded a `Remindable` marker in the kernel schema, but this
conflated "thing that can be reminded" with the kernel itself.  Reminders are
an extension concern — not every deployment needs them, and the kernel should
not grow a reminder-specific marker that every entity must inherit.

At the same time, triggers need a universal way to reference a temporal point
on an entity (a "due date", a "start time") so that relative triggers ("2
hours before the event") can be evaluated generically.

## Decision

Split the concern into two kernel mechanisms:

1. **`Anchored`** — a pure role marker in the core schema module.  No fields.
   Concrete classes implementing `Anchored` declare
   `"@metadata": {"anchor_field": "<xsd:dateTime field>"}` at the class level.
   The composer validates this at lint layer L4 (exports must have
   `label_field`) and L5 (Anchored classes must declare `anchor_field`).  If
   the anchor field is unset on a document, relative triggers referencing it
   are **dormant** — evaluators skip them explicitly (`triggerd` logs
   `trigger_dormant`).

2. **`Trigger`** — an abstract root in the triggers schema module
   (`schema/modules/triggers`).  Concrete trigger types:
   - `ScheduleTrigger` (RFC 5545 rrule)
   - `OneShotTrigger` (single `fire_at` instant)
   - `RelativeTrigger` (offset relative to an `Anchored` entity's anchor
     field)
   - `EventTrigger` (fires on kernel change-feed events)
   - `CompositeTrigger` (boolean AND/OR/NOT of other triggers)

   `Triggerable` is a mixin for things that own a trigger (used by
   extensions).  `Remindable` was removed from core.

The trigger lifecycle (`pending → notified → renotify → expire → snoozed`) is
materialised as `TriggerFiring` records by `triggerd` and enforced by
`effectd` through its nag policy.

## Alternatives considered

- **`Remindable` in kernel** — early design, rejected because reminders are
  an extension concern.  Kernel should carry only the universal building
  blocks (`Anchored`, `Trigger`), not domain-specific markers.
- **Embedded anchor field on `Anchored`** (e.g. `anchor_at: optional
  xsd:dateTime`) — rejected because a single field name cannot serve all
  concrete classes (a `Task` anchors on `due_date`, an `Event` on `start`,
  etc.).  The `@metadata.anchor_field` indirection solves this.
- **Separate trigger database/engine** (e.g. cron, Temporal) — rejected
  because the database is the only integration point.  Materialised
  `TriggerFiring` records keep trigger state queryable, auditable, and
  consistent with the rest of the graph.
- **Push-based trigger notification** — rejected because it would couple
  `triggerd` to downstream services.  Polling the `TriggerFiring` table keeps
  the queue in the database.

## Consequences

- **Easier**: any extension can declare `Anchored` classes with their own
  anchor fields.  Trigger types are composable (`CompositeTrigger`).
  Dormant-anchor semantics are explicit and logged.  The trigger lifecycle is
  fully materialised and queryable.
- **Harder**: two kernel schema modules (core + triggers) instead of one.
  Evaluator plugins must handle dormant anchors correctly.  The composer lint
  layers L4/L5 add build-time validation that must be maintained.
- **Constraint**: `Anchored` classes must declare `@metadata.anchor_field` or
  the composer rejects the schema.  Extensions that own triggers must use
  `Triggerable` from the triggers module.

## References

- [Architecture](../concepts/architecture.md) — Trigger / Notify data flow
- [Data Model](../concepts/data-model.md)
- [Vision](../concepts/vision.md) — Anchored + Trigger section
