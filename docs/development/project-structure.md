# Project structure

## Purpose

This page explains the directory layout of the firnline monorepo — what each
directory is responsible for and why it exists. For runtime relationships
between components, see the [architecture page](../concepts/architecture.md).

## Top-level layout

```
firnline/
├── pyproject.toml          # Workspace root — [tool.uv.workspace] declares all members
├── compose.yaml            # Docker Compose deployment (bundled TerminusDB included)
├── CHANGELOG.md            # Keep-a-Changelog format; semver versions
├── shell.nix               # Optional Nix development shell (Python 3.12 + uv)
├── packages/               # Shared libraries (no runtime processes)
├── services/               # Deployable daemons (each has its own Dockerfile)
├── extensions/             # First-party extension packages
├── schema/modules/         # Kernel schema module sources
├── docker/                 # Container support files
├── docs/                   # All project documentation (4-tier structure)
└── scripts/                # Release and validation scripts
```

## `packages/` — shared libraries

These provide the common foundation that every service imports. They do not
run as standalone processes.

| Package | Responsibility |
|---|---|
| `firnline-core` | Shared library: async TerminusDB HTTP client (`tdb.py`), generated Pydantic models (kernel classes), plugin protocols (`plugins.py`), conventions (`conventions.py`: UTC helpers, blob store, agent grammar, external refs), and settings base classes. **Every service depends on this.** |
| `firnline-schema` | Schema toolchain CLI: `compose`, `diff`, `plan`, `apply`, `validate`, `promote`, `codegen`. Discovers schema modules from the `schema/modules/` directory and from installed packages via the `firnline.schema_modules` entry-point group. Enforces composer lint layers (L3: documentation, L4: label_field, L5: anchor_field). |

## `services/` — deployable daemons

Each service is a process with its own Dockerfile and `pyproject.toml`.
Services never call each other directly — the database is the only
integration point.

| Service | Responsibility |
|---|---|
| `captured` | Capture-ingress daemon: `POST /v1/capture/note` and `POST /v1/capture/file`. Accepts text and file uploads, creates `Captured` documents, dispatches to pluggable `CaptureHandler` plugins by kind. Minimal FastAPI service (port 8088). |
| `ingestd` | AI ingestion polling worker: picks up `Captured` documents with status `new` or `transcribed`, sends text to an LLM via LiteLLM with typed output schemas, links known entities (Person, Location), materialises `Task`/`Event`/`Reminder` documents in one commit per item, and flips the capture status to `processed`. Uses `ExtractorPlugin` and `IngestSourcePlugin` entry points. |
| `queryd` | GraphQL read proxy and write-tool hub: serves GraphQL queries (`POST /v1/graphql`), document lookup (`GET /v1/documents/{iri}`), entity/class/field search (`/v1/find/*`), schema introspection (`/v1/schema`, `/v1/modules`), and, when `QUERYD_ENABLE_WRITES=true`, guarded write-tool endpoints (`/v1/tools`). FastAPI (port 8087). Model-free — no embedded LLM. |
| `mcpd` | MCP server exposing firnline to external AI agents via the Model Context Protocol (streamable HTTP). Wraps queryd and captured endpoints as MCP tools. Port 8090. |
| `indexed` | Precision grounding service: mirrors TerminusDB documents and schema into a hybrid vector+lexical index (SQLite + embeddings). Provides precise-lookup endpoints to `ingestd` and `queryd` so the LLM does not invent entity names or schema fields. Port 8089. |
| `triggerd` | Trigger evaluation polling worker: evaluates `Trigger` documents via pluggable `TriggerEvaluator` plugins, computes occurrence instants within each cycle's lookback window, and materialises `TriggerFiring` records with `status=pending`. |
| `effectd` | Effect delivery daemon: polls `TriggerFiring` documents, executes `ActionExecutor` plugins (webhook, Gotify notification, etc.), runs the legacy notification loop with nag policy (renotify after `renotify_every`, expire after `expire_after`, wake up snoozed firings). |
| `apid` | **Combined deployment daemon** — bundles `captured`, `queryd`, `indexed`, and `mcpd` into a single process on port 8080. The default for Docker Compose. Uses the same sub-service code paths; each component is configured via its own env-var prefix. |
| `webui` | Reflex-based web dashboard: capture form, inbox (Captured documents), generic class browser (auto-discovers schema classes grouped by module), health monitoring, modules registry, automations page. Port 3000. |

## `extensions/` — first-party extension packages

Six extensions ship in the monorepo. Each is a pip-installable package
providing schema modules, entry points, and generated models. They double as
reference implementations for third-party extension authors.

| Extension | What it contributes |
|---|---|
| `firnline-ext-time-management` | Schema module (`time_management`: Task, Event, Routine, Activity, etc.), extractor plugin, queryd tools (`create_routine`, `update_routine`, `log_activity`) |
| `firnline-ext-address-book` | Schema module (`address_book`: Person, Location, Organization), extractor plugin, indexer plugin, geocoder |
| `firnline-ext-gotify` | Gotify notification channel (legacy) and native `ActionExecutor` |
| `firnline-ext-webhook` | Reference `ActionExecutor` that calls arbitrary HTTP endpoints |
| `firnline-ext-decisions` | Decision/pro-con tracking domain |

Extensions are optional — the kernel (core + capture + triggers schema
modules) must compose, pass tests, and idle gracefully with zero extensions
installed. The melt test (`scripts/melt-test.sh`) enforces this.

## `schema/modules/` — kernel schema modules

Three kernel modules that ship with the system and are always present:

| Module | Owns |
|---|---|
| `core` | `Entity` universal base, role markers (`Source`, `Context`, `Anchored`), `Provenance` subdocument, kernel `Tag`, registry classes (`SchemaModule`, `SchemaMigration`), `ExternalRef` |
| `capture` | `Captured` class — the single capture type (content_type, content, blob_sha256, status machine) |
| `triggers` | `Trigger` abstract root and concrete types (`ScheduleTrigger`, `OneShotTrigger`, `RelativeTrigger`, `EventTrigger`, `CompositeTrigger`), `TriggerFiring`, `Triggerable` mixin |

Each module directory contains `manifest.json` (name, version, dependencies,
exports, `models_target` routing), `schema.json` (class/enum definitions), and
an optional `migrations/` directory.

## `docker/` — container support

Contains `entrypoint.sh` — a shared entrypoint script used by all service
containers to manage extension overlay installation via the
`firnline_ext_venv` shared volume. The bootstrap service installs extension
wheels into this volume; other services mount it read-only.

## `docs/` — documentation

Organised into four tiers plus development and decisions:

| Tier | Directory | Question answered |
|---|---|---|
| Getting started | `getting-started/` | What is this and how do I try it? |
| Concepts | `concepts/` | *Why* does it work this way? |
| Guides | `guides/` | *How* do I accomplish a specific task? |
| Reference | `reference/` | *What* are the exact facts? |
| Development | `development/` | How do I contribute? |
| Decisions | `decisions/` | Why were key choices made? (ADRs) |

## `scripts/` — tooling

- `validate-release.sh` — 15-step release validation (lint, tests, melt
  test, lockfile, version checks, secret scanning, link checking).
- `melt-test.sh` — kernel-purity check: ensures kernel composes, generates,
  imports, and passes tests with zero extensions installed.
- `melt_test/` — dedicated pytest suite for the melt test.

## Related documents

- [Architecture](../concepts/architecture.md) — runtime relationships and data flow
- [Entry points reference](../reference/entry-points.md) — plugin protocols and groups
- [Local development](local-development.md) — how to work with this structure
