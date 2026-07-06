# Architecture

## Principles

1. **The database is the integration point.** Modules never call each other
   directly. They read and write TerminusDB documents; status fields *are* the
   work queues.
2. **One domain library, many consumers.** All TerminusDB access goes through
   `firnline-core`: a thin typed async HTTP client and generated Pydantic
   models. No service talks to TerminusDB with raw ad-hoc code.
3. **AI writes with provenance; branches gate trust.** AI-created documents
   carry `derived_from`; AI commits carry `author=<service>` and one commit
   per inbox item.  Trust ladder: dry-run → staging branch → main.
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
                                           InboxNote / InboxAudio (status=new)
                                                   │
┌──────────────────────────────────────────────────┴──────────────────────┐
│                            TERMINUSDB (SSOT)                            │
│  instance graph: Inbox* · Task · Event · Reminder · Person · Location   │
│  schema graph: composed from modules (build artifact)                   │
│  commit graph: audit trail; branches = staging / review boundary        │
└────────┬──────────────────────────┬────────────────────────────────────┘
         │ poll (new/transcribed)   │ GraphQL (read) + tools
         ▼                          ▼
      INGESTD                    QUERYD ◄── POST /v1/chat ── FRONTEND
      poll → extract → link      FastAPI + Pydantic AI
      → insert → flip status     read tools + guarded writes
      per-item commit            LLM via LiteLLM
      LLM via LiteLLM
         │
         ▼
      TRIGGERD
      poll → evaluate → insert
      TriggerFiring records
      per-cycle commit
```

## Components

| Unit | Role | Port |
|---|---|---|
| **TerminusDB** | SSOT graph database (v12.0.6). Stores all entities + schema module registry. | 6363 |
| **captured** | Ingestion API — accepts notes and file uploads; dispatches to pluggable handler plugins. | 8088 |
| **ingestd** | Polling worker — picks up inbox items, runs extractor plugins via LLM, writes typed documents. | — |
| **queryd** | Conversational agent API — read tools, GraphQL, and flag-gated write-tool plugins. | 8087 |
| **triggerd** | Polling worker — evaluates Trigger documents, materializes TriggerFiring records. | — |
| **bootstrap** | One-shot container (profile `bootstrap`) — creates database, composes & applies schema, installs extensions into shared overlay volume. | — |

An **external LiteLLM proxy** is required for LLM access — it is NOT part of
the compose stack.

## Data Flow

1. **Capture** — voice memos arrive via Syncthing → n8n STT pipeline →
   `InboxAudio(status=transcribed)`. Text notes arrive via
   `POST /v1/capture/note` → `InboxNote(status=new)`.
2. **Ingest** — `ingestd` polls for inbox items (source plugins define which
   types/statuses), sends text to LLM with typed output schemas (extractor
   plugins), links known entities (Person, Location), materializes documents
   in one commit per item, flips status.
3. **Query** — `queryd` serves `POST /v1/chat` with full conversation history
   each turn. The agent has read tools (`graphql_query`, `get_document`,
   `get_schema_details`, `today`) and, when `ENABLE_WRITES=true`, registered
   write-tool plugins.
4. **Trigger** — `triggerd` polls for Trigger documents, runs evaluator plugins
   to compute occurrence instants within each cycle's lookback window, and
   materializes `TriggerFiring` records with `status=pending`.  Firing
   statuses are the queue for downstream consumers (reminder delivery,
   notification routing).  The database is the only integration point.

## Schema Module System

The schema is composed from versioned JSON modules, each in a directory
containing:

- **`manifest.json`** — `name`, semver `version`, `depends_on`
  `[{name, range}]`, `exports [ClassNames]`, `description`.
- **`schema.json`** — JSON array of TerminusDB class/enum definitions.
- **`migrations/`** — optional ordered `NNNN_description.py` data migration
  scripts (schema shape changes come from the fragment diff, never from
  migration code).

The `core` module (kernel) stays in `schema/modules/core/` and owns:
`@context`, the contentless markers (`Source`, `Context`, `Remindable`),
registry classes (`SchemaModule`, `SchemaMigration`), and `ExternalRef`.
All domain modules (inbox, planning, people, places, reminders,
routines) live in extensions while core and triggers are first-party in
`schema/modules/`.

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
`promote --branch b` (fast-forward main) → `codegen` (regenerate Pydantic models).

## Plugin Mechanism

Five entry-point groups, discovered via `importlib.metadata.entry_points`:

| Entry-point group | Protocol | Used by | Purpose |
|---|---|---|---|
| `firnline.schema_modules` | directory path | firnline-schema | Contribute a schema module (manifest + schema + migrations) |
| `firnline.ingestd.sources` | `IngestSourcePlugin` | ingestd | Define what document type + status to poll |
| `firnline.ingestd.extractors` | `ExtractorPlugin` | ingestd | Provide proposal models, prompt snippets, linking context, document builders |
| `firnline.queryd.tools` | `ToolPlugin` | queryd | Register Pydantic AI write-tool objects |
| `firnline.captured.handlers` | `CaptureHandler` | captured | Handle capture requests by kind (e.g. "note", "file") |
| `firnline.triggerd.evaluators` | `TriggerEvaluator` | triggerd | Evaluate trigger types, propose occurrence instants |

All three host services follow the same startup behaviour: discover plugins →
`check_requirements` against the `SchemaModule` registry → skip plugins with
unmet requirements (WARNING-level log) → log the active plugin set at INFO.
`--strict-plugins` makes skips fatal. Name/kind collisions between plugins are
fatal at startup.

## Shared Core (`firnline-core`)

- **`tdb.py`** — async TerminusDB HTTP client: `get_documents`, `insert_documents`
  (author + commit message, returns IRIs), `replace_document`, `graphql`. Basic
  auth everywhere; non-2xx raises typed `TdbError(status, body)`.
- **`settings.py`** — shared `TDB_URL / TDB_ORG / TDB_DB / TDB_BRANCH /
  TDB_USER / TDB_PASSWORD` base, subclassed by each service with its own prefix.
- **`plugins.py`** — `ExtractorPlugin`, `ToolPlugin`, `CaptureHandler`,
  `IngestSourcePlugin` protocols, `ModuleRequirement`, `check_requirements`,
  `discover_plugins`, `select_plugins`.
- **`conventions.py`** — `utc_now()`, `BlobStore` (content-addressed file
  storage), `ExternalRef` convention.
- **`generated/`** — codegen output, one file per module. **Never hand-edited.**

### Conventions (system-wide)

- `estimated_duration` in **minutes**; `priority` **1 = highest** (1..5).
- Datetimes stored **UTC** with explicit offset, displayed in **Europe/Zurich**.
- Timezone injected at runtime, never hardcoded.

## Source Code Layout

```
firnline/
├── pyproject.toml              # [tool.uv.workspace] — all packages + extensions
├── compose.yaml                # deployment (external TDB)
├── compose.bundled-tdb.yaml    # overlay adding TerminusDB container
├── schema/modules/core/        # kernel schema module (manifest, schema, context, migrations)
├── schema/modules/triggers/    # trigger schema module
├── packages/
│   ├── firnline-core/          # shared library (tdb client, models, plugins, conventions)
│   └── firnline-schema/        # schema CLI (compose, diff, apply, validate, promote, codegen)
├── services/
│   ├── captured/               # capture ingress (FastAPI)
│   ├── ingestd/                # AI ingestion polling worker
│   ├── queryd/                 # conversational agent (FastAPI)
│   └── triggerd/               # trigger evaluation polling worker
├── extensions/
│   ├── firnline-ext-inbox/     # inbox schema + sources + capture handlers
│   ├── firnline-ext-people/    # people schema + extractor
│   ├── firnline-ext-places/    # places/Location schema
│   ├── firnline-ext-planning/  # planning schema + extractor + queryd tools
│   ├── firnline-ext-reminders/ # reminders schema + extractor + tools
│   └── firnline-ext-routines/  # routines schema
└── docker/entrypoint.sh        # extension overlay management in containers
```
