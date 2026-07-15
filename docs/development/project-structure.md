# Project Structure

The layout of the firnline monorepo — what each top-level directory contains,
why it exists, and where new code should go.

## `packages/` — shared libraries

These are the only packages that other workspace members depend on directly.

| Package | Responsibility |
|---|---|
| `firnline-core` | Shared domain library: Pydantic models (generated from kernel schema), `TdbClient` (typed async HTTP client for TerminusDB), plugin protocols and `PluginHost`, settings primitives, semver, durations, templates, tool specs. **Everything that touches TerminusDB or the plugin system goes through here.** |
| `firnline-schema` | Schema CLI toolchain: `compose`, `diff`, `plan`, `apply`, `validate`, `promote`, `codegen`. Also builds the bootstrap container image that initializes the database and applies the composed schema. |

## `services/` — deployable daemons

Each service is a standalone process with its own settings prefix, Dockerfile,
and port. They communicate only through TerminusDB (the database is the
integration point). **No service calls another service directly** (except mcpd
which calls queryd+captured over HTTP).

| Service | Responsibility | Port |
|---|---|---|
| `captured` | Capture-ingress API. Accepts notes and file uploads, dispatches to pluggable handlers. | 8088 |
| `ingestd` | Polling worker. Picks up `Captured` documents, runs extractor plugins via LLM, writes typed documents to TerminusDB. | — |
| `queryd` | Read proxy + conversational API. GraphQL, document lookup, `find/*` endpoints, schema introspection, guarded write-tool endpoints. | 8087 |
| `mcpd` | MCP server. Exposes firnline to external AI agents via Model Context Protocol. Calls queryd+captured over HTTP. | 8090 |
| `indexed` | Hybrid search index sidecar. Mirrors TDB documents into a vector+lexical index for precise entity lookups. | 8089 |
| `triggerd` | Polling evaluator. Evaluates `Trigger` documents and materializes `TriggerFiring` records. | — |
| `effectd` | Effect delivery daemon. Plans `ActionExecution` records from firings, executes via `ActionExecutor` plugins (webhook, notify). Also runs the legacy notification loop (nag policy). | — |
| `webui` | Reflex web dashboard. Seven introspection-driven pages: Dashboard, Capture, Inbox, Browse, Health, Modules, Automations. | 3000 |

## `extensions/` — first-party extensions

Six extensions that dogfood the plugin system. Each provides one or more
entry points (schema module, extractor, tools, indexer, executor, etc.).

| Extension | Provides |
|---|---|
| `firnline-ext-time-management` | `time_management` schema module (Task, Event, Routine, Activity, etc.), extractor, queryd write tools, indexer |
| `firnline-ext-reminders` | `reminders` schema module (Reminder), extractor, trigger evaluator, queryd write tools |
| `firnline-ext-people` | `people` schema module (Person, Contact), linking extractor, indexer |
| `firnline-ext-places` | `places` schema module (Location, Address) |
| `firnline-ext-gotify` | Gotify notification channel (legacy) + native ActionExecutor (kind: `notify:gotify`) |
| `firnline-ext-webhook` | Reference ActionExecutor: calls arbitrary HTTP endpoints |

## `schema/modules/` — declarative schema definitions

Each subdirectory is a **kernel schema module**: a `manifest.json` +
`schema.json` pair (plus optional `migrations/`). These are the source of
truth for the database schema — the composed schema and generated models are
build artifacts (never hand-edited).

| Module | Responsibility |
|---|---|
| `core` | Entity base class, markers (Source, Context, Anchored, Triggerable), registry classes (SchemaModule, SchemaMigration), document class (plain document storage) |
| `capture` | Captured class — the inbox replacement (content_type, content, blob_sha256, status) |
| `triggers` | Abstract Trigger and concrete types (OneShotTrigger, ScheduleTrigger, EventTrigger, CompositeTrigger), TriggerFiring, FiringStatus |
| `actions` | Action hierarchy (WebhookAction, NotifyAction), ActionExecution, ActionMode trust ladder (dry_run → approval → auto), ExecutionStatus |

Extension schema modules live inside their respective `extensions/*/`
packages, not here. The kernel modules are always composed; extension
modules are discovered via `firnline.schema_modules` entry points.

## `docker/` — container infrastructure

Contains `entrypoint.sh` — the shared container entrypoint that manages
extension installation into a shared overlay volume. Bootstrap containers
run it in install mode (`FIRNLINE_EXTENSIONS_INSTALL=true`); service
containers mount the overlay read-only.

## `scripts/` — release and validation tooling

| Script | Purpose |
|---|---|
| `validate-release.sh` | Full release gate: no secrets, version consistency, lockfile check, pytest, import smoke, CLI smoke, melt test, docs link check, compose config check |
| `melt-test.sh` | Kernel-purity check — composes + codegens with zero extensions and verifies kernel-only integrity |
| `melt_test/` | pytest suite for kernel melt tests |

## `docs/` — documentation

Reorganized into a topic-based tree. See [documentation.md](documentation.md)
for the structure and style guide.

## `schema/` — (legacy root)

The `schema/` directory at the repo root is the canonical home for kernel
schema modules. It also historically contained a monolithic `schema.json`
for ingestd (since moved to `services/ingestd/schema/schema.json`).

## Where new code goes

| What you're adding | Where it goes |
|---|---|
| A new domain (e.g. "books") with its own schema classes + extraction | New extension in `extensions/` — provides schema module, extractor, optionally tools and indexer |
| A new kernel capability (e.g. a new service) | New directory under `services/` — if it needs schema, add a kernel module under `schema/modules/` |
| A new schema class in an existing domain | Edit the domain's `schema.json` in its existing extension or kernel module |
| A shared utility or protocol | `packages/firnline-core/` — don't duplicate across services |
| A new integration with an external service | New extension under `extensions/` (follow the gotify/webhook pattern for executor plugins) |
| A new write-tool for an existing domain | Add to the domain extension's `tools.py` and register under `firnline.queryd.tools` |

## Related documents

- [../concepts/architecture.md](../concepts/architecture.md) — system design
  and data flow
- [extension-development.md](extension-development.md) — how to build extensions
- [local-development.md](local-development.md) — dev environment setup
