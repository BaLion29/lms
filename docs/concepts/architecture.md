# Architecture

How the pieces fit together: services, data flow, plugin mechanism, shared
core, and system-wide conventions.

## Overview

Firnline is a **headless backend** composed of cooperating services that
communicate exclusively through one TerminusDB database. No service calls
another directly; status fields on documents serve as work queues.

## Principles

1. **The database is the integration point.** Modules never call each other
   directly. They read and write TerminusDB documents; status fields *are* the
   work queues.
2. **One domain library, many consumers.** All TerminusDB access goes through
   `firnline-core`: a thin typed async HTTP client and generated Pydantic
   models. No service talks to TerminusDB with raw ad-hoc code.
3. **AI writes with provenance; branches gate trust.** AI-created documents
   carry a required `Provenance` (birth certificate); AI commits carry
   `author=<service>` and one commit per captured item. Trust ladder:
   dry-run → staging branch → main. The commit graph is the biography:
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

## System Overview

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
| **mcpd** | MCP server — exposes firnline to external AI agents via Model Context Protocol (streamable HTTP). Tools: graphql_query, get_document, find_entity/class/field, get_schema, list_modules, capture, create_document. | 8090 |
| **indexed** | Precision grounding service — mirrors TDB documents + schema into a hybrid vector+lexical index and serves precise-lookup endpoints to ingestd and queryd. | 8089 |
| **triggerd** | Polling worker — evaluates Trigger documents, materializes TriggerFiring records. | — |
| **effectd** | Effect delivery daemon — plans `ActionExecution` records, executes via `ActionExecutor` plugins (webhook, notify, etc.), runs legacy notification loop with nag policy (renotify, expire, snooze wake-up). See [actions-and-trust.md](actions-and-trust.md) for the action lifecycle. | — |
| **bootstrap** | One-shot container (profile `bootstrap`) — creates database, composes & applies schema, installs extensions into shared overlay volume. | — |

An **external LiteLLM proxy** is required for LLM access — it is NOT part of
the compose stack.

## Data Flow

1. **Capture** — voice memos arrive via Syncthing → n8n STT pipeline →
   `Captured(status=transcribed)`. Text notes arrive via
   `POST /v1/capture/note` → `Captured(status=new)`.

2. **Ingest** — `ingestd` polls for Captured documents, sends text to LLM with typed output schemas (extractor
   plugins), links known entities (Person, Location), materializes documents
   in one commit per item, flips status.

3. **Query** — `queryd` serves GraphQL read queries (`POST /v1/graphql`),
   document lookup (`GET /v1/documents/{iri}`), semantic entity/class/field
   search (`/v1/find/*`), schema introspection (`/v1/schema`, `/v1/modules`),
   and, when `QUERYD_ENABLE_WRITES=true`, registered write-tool endpoints
   (`GET /v1/tools`, `POST /v1/tools/{name}`). External AI agents reach
   queryd through mcpd, which wraps these endpoints as MCP tools.

4. **Trigger** — `triggerd` polls for Trigger documents, runs evaluator plugins
   to compute occurrence instants within each cycle's lookback window, and
   materializes `TriggerFiring` records with `status=pending`. Firing
   statuses are the queue for downstream consumers (reminder delivery,
   notification routing). The database is the only integration point.

5. **Notify/Effect** — `effectd` polls `TriggerFiring` documents: delivers pending
   firings via executor plugins (entry-point group `firnline.effectd.executors`, with
   legacy `firnline.notifyd.channels` auto-adapted), executes the nag policy
   (renotify after `renotify_every`, expire after `expire_after`, wake up snoozed
   firings), and transitions firing statuses (`pending→notified→expired`, etc.).

6. **Grounding** — `indexed` polls the TDB commit log and mirrors documents
   (via `IndexerPlugin` plugins) and schema into a hybrid vector+lexical index.
   `ingestd` consults it for entity linking beyond casefold-exact match;
   `queryd` uses `find_entity`/`find_class`/`find_field` tools to ground the
   agent before GraphQL queries. If `indexed` is unavailable, both consumers
   degrade gracefully to today's behaviour.

### Direct Structured Ingestion

When the caller already knows the exact field values for a document, the full
capture → ingest pipeline is unnecessary — there is no free text to
disambiguate. A shortcut path is available: `POST
/v1/documents/{class_name}` on **queryd** accepts a plain JSON object body,
validates it against the TerminusDB schema, and writes it via
`Repository.create()` (design law L6: every entity write goes through this
layer). External AI agents access this path through **mcpd**'s
`create_document` tool. Provenance is recorded via the `X-Firnline-Agent`
header (default `service:queryd` when not present; mcpd sets `ext:mcp` so
external-agent writes are correctly attributed).

## Plugin Mechanism

Plugin discovery, validation, and selection are handled by the shared
`PluginHost` in `firnline-core`. Every service configures its own
`HostPolicy` (broken_entry_point_fatal, zero_active_fatal, strict,
tdb_unavailable_fatal) with a stance appropriate to its role.

### Entry Point Groups

| Group | Protocol | Used by | Purpose |
|---|---|---|---|
| `firnline.schema_modules` | directory path | firnline-schema | Contribute a schema module (manifest + schema + migrations) |
| `firnline.ingestd.sources` | `IngestSourcePlugin` | ingestd | Define what document type + status to poll |
| `firnline.ingestd.extractors` | `ExtractorPlugin` | ingestd | Provide proposal models, prompt snippets, linking context, document builders |
| `firnline.queryd.tools` | `ToolSpecPlugin` (canonical) / `ToolPlugin` (legacy) | queryd | Register Pydantic AI write-tool objects (deprecated in favor of `ToolSpecPlugin`) |
| `firnline.captured.handlers` | `CaptureHandler` | captured | Handle capture requests by kind (e.g. "note", "file") |
| `firnline.triggerd.evaluators` | `TriggerEvaluator` | triggerd | Evaluate trigger types, propose occurrence instants |
| `firnline.indexed.indexers` | `IndexerPlugin` | indexed | Declare which TDB classes to mirror and how to extract entity text + aliases |
| `firnline.notifyd.channels` | `NotificationChannel` | effectd | **Deprecated** — auto-adapted to `ActionExecutor`. Migrate to `firnline.effectd.executors`. |
| `firnline.effectd.executors` | `ActionExecutor` | effectd | Execute external effects (notification, webhook, home-automation, etc.) |

Full protocol definitions live in [reference documentation for entry
points](../reference/entry-points.md). The plugin system concept —
including the "everything is an extension" philosophy, dependency resolution,
and the melt test — is covered in [plugin-system.md](plugin-system.md).

## Schema Module System (Summary)

The schema is composed from versioned **schema modules** (directories
containing `manifest.json`, `schema.json`, and optional `migrations/`).
Modules are discovered from the `schema/modules/` directory tree and from
installed packages via the `firnline.schema_modules` entry-point group.

The `core` module (kernel) owns the universal `Entity` base, the role markers
(`Source`, `Context`, `Anchored`, `Trigger` — all pure markers), `Provenance`,
`Tag`, `ExternalRef`, and the registry classes (`SchemaModule`,
`SchemaMigration`). Kernel modules (`core`, `capture`, `triggers`, `actions`)
live in `schema/modules/`. Extension modules live in extension packages.

The `firnline-schema` CLI provides the compose → diff → plan → apply →
validate → promote → codegen workflow. Full details are in the [schema modules
reference](../reference/schema-modules.md).

### Semver Policy

- **MINOR** — additive only: new classes, new Optional fields, new enum
  values, widened exports.
- **MAJOR** — anything else (new required field, type change, removal) —
  must ship with at least one migration file.

## Shared Core (`firnline-core`)

- **`tdb.py`** — async TerminusDB HTTP client: `get_documents`, `insert_documents`
  (author + commit message, returns IRIs), `replace_document` (optimistic concurrency
  via `expected_head`, raises `TdbConflictError`), `get_documents_by_status`
  (server-side status filtering), `changes_since` (commit-log change feed for
  downstream consumers like `indexed` and `EventTrigger`), `graphql`. Basic
  auth everywhere; non-2xx raises typed `TdbError(status, body)`.
- **`settings.py`** — shared `TDB_URL / TDB_ORG / TDB_DB / TDB_BRANCH /
  TDB_USER / TDB_PASSWORD` base, subclassed by each service with its own prefix.
- **`plugins.py`** — `PluginHost`, `HostPolicy`, protocol definitions,
  `ModuleRequirement`, `check_requirements`, `discover_plugins`, `select_plugins`.
- **`conventions.py`** — `utc_now()`, `BlobStore` (content-addressed file
  storage), `ExternalRef` convention, `agent_id()`/`parse_agent()` for the
  reserved agent naming grammar (`service:<name>`, `user:<name>`, `ext:<name>`).
- **`generated/`** — codegen output for kernel modules (core, capture, triggers,
  actions). Extension models land in their own packages, routed by the
  `models_target` manifest field. **Never hand-edit any generated file.**

## Conventions

- `estimated_duration` in **minutes**; `priority` **1 = highest** (1..5).
- Datetimes stored **UTC** with explicit offset, displayed in **Europe/Zurich**.
- Timezone injected at runtime, never hardcoded.

## Source Code Layout

```
firnline/
├── pyproject.toml              # [tool.uv.workspace] — all packages + extensions
├── compose.yaml                # deployment (external TDB)
├── compose.bundled-tdb.yaml    # overlay adding TerminusDB container
├── schema/modules/core/        # kernel schema module (Entity, markers, registry, provenance)
├── schema/modules/capture/     # kernel capture schema module (Captured)
├── schema/modules/triggers/    # kernel trigger schema module
├── schema/modules/actions/     # kernel actions schema module
├── packages/
│   ├── firnline-core/          # shared library (tdb client, models, plugins, conventions)
│   └── firnline-schema/        # schema CLI (compose, diff, apply, validate, promote, codegen)
├── services/
│   ├── captured/               # capture ingress (FastAPI)
│   ├── ingestd/                # AI ingestion polling worker
│   ├── queryd/                 # GraphQL read proxy + write-tool endpoints (FastAPI)
│   ├── mcpd/                   # MCP server for external agents
│   ├── triggerd/               # trigger evaluation polling worker
│   ├── effectd/                # effect delivery daemon (nag policy + channels)
│   ├── indexed/                # precision grounding service (hybrid vector+lexical index)
│   └── webui/                  # Reflex WebUI (Python frontend)
├── extensions/
│   ├── firnline-ext-gotify/    # Gotify notification channel & action executor
│   ├── firnline-ext-webhook/   # Webhook action executor (reference)
│   ├── firnline-ext-people/    # people schema + extractor
│   ├── firnline-ext-places/    # places/Location schema
│   ├── firnline-ext-time-management/  # tasks, events, routines, activities schema + extractor + queryd tools
│   ├── firnline-ext-reminders/ # reminders schema + extractor + tools
└── docker/entrypoint.sh        # extension overlay management in containers
```

See [project structure](../development/project-structure.md) for the rationale
behind this layout.

## Related documents

- [Vision](vision.md) — the ADHD core problem and design principles
- [Entity model](entity-model.md) — Source, Context, Anchored, Trigger markers
- [Plugin system](plugin-system.md) — extensibility in detail
- [Schema modules reference](../reference/schema-modules.md) — full schema module format and compose workflow
- [Entry points reference](../reference/entry-points.md) — protocol definitions
- [Project structure](../development/project-structure.md) — layout rationale
