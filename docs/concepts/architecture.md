# Architecture

## Purpose

This page describes the system architecture of firnline — the principles that
govern it, the components and their roles, how data flows between them, and the
extension mechanisms that allow the system to grow. It is for anyone who needs
to understand how the pieces fit together.

## Principles

1. **The database is the integration point.** Modules never call each other
   directly. They read and write TerminusDB documents; status fields *are* the
   work queues.
2. **One domain library, many consumers.** All TerminusDB access goes through
   `firnline-core`: a thin typed async HTTP client and generated Pydantic
   models. No service talks to TerminusDB with raw ad-hoc code.
3. **AI writes with provenance; branches gate trust.** AI-created documents
   carry a required `Provenance` (birth certificate); AI commits carry
   `author=<service>` and one commit per captured item.  Trust ladder:
   dry-run → staging branch → main.  The commit graph is the biography:
   updates are attributed there, deliberately not on the document.
4. **Vertical slices, always usable.** Every layer is built thin-but-complete
   before being deepened. A working end-to-end pipeline beats a polished
   fragment.
5. **Composition over configuration of a monolith.** Growth happens through
   schema modules + service plugins with declared, versioned contracts — not
   by editing core.
6. **Build artifacts are never hand-edited.** The composed schema and the
   generated models are outputs; the module fragments and manifests in the repo
   are the source of truth.

## System overview

```
  Capture device
  ────────────
  voice memo ─► watched dir (Syncthing) ─► STT pipeline
  quick text ─► POST /v1/capture/note ───► captured
                                                    │
                                            Captured (status=new)
                                                    │
┌──────────────────────────────────────────────────┴──────────────────────┐
│                            TERMINUSDB (SSOT)                            │
│  instance graph: Captured · Task · Event · Reminder · Person · Location │
│  schema graph: composed from modules (build artifact)                   │
│  commit graph: audit trail; branches = staging / review boundary        │
└────────┬──────────────────────────┬────────────────────────────────────┘
          │ poll (new/transcribed)   │ GraphQL / find* / tools
          ▼                          ▼
       INGESTD                    QUERYD ◄── mcpd (MCP server)
       poll → extract → link      GraphQL read proxy
       → insert → flip status     document lookup, find entity|class|field
       per-item commit            schema introspection
       LLM via LiteLLM            write-tool endpoints (guarded)
         │
         ▼
       TRIGGERD
       poll → evaluate → insert
       TriggerFiring records
       per-cycle commit
          │
          ▼
       EFFECTD
       poll → plan ActionExecutions → execute via executors
       → legacy notify loop (renotify / expire / snooze wake-up)
       per-firing commit
```

## Components

| Unit | Role | Port |
|---|---|---|
| **TerminusDB** | SSOT graph database (v12.0.6). Stores all entities + schema module registry. | 6363 |
| **captured** | Ingestion API — accepts notes and file uploads; dispatches to pluggable handler plugins. | 8088 |
| **ingestd** | Polling worker — picks up Captured documents, runs extractor plugins via LLM, writes typed documents. | — |
| **queryd** | Conversational agent API — read tools, GraphQL, structured API endpoints, and flag-gated write-tool plugins. | 8087 |
| **mcpd** | MCP server — exposes firnline to external AI agents via Model Context Protocol (streamable HTTP). | 8090 |
| **indexed** | Precision grounding service — mirrors TDB documents + schema into a hybrid vector+lexical index and serves precise-lookup endpoints to ingestd and queryd. | 8089 |
| **triggerd** | Polling worker — evaluates Trigger documents, materializes TriggerFiring records. | — |
| **effectd** | Effect delivery daemon — plans `ActionExecution` records, executes via `ActionExecutor` plugins (webhook, notify, etc.), runs legacy notification loop with nag policy. See [actions](../concepts/actions.md) for the action lifecycle. | — |
| **bootstrap** | One-shot container (profile `bootstrap`) — creates database, composes & applies schema, installs extensions into shared overlay volume. | — |

An **external LiteLLM proxy** is required for LLM access — it is NOT part of
the compose stack.

## Data flow

1. **Capture** — voice memos arrive via Syncthing → n8n STT pipeline →
   `Captured(status=transcribed)`. Text notes arrive via
   `POST /v1/capture/note` → `Captured(status=new)`.
2. **Ingest** — `ingestd` polls for Captured documents, sends text to LLM with
   typed output schemas (extractor plugins), links known entities (Person,
   Location), materializes documents in one commit per item, flips status.
3. **Query** — `queryd` serves GraphQL read queries, document lookup, semantic
   entity/class/field search, schema introspection, and (when
   `QUERYD_ENABLE_WRITES=true`) registered write-tool endpoints. External AI
   agents reach queryd through mcpd, which wraps these endpoints as MCP tools.
4. **Trigger** — `triggerd` polls for Trigger documents, runs evaluator plugins
   to compute occurrence instants within each cycle's lookback window, and
   materializes `TriggerFiring` records. Firing statuses are the queue for
   downstream consumers. The database is the only integration point.
5. **Notify** — `effectd` polls `TriggerFiring` documents: delivers pending
   firings via notification channels, executes the nag policy (renotify,
   expire, wake up snoozed firings), and transitions firing statuses.
6. **Grounding** — `indexed` polls the TDB commit log and mirrors documents
   (via `IndexerPlugin` plugins) and schema into a hybrid vector+lexical index.
   `ingestd` consults it for entity linking beyond casefold-exact match;
   `queryd` uses `find_entity`/`find_class`/`find_field` tools to ground the
   agent before GraphQL queries. If `indexed` is unavailable, both consumers
   degrade gracefully to today's behaviour.

### Direct structured ingestion

When the caller already knows the exact field values for a document, the full
capture → ingest pipeline is unnecessary — there is no free text to
disambiguate. A shortcut path is available: `POST /v1/documents/{class_name}`
on **queryd** accepts a plain JSON object body, validates it against the
TerminusDB schema, and writes it via `Repository.create()` (design law: every
entity write goes through this layer). External AI agents access this path
through **mcpd**'s `create_document` tool. Provenance is recorded via the
`X-Firnline-Agent` header.

## Schema module system

The schema is composed from versioned JSON modules, each in a directory
containing:

- **`manifest.json`** — `name`, semver `version`, `depends_on`
  `[{name, range}]`, `exports [ClassNames]`, `description`, and the required
  codegen routing field `models_target` (dotted Python module path).
- **`schema.json`** — JSON array of TerminusDB class/enum definitions.
- **`migrations/`** — optional ordered `NNNN_description.py` data migration
  scripts (schema shape changes come from the fragment diff, never from
  migration code).

The `core` module (kernel) stays in `schema/modules/core/` and owns:
`@context`, the `Entity` universal base (`created_at`, `updated_at`,
`provenance` — required, exactly one, the birth certificate — `derived_from`,
`archived_at`, `contexts`, `external_refs`), the role markers (`Source`,
`Context`, `Anchored` — all pure markers), the `Provenance` subdocument
(agent, at, method, confidence — agent grammar: `service:<name>`,
`user:<name>`, `ext:<name>`), the kernel `Tag(name)` class, registry
classes (`SchemaModule`, `SchemaMigration`), and `ExternalRef`.

Modules are discovered from two sources: the `schema/modules/` directory
tree, and installed packages via the `firnline.schema_modules` entry-point
group. Discovery runs during `firnline-schema compose`.

### Semver policy

- **MINOR** — additive only: new classes, new Optional fields, new enum
  values, widened exports.
- **MAJOR** — anything else (new required field, type change, removal) —
  must ship with at least one migration file.

The full CLI workflow (`compose` → `diff` → `plan` → `apply` → `validate` →
`promote` → `codegen`) and composer lint layers are documented in the
reference and guides:

- [CLI reference](../reference/cli.md) — all `firnline-schema` commands and flags
- [Schema change guide](../guides/schema-changes.md) — step-by-step workflow for adding or changing a module

## Plugin mechanism

Every service can be extended through Python entry points. A plugin is a
Python package that registers one or more callables under a named entry-point
group (e.g., `firnline.ingestd.extractors`). At startup, each host service
discovers all plugins in its group, validates their module requirements against
the in-database schema registry, checks for naming collisions, and selects the
active set. The shared `PluginHost` in `firnline-core` provides the discovery
→ validate → select → log pipeline; each service tunes its own `HostPolicy`
(fatal vs. degraded behavior on failures).

This means new domains ship as a single installable package containing a
schema module, an extractor plugin for ingestd, a tool plugin for queryd, an
indexer for indexed, and optionally an action executor for effectd — no core
changes needed.

For the full list of entry-point groups, their protocols, and host policies,
see the [entry points reference](../reference/entry-points.md).

## Shared core and conventions

All services share `firnline-core`, which provides:

- **`tdb.py`** — async TerminusDB HTTP client with typed error handling and
  optimistic concurrency.
- **`plugins.py`** — plugin discovery, validation, and selection infrastructure.
- **`conventions.py`** — time utilities, blob storage, the reserved agent naming
  grammar, and the `ExternalRef` convention.
- **`generated/`** — codegen output for kernel modules. **Never hand-edit.**

System-wide conventions: `estimated_duration` in minutes; `priority` 1 = highest
(1..5); datetimes stored UTC with explicit offset, displayed in Europe/Zurich.

## Related documents

- [Vision](../concepts/vision.md) — the why behind the architecture
- [Data model](../concepts/data-model.md) — entity hierarchy and provenance model
- [Actions](../concepts/actions.md) — how triggers flow into external effects
- [Search and grounding](../concepts/search-and-grounding.md) — precision grounding service
- [Entry points reference](../reference/entry-points.md) — all plugin protocols and host policies
- [CLI reference](../reference/cli.md) — `firnline-schema` commands
- [Schema change guide](../guides/schema-changes.md) — adding or changing a module
- [Project structure](../development/project-structure.md) — source code layout
- [Configuration reference](../reference/configuration.md) — environment variables
