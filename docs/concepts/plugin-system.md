# Plugin System

Why the system treats almost everything as an extension, and how the kernel
enforces purity while letting third parties ship a complete vertical slice.

## Overview

Firnline is built on an **everything-is-an-extension** philosophy. The
kernel — schema modules `core`, `capture`, `triggers`, and `actions` plus the
shared `firnline-core` library — provides the universal base and
infrastructure. Everything else (time management, people, places, reminders,
notification channels, webhook executors) ships as **extension packages** that
never touch kernel code.

This is not just convention — it is **machine-enforced**. The **melt test**
(`scripts/melt-test.sh`, wired into `validate-release.sh`) proves that a
kernel-only install composes the schema, passes codegen and tests, and idles
gracefully. No extension may be necessary for the system to start.

## Kernel vs. Extensions

| Kernel (in repo) | Extensions (installable packages) |
|---|---|
| `Entity`, `Source`, `Context`, `Anchored`, `Provenance`, `Tag` | `Task`, `Event`, `Routine`, `Activity`, `Reminder` |
| `Captured`, `Trigger` hierarchy, `Action` hierarchy | `Person`, `Location` |
| `PluginHost`, all plugin protocols | Extractor plugins, tool plugins, evaluator plugins |
| `TdbClient`, `BlobStore`, `agent_id()` | Notification channels, webhook executors, Gotify integration |
| Schema toolchain (`firnline-schema`) | Schema extensions (modules discovered via entry points) |

A single extension package can contain any subset of: a schema module,
ingest sources, extractor plugins, query tool plugins, capture handlers,
trigger evaluators, indexer plugins, notification channels, and action
executors.

## PluginHost and HostPolicy

All host services boot through the shared `PluginHost` in `firnline-core`.
The startup sequence is the same for every service:

1. **Discover** — load all plugins registered under the service's entry-point
   group via `importlib.metadata.entry_points`.
2. **Validate** — structural conformance check against the relevant protocol
   (when supplied).
3. **Fetch registry** — query TerminusDB for `SchemaModule` documents.
4. **Check requirements** — verify each plugin's `requires` (semver ranges)
   and `requires_classes` (class `@id` values) against the registry's installed
   modules and their `exports`.
5. **Collision check** — duplicate keys (capture kind, tool name, trigger
   type, indexed class, executor kind) across active plugins are **fatal**.
6. **Select** — active plugins pass all checks; failures are skipped.
7. **Log** — the active set is logged at INFO on every startup.

Each service configures a declarative `HostPolicy`:

| Policy flag | What it controls |
|---|---|
| `broken_entry_point_fatal` | Crash if an entry point fails to load |
| `zero_active_fatal` | Crash if no plugins are active after selection |
| `strict` | Requirement/validation failures are fatal (not just skipped) |
| `tdb_unavailable_fatal` | Crash if the schema module registry cannot be fetched |

Services choose their own stance. `ingestd` uses `broken_entry_point_fatal=true,
zero_active_fatal=true` (ingestion without extractors is meaningless). `queryd`
uses `zero_active_fatal=false` (read queries work without tool plugins).
`effectd` is the most permissive — `broken_entry_point_fatal=false,
strict=false` — because effect delivery should degrade gracefully when
optional executors are unavailable.

### `requires_classes` Dependency Resolution

Beyond semver module `requires`, plugins can declare `requires_classes: list[str]`
— class `@id` values (e.g. `["Task"]`, `["Person"]`) that must appear in the
union of `exports` across all installed `SchemaModule` documents. This
catches the case where a module is installed at the correct version but a
specific class was removed or renamed. The check runs at startup within
`check_requirements`; violations skip the plugin (or crash in strict mode).

## Entry Point Groups

An extension registers one or more of these groups in its `pyproject.toml`:

| Group | One-line purpose |
|---|---|
| `firnline.schema_modules` | Contribute a schema module (manifest.json + schema.json + migrations) |
| `firnline.ingestd.sources` | Tell ingestd which document type + status to poll |
| `firnline.ingestd.extractors` | Provide LLM extraction logic: proposal models, prompts, linking, builders |
| `firnline.queryd.tools` | Register guarded write tools (Pydantic AI or ToolSpec) |
| `firnline.captured.handlers` | Handle capture requests by kind (e.g. "note", "file") |
| `firnline.triggerd.evaluators` | Evaluate trigger types, compute occurrence instants |
| `firnline.indexed.indexers` | Declare TDB classes to mirror into the hybrid search index |
| `firnline.notifyd.channels` | Legacy: deliver TriggerFiring records via external services (auto-adapted) |
| `firnline.effectd.executors` | Execute external effects (webhook, notify, home-automation) |

Full protocol signatures and lifecycle details are in the [entry points
reference](../reference/entry-points.md).

## Schema Modules as Part of an Extension

An extension that contributes to the schema includes a `manifest.json` and
`schema.json` in its package. The `manifest.json` declares:

- `name` — must match the entry-point name.
- `version` — semver.
- `depends_on` — modules it depends on with semver ranges.
- `models_target` — dotted Python module path where codegen writes Pydantic
  models (e.g. `firnline_ext_time_management.models`).
- `exports` — class/enum `@id` values made available to other modules.
- `description` — human-readable.

The `firnline-schema compose` step discovers extension modules from the
`schema/modules/` tree and from installed packages via the
`firnline.schema_modules` entry point. Codegen routes models to the owning
package based on `models_target`. The extension's code imports its own
`models.py` like any other Python module.

Full details are in the [schema modules reference](../reference/schema-modules.md).

## Melt Test — Kernel Purity Guarantee

The firn-line law states: **a kernel-only install must work**. The melt test
(`scripts/melt-test.sh`) enforces this:

1. Install the workspace with only kernel packages (`firnline-core`,
   `firnline-schema`) and services.
2. Run `firnline-schema compose` — must succeed with only kernel modules
   (core, capture, triggers, actions).
3. Run `firnline-schema codegen` — must generate kernel models.
4. Run `uv run pytest` — full test suite must pass.
5. Boot each service — must idle gracefully without extensions.

No third-party extension may be necessary for start-up. The melt test is
wired into `validate-release.sh` so no release can ship with a broken kernel.

## The Whole Vertical in One Package

The extensibility promise: one `pip install firnline-ext-example` can add:

- A **schema module** — new classes and enums composed into the schema.
- An **extractor plugin** — LLM extraction logic that turns text into those
  classes.
- **Query tools** — guarded write endpoints that let agents manipulate them.
- **Indexer declaration** — mirrored into the hybrid search index.
- **Trigger evaluators** — new trigger types that fire on domain conditions.
- **Action executors** — external effects these triggers can invoke.

Dropped in and installed, the new domain is capturable, extractable, stored,
queryable, triggerable, and actionable — without touching kernel code.

## Related documents

- [Architecture](architecture.md) — the per-service `HostPolicy` table
- [Entry points reference](../reference/entry-points.md) — full protocol signatures
- [Schema modules reference](../reference/schema-modules.md) — module format and compose workflow
- [Extension development](../development/extension-development.md) — how to build an extension
- [Installing extensions](../guides/installing-extensions.md) — Docker overlay and pip integration
