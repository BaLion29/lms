# Architecture

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
| **effectd** | Effect delivery daemon — plans `ActionExecution` records, executes via `ActionExecutor` plugins (webhook, notify, etc.), runs legacy notification loop with nag policy (renotify, expire, snooze wake-up). See [docs/actions.md](actions.md) for the action lifecycle. | — |
| **bootstrap** | One-shot init container — waits for TDB, creates database, composes & applies schema, installs extensions. Exits after completion. | — |

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
    queryd through mcpd, which wraps these endpoints as MCP tools (see
    [mcpd](mcpd.md)).
4. **Trigger** — `triggerd` polls for Trigger documents, runs evaluator plugins
   to compute occurrence instants within each cycle's lookback window, and
   materializes `TriggerFiring` records with `status=pending`.  Firing
   statuses are the queue for downstream consumers (reminder delivery,
   notification routing).  The database is the only integration point.
5. **Notify** — `effectd` polls `TriggerFiring` documents: delivers pending
   firings via `NotificationChannel` plugins (entry-point group
   `firnline.notifyd.channels`), executes the nag policy (renotify after
   `renotify_every`, expire after `expire_after`, wake up snoozed firings),
   and transitions firing statuses (`pending→notified→expired`, etc.).
6. **Grounding** — `indexed` polls the TDB commit log and mirrors documents
   (via `IndexerPlugin` plugins) and schema into a hybrid vector+lexical index.
   `ingestd` consults it for entity linking beyond casefold-exact match;
   `queryd` uses `find_entity`/`find_class`/`find_field` tools to ground the
   agent before GraphQL queries.  If `indexed` is unavailable, both consumers
    degrade gracefully to today's behaviour.

### Direct Structured Ingestion

When the caller already knows the exact field values for a document, the full
capture → ingest pipeline is unnecessary — there is no free text to
disambiguate.  A shortcut path is available: ``POST
/v1/documents/{class_name}`` on **queryd** accepts a plain JSON object body,
validates it against the TerminusDB schema, and writes it via
``Repository.create()`` (design law L6: every entity write goes through this
layer).  External AI agents access this path through **mcpd**'s
``create_document`` tool.  Provenance is recorded via the ``X-Firnline-Agent``
header (default ``service:queryd`` when not present; mcpd sets ``ext:mcp`` so
external-agent writes are correctly attributed).

## Schema Module System

The schema is composed from versioned JSON modules, each in a directory
containing:

- **`manifest.json`** — `name`, semver `version`, `depends_on`
  `[{name, range}]`, `exports [ClassNames]`, `description`, and the required
  codegen routing field `models_target` (dotted Python module path, e.g.
  `firnline_core.generated.core` for kernel modules or
  `firnline_ext_time_management.models` for extensions).
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
`user:<name>`, `ext:<name>`), the kernel `Tag(name)` class (a minimal
blessed Context for frictionless cross-extension tagging), registry
classes (`SchemaModule`, `SchemaMigration` — `SchemaModule.exports`
stores the module's exported class @ids, written at install), and
`ExternalRef`. All domain modules (planning, people, places, reminders,
routines) live in extensions; core, triggers, and capture are kernel
modules in `schema/modules/`.

Modules are discovered from two sources: the `schema/modules/` directory
tree, and installed packages via the `firnline.schema_modules` entry-point
group. Discovery runs during `firnline-schema compose`.

### Semver policy

- **MINOR** — additive only: new classes, new Optional fields, new enum
  values, widened exports.
- **MAJOR** — anything else (new required field, type change, removal) —
  must ship with at least one migration file.

### firnline-schema CLI workflow

`compose` → `diff` (classifies additive/breaking) → `plan` (dry description)
→ `apply --branch b` (push schema, run migrations, upsert registry; idempotent)
→ `validate --branch b` (GraphQL smoke tests, registry ⇔ lock) →
`promote --branch b` (fast-forward main) → `codegen` (regenerate Pydantic models
per owning package via `models_target`).

**Composer lint layers**: during compose, every class/enum listed in a module's
`exports` must carry an `@documentation` key with a non-empty `@comment`
string — "the schema is a prompt" (L3). Exported concrete `Entity` subclasses
must declare `@metadata.label_field` (L4). Classes implementing `Anchored`
must declare `@metadata.anchor_field` naming an `xsd:dateTime` field (L5).
`queryd` derives its agent briefing from these `@documentation` comments.

## Plugin Mechanism

Eight entry-point groups, discovered via `importlib.metadata.entry_points`:

| Entry-point group | Protocol | Used by | Purpose |
|---|---|---|---|
| `firnline.schema_modules` | directory path | firnline-schema | Contribute a schema module (manifest + schema + migrations) |
| `firnline.ingestd.sources` | `IngestSourcePlugin` | ingestd | Define what document type + status to poll |
| `firnline.ingestd.extractors` | `ExtractorPlugin` | ingestd | Provide proposal models, prompt snippets, linking context, document builders |
| `firnline.queryd.tools` | `ToolPlugin` | queryd | Register Pydantic AI write-tool objects |
| `firnline.captured.handlers` | `CaptureHandler` | captured | Handle capture requests by kind (e.g. "note", "file") |
| `firnline.triggerd.evaluators` | `TriggerEvaluator` | triggerd | Evaluate trigger types, propose occurrence instants |
| `firnline.indexed.indexers` | `IndexerPlugin` | indexed | Declare which TDB classes to mirror and how to extract entity text + aliases |
| `firnline.notifyd.channels` | `NotificationChannel` | effectd | Deliver `TriggerFiring` records via external notification services (legacy, auto-adapted to executors) |
| `firnline.effectd.executors` | `ActionExecutor` | effectd | Execute external effects (notification, webhook, home-automation, etc.) |

All host services boot through the shared `PluginHost` in `firnline-core`
(discover → validate → check_requirements → collision check → select →
log). Each service configures a `HostPolicy` with its own stance on failures.
Plugins may declare `requires_classes: list[str]` in addition to
`requires: list[ModuleRequirement]` — checked against registry `exports`
at startup. Name/kind collisions between active plugins are fatal at
startup. Per-service policies:

| Service | broken_entry_point_fatal | zero_active_fatal | strict | tdb_unavailable_fatal |
|---|---|---|---|---|
| ingestd | true | true | configurable | default (true) |
| queryd | configurable | false | configurable | false (graceful degradation) |
| captured | true | false | configurable | false (graceful degradation) |
| triggerd | true | false | configurable | default (true) |
| indexed | configurable (strict) | false | configurable (strict) | default (true) |
| effectd | false | false | false | default (true) |

## Shared Core (`firnline-core`)

- **`tdb.py`** — async TerminusDB HTTP client: `get_documents`, `insert_documents`
  (author + commit message, returns IRIs), `replace_document` (optimistic concurrency
  via `expected_head`, raises `TdbConflictError`), `get_documents_by_status`
  (server-side status filtering), `changes_since` (commit-log change feed for
  downstream consumers like `indexed` and `EventTrigger`), `graphql`. Basic
  auth everywhere; non-2xx raises typed `TdbError(status, body)`.
- **`settings.py`** — shared `TDB_URL / TDB_ORG / TDB_DB / TDB_BRANCH /
  TDB_USER / TDB_PASSWORD` base, subclassed by each service with its own prefix.
- **`plugins.py`** — `ExtractorPlugin`, `ToolPlugin`, `CaptureHandler`,
  `IngestSourcePlugin`, `ActionExecutor`, `ActionContext`, `ExecutionResult`,
  `ChannelExecutorAdapter` protocols/datatypes, `ModuleRequirement`,
  `check_requirements`, `discover_plugins`, `select_plugins`.
- **`conventions.py`** — `utc_now()`, `BlobStore` (content-addressed file
  storage), `ExternalRef` convention, `agent_id()`/`parse_agent()` for the
  reserved agent naming grammar (`service:<name>`, `user:<name>`, `ext:<name>`).
- **`generated/`** — codegen output for kernel modules (core, capture, triggers).
  Extension models land in their own packages (e.g. `firnline_ext_time_management/
  models.py`), routed by the `models_target` manifest field. **Never
  hand-edit any generated file.**

### Conventions (system-wide)

- `estimated_duration` in **minutes**; `priority` **1 = highest** (1..5).
- Datetimes stored **UTC** with explicit offset, displayed in **Europe/Zurich**.
- Timezone injected at runtime, never hardcoded.

## Source Code Layout

```
firnline/
├── pyproject.toml              # [tool.uv.workspace] — all packages + extensions
├── compose.yaml                # deployment (bundled TerminusDB included, removable)
├── schema/modules/core/        # kernel schema module (Entity, markers, registry, provenance)
├── schema/modules/capture/      # kernel capture schema module (Captured)
├── schema/modules/triggers/    # kernel trigger schema module
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
│   └── indexed/                # precision grounding service (hybrid vector+lexical index)
├── extensions/
│   ├── firnline-ext-gotify/    # Gotify notification channel & action executor
│   ├── firnline-ext-webhook/   # Webhook action executor (reference)
│   ├── firnline-ext-people/    # people schema + extractor
│   ├── firnline-ext-places/    # places/Location schema
│   ├── firnline-ext-time-management/  # tasks, events, routines, activities schema + extractor + queryd tools
│   ├── firnline-ext-reminders/ # reminders schema + extractor + tools
└── docker/entrypoint.sh        # extension overlay management in containers
```
