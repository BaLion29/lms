# ADR-003: Entry-point plugin system

> **Note:** Backfilled from vision documentation; decision predates this record.

## Status

Accepted

## Date

2026-07-15

## Context

The firnline services need to be extensible without editing core code. New
domains (time management, address book, reminders) should ship as installable
packages that contribute schema modules, extraction logic, query tools, and
notification channels — and the system must discover and validate them at
startup.

The extensibility surface spans the whole vertical: schema composition,
capture handling, AI extraction, read/write tools, trigger evaluation,
indexing, and notification delivery. A single plugin interface would be too
coarse; per-service discovery logic would couple the system to its plugins.

## Decision

Use **Python `importlib.metadata` entry points** with **nine** named groups,
one per extension point. All host services boot through the shared
**`PluginHost`** in `firnline-core`, which performs:

1. **Discover** — `entry_points(group=...)`
2. **Validate** — each plugin implements a typed protocol
3. **Check requirements** — plugins declare `requires` (module semver ranges)
   and `requires_classes` (class @ids), checked against the in-database
   registry's `exports` at startup
4. **Collision check** — name/kind collisions between active plugins are
   fatal
5. **Select** — per-service `HostPolicy` controls which failures are fatal
   vs. degraded (e.g. `queryd` tolerates missing plugins; `ingestd` does not)

The nine entry-point groups:

| Group | Protocol | Used by |
|---|---|---|
| `firnline.schema_modules` | directory path | firnline-schema |
| `firnline.captured.handlers` | `CaptureHandler` | captured |
| `firnline.ingestd.sources` | `IngestSourcePlugin` | ingestd |
| `firnline.ingestd.extractors` | `ExtractorPlugin` | ingestd |
| `firnline.queryd.tools` | `ToolPlugin` | queryd |
| `firnline.triggerd.evaluators` | `TriggerEvaluator` | triggerd |
| `firnline.indexed.indexers` | `IndexerPlugin` | indexed |
| `firnline.notifyd.channels` | `NotificationChannel` | effectd (legacy) |
| `firnline.effectd.executors` | `ActionExecutor` | effectd |

## Alternatives considered

- **File-system scanning** (convention-over-configuration directories) —
  rejected because it does not work with pip-installed packages and makes
  collision detection implicit.
- **Plugin registry service** — over-engineered for a single-process
  discovery problem; would add network hops and operational complexity.
- **Single entry-point group with a type discriminator field** — rejected
  because it would sacrifice type-checking at the entry-point level and make
  the protocol surface ambiguous.

## Consequences

- **Easier**: third-party extensions ship one pip-installable package with
  multiple entry points. Startup validation catches misconfigurations before
  runtime. Collision detection prevents silent conflicts.
- **Harder**: nine protocols to document and maintain. Backward-incompatible
  protocol changes require coordination across all plugins.
- **Constraint**: every service must import `firnline-core.plugins` and
  configure a `HostPolicy`. Direct ad-hoc discovery outside `PluginHost` is
  forbidden.

## References

- [Architecture](../concepts/architecture.md) — Plugin Mechanism section
- [Entry Points Reference](../reference/entry-points.md)
- [Vision](../concepts/vision.md) — Extensibility Promise
