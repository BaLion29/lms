# Life-Management System — ARCHITECTURE.md

Companion to `GOAL.md`. This document describes **how** the system is built. It assumes a single-user, self-hosted deployment (Proxmox VM / Docker Compose) with Traefik + Authentik in front of anything HTTP. It is the reconciliation of the original architecture with the `ingestd`, `queryd`, and modularization build specs — where they diverged, this document records what won and why (§9).

---

## 1. Architectural Principles

1. **The database is the integration point.** Modules never call each other directly. They read and write TerminusDB documents; status fields *are* the work queues (`new → transcribed → processed / failed`). Every module is independently restartable, replaceable, and debuggable.
2. **One domain library, many consumers.** All TerminusDB access goes through `lms-core`: a thin typed async HTTP client (`tdb.py`, httpx — deliberately *not* the `terminusdb-client` package) and **generated** Pydantic models. No service talks to TerminusDB with raw ad-hoc code.
3. **AI writes with provenance; branches gate trust.** AI-created documents carry `derived_from`; AI commits carry `author=<service>` and one commit per inbox item. Trust ladder: dry-run → staging branch (`TDB_BRANCH`) → main. Write *tools* (queryd) are additionally gated behind `ENABLE_WRITES` and are typed, narrow, and logged — never a generic mutation surface.
4. **Vertical slices, always usable.** Every layer is built thin-but-complete before being deepened. A working end-to-end pipeline beats a polished fragment.
5. **Composition over configuration of a monolith.** Growth happens through schema modules + service plugins with declared, versioned contracts — not by editing core.
6. **Build artifacts are never hand-edited.** The composed schema and the generated models are outputs; the module fragments in git are the source of truth.

### The six design laws (enforced in code, not just prose)

- **L1** — `core` owns the `@context`, the registry classes (`SchemaModule`, `SchemaMigration`), and the contentless universal markers (`Source`, `Context`, `Remindable`). Other modules **may** define abstract classes (e.g. `triggers` owns `Trigger`); referencing abstracts across modules follows the normal exports rule (L2).
- **L2** — A module's schema may reference only: its own classes, `core` abstracts, and classes listed in the `exports` of modules it names in `depends_on`. The composer walks every class reference and errors on violations.
- **L3** — The composed schema (what TerminusDB sees) is a build artifact (`build/composed.schema.json`), never hand-edited.
- **L4** — Generated Python models are build artifacts too — regenerated, never edited; a CI check fails on codegen drift.
- **L5** — Services and plugins declare module requirements as semver ranges, verified at startup against the in-database registry.
- **L6** — Writes into the SSOT happen only through typed paths: ingestd's pipeline or queryd's registered write tools. GraphQL is read-only (guarded in code).
- **L7** — First-party extensions (`extensions/**`) must use only public kernel contracts: entry points, protocols from `lms_core.plugins`, and the `lms_core` public API. CI enforces that `extensions/**` never imports from service internals.

---

## 2. System Overview

```
  phone / laptop                                   operator / contributor
  ──────────────                                   ──────────────────────
  voice memo ─ Syncthing ─► watched dir            schema/modules/<name>/
  quick text ─────────────► capture endpoint              │
        │                                          lms-schema CLI:
        ▼                                          compose → diff → plan →
  InboxAudio / InboxNote (status=new)              apply → validate →
        │                                          promote → codegen
        │                                                 │
┌───────┴─────────────────────────────────────────────────┴───────────┐
│                         TERMINUSDB (SSOT)                           │
│  instance graph: Inbox* · Task · Event · Reminder · Person ·        │
│    Location · Routine · Activity · Trigger* · SchemaModule ·        │
│    SchemaMigration                                                  │
│  schema graph: composed from modules (build artifact)               │
│  commit graph: audit trail; branches = staging / review boundary    │
└──┬─────────────────┬──────────────────────┬─────────────────────────┘
   │ status=new      │ status=transcribed/  │ GraphQL (read) +
   │ (audio)         │ new (notes)          │ document API (gated writes)
   ▼                 ▼                      ▼
 TRANSCRIPTION     INGESTD                QUERYD ◄── POST /v1/chat ── REFLEX APP
 n8n + Speaches/   poll → extract         FastAPI + Pydantic AI      (lms-frontend)
 faster-whisper    (Pydantic AI, typed    read tools + guarded       chat · inbox ·
 (today; future:   union) → link →        GraphQL · flag-gated       tasks · agenda ·
 transcriberd)     insert (1 commit/item) write-tool plugins         contexts · capture
                   → flip status          LLM via LiteLLM
                   extractor plugins                │
                   LLM via LiteLLM                  ▼
                                          future: REMINDERD ──► ntfy (nag/snooze)
```

Deployable units today: **TerminusDB**, **ingestd**, **queryd**, **Reflex app**, plus the existing n8n/STT capture pipeline. Planned: **reminderd**, **transcriberd**, semantic-search service. All Python components share `lms-core`; LLM calls all go through the **LiteLLM proxy** (OpenAI-compatible, temperature 0).

---

## 3. Repository Layout (uv workspace)

```
lms/
├── pyproject.toml              # [tool.uv.workspace] members
├── README.md                   # env refs, run modes, module tutorial, bootstrap/rollback
├── CHANGELOG.md                # entry per production-touching rollout step
├── compose.yaml                # default (external TDB) deployment
├── compose.bundled-tdb.yaml    # overlay adding a bundled TerminusDB container
├── schema/
│   └── modules/
│       ├── core/               # manifest.json · schema.json · context.json   (markers, @context, registry, ExternalRef)
│       ├── inbox/              # manifest.json · schema.json · migrations/
│       ├── people/             # Person, Contact
│       ├── places/             # Location
│       ├── planning/           # Task, TaskSpec, Event (+ enums)
│       ├── reminders/          # Reminder
│       ├── routines/           # Routine, RoutineStep, Activity, ActivitySpec
│       └── triggers/           # Trigger (abstract) + concrete trigger types + enums
├── build/                      # composed.schema.json · modules.lock.json (artifacts)
├── packages/
│   ├── lms-schema/             # composer · differ · migrator · codegen (library + CLI)
│   └── lms-core/
│       └── src/lms_core/
│           ├── tdb.py          # async TerminusDB HTTP client (typed TdbError)
│           ├── settings.py     # shared TDB_* settings base class
│           ├── plugins.py      # ExtractorPlugin / ToolPlugin protocols, ModuleRequirement
│           └── generated/      # codegen output — DO NOT EDIT (one file per module)
├── services/
│   ├── ingestd/                # pipeline + built-in extractor plugin(s)
│   └── queryd/                 # agent API + built-in write-tool plugin(s)
└── examples/
    └── lms-module-library/     # reference third-party module (Book) — the proof
```

Per-service standards (uniform): Python ≥ 3.12, uv, Pydantic v2 + pydantic-settings, pydantic-ai, httpx, structlog, ruff, pytest (+ pytest-asyncio, respx). Multi-stage non-root Dockerfiles. Configuration exclusively via env vars (`INGESTD_*`, `QUERYD_*`, shared `TDB_*`). Tests run without network (respx for TerminusDB, TestModel/FunctionModel for the LLM).

---

## 4. Schema Module System

### 4.1 Module format

Each `schema/modules/<name>/` contains:

- **`manifest.json`** — `name`, semver `version`, `depends_on: [{name, range}]`, `exports: [ClassNames]`, `description`. `core` is an implicit dependency of everything and is versioned like any module.
- **`schema.json`** — a JSON array of TerminusDB class/enum definitions, same format as the monolithic schema but *without* the `@context` object (only `core` carries that).
- **`migrations/`** — ordered `NNNN_description.py` files exposing `async def up(tdb, branch)`. Migrations are **data** migrations (backfills, copies, status rewrites); schema shape changes come from the fragment diff, never from migration code.

### 4.2 Semver policy (tool-enforced by the differ)

- **MINOR** — additive only: new classes, new `Optional` fields, new enum values, widened exports.
- **MAJOR** — anything else: new required field, type change, removal, enum value removal — and it **must** ship with at least one migration file, or `diff` errors.

### 4.3 In-database registry (`core`)

- `SchemaModule` (Lexical key on `name`): name, version, checksum, installed_at.
- `SchemaMigration`: module, filename, checksum, applied_at.

The registry is what plugins verify their requirements against at runtime, and what `validate`/`/healthz` report.

### 4.4 lms-schema CLI

`compose` (topo-order, L2 validation, duplicate-`@id` check, deterministic output + lock file) → `diff` (against live instance schema *and* previous lock; classifies additive/breaking; enforces §4.2) → `plan` (dry description) → `apply --branch b` (push composed schema, run pending migrations, upsert registry docs; **idempotent**) → `validate --branch b` (smoke GraphQL query per concrete class, registry ⇔ lock) → `promote --branch b` (API merge to main; documented fallback: re-run `apply` on main after branch validation, if schema-graph merges prove unreliable) → `codegen` (§4.5).

The exact TerminusDB mechanics of schema replacement (`full_replace=true`, validation timing vs. migrations-first ordering) are determined empirically against a dev instance and encoded in `apply` — this is precisely where training-data assumptions are banned.

### 4.5 Codegen (models are generated, not written)

`lms-schema codegen` reads the composed schema and emits `lms_core/generated/<module>.py`, following the modeling rules proven by the original hand-written models:

- flattened inheritance (one flat model per concrete class; no Python MI mimicking the schema)
- `@type`/`@id` via aliases + `populate_by_name`; `@id` never set on insert
- document references as **IRI strings** (`str` / `list[str]`), never nested models — except `@subdocument` classes (`Contact`), which nest inline
- `Optional` → `| None = None`, serialized with `exclude_none` (TerminusDB rejects explicit `null`)
- `Set` → `list[...]`, enums → `StrEnum` with exact lowercase values, datetimes serialized ISO 8601 UTC
- `@oneOf` (RoutineStep) → both fields optional + model_validator enforcing exactly-one

Golden round-trip tests pin the exact JSON the document API expects; the hand-written models were only deleted after generated models passed those tests verbatim. A CI check regenerates and fails on any diff.

---

## 5. Shared Core (`lms-core`)

- **`tdb.py`** — the only TerminusDB surface: `get_documents`, `insert_documents` (author + commit message, returns IRIs), `replace_document` (fetch-full → mutate → PUT; the document API has no partial patch), `graphql`. Basic auth everywhere; non-2xx raises typed `TdbError(status, body)` with the raw body preserved verbatim — it is fed back to the LLM on schema-rejection retries.
- **`settings.py`** — shared `TDB_URL / TDB_ORG / TDB_DB / TDB_BRANCH / TDB_USER / TDB_PASSWORD` base; service-specific settings stay in each service.
- **`plugins.py`** — the `ExtractorPlugin` / `ToolPlugin` protocols, `ModuleRequirement`, and `check_requirements(tdb, reqs)` comparing against the registry.
- **`generated/`** — see §4.5.

Conventions (system-wide, non-negotiable): `estimated_duration` in **minutes**; `priority` **1 = highest** (1..5); datetimes stored **UTC** with explicit offset, displayed **Europe/Zurich**; timezone injected at runtime, never hardcoded.

---

## 6. Services

### 6.1 Capture & transcription

Three intake paths converge on inbox documents: (1) **watched/synced directories** — voice memos arrive via Syncthing; the existing n8n pipeline creates `InboxAudio(status=new)`, runs faster-whisper (Speaches), writes `transcription`, flips to `transcribed`; (2) **HTTP capture endpoint** (bearer-token, mounted on the Reflex app's embedded FastAPI) for phone shortcuts; (3) **in-app quick capture** → `InboxNote(status=new)`. Transcription is deliberately behind the status interface — replacing n8n with a dedicated `transcriberd` changes nothing downstream.

### 6.2 ingestd — AI ingestion

Sequential polling loop (asyncio, no broker, no concurrency in v1 — correctness and debuggability first). Per inbox document (`InboxNote@new`, `InboxAudio@transcribed`):

1. **Idempotency guard** — if documents with `derived_from == inbox IRI` already exist (prior crash between insert and flip), just flip status and continue.
2. **Extraction** — one Pydantic AI agent; output is `ExtractionResult{proposals: list[Proposal-union], reasoning, confidence}` where the union is a **discriminated union built dynamically from active extractor plugins** (`kind` literals must be globally unique; collision = startup error). System prompt = core rules (today's date/TZ per run; input may be DE/FR/EN and extracted text stays in the input language; relative dates resolved against the capture's own timestamp; never invent — omit instead; normalize obvious STT mangling cautiously) + concatenated plugin `prompt_snippet()`s + per-cycle `linking_context()`s.
3. **Entity linking (deliberately naive)** — known `Person`/`Location` docs fetched per batch and injected as context; case-insensitive exact match reuses IRIs, unknown locations are created-then-referenced, near-misses are logged, never fuzzy-matched.
4. **Materialize** — plugins convert proposals to document dicts (timestamps, initial status, `derived_from`); **all documents for one inbox item in one commit** (`ingestd: extracted from <IRI>`, author `ingestd`).
5. **Schema-rejection feedback loop** — on `TdbError`, re-run the agent with the raw error appended, up to `MAX_LLM_RETRIES`; then flip to `failed` with full error logged.
6. Flip inbox status to `processed`. Empty proposals is a *valid* result ("nothing actionable") → `processed`.

Any unexpected per-document exception: log traceback, flip to `failed`, continue — **the loop never dies**. Graceful SIGTERM/SIGINT (finish current item, exit 0). Modes: daemon (immediate cycle + interval), `--once`, `--dry-run` (real reads + real LLM, zero writes/flips — the primary manual test mode). Built-in plugin `planning_people` (Task/Event/Reminder/Person extraction; requires planning ≥1.0, people ≥1.0).

### 6.3 queryd — conversational agent

Stateless FastAPI service; the Reflex client sends full conversation history each turn to `POST /v1/chat` (bearer token, constant-time compare) and receives `{message, tool_trace}` — the trace (tool name, truncated input, one-line output summary) feeds a debug drawer in the UI. `GET /healthz` (unauthenticated) reports TerminusDB reachability, installed module versions, and the active plugin list.

One Pydantic AI agent, built once at startup:

- **System prompt**: per-request date/time (Europe/Zurich); a schema briefing generated from the GraphQL SDL at startup (cached) plus the installed-modules list from the registry; behavioral rules (answer in the user's language; never show raw IRIs — resolve to names; sensible ordering; say "nothing found" instead of guessing; compute concrete date ranges from relative dates before querying; never claim a write succeeded without a tool-returned IRI; when writes are disabled, say so instead of pretending).
- **Read tools** (always): `get_schema_details`, `graphql_query` (code-level guards: query-only — mutation/subscription rejected after comment-stripping; 50 KB truncation with visible marker; 10 s timeout; GraphQL errors returned to the agent for self-correction within the cap), `get_document`, `today`.
- **Write tools** (plugins, registered only when `ENABLE_WRITES=true`): `set_task_status`, `set_event_status`, `create_task`, `create_reminder` (verifies `refers_to` target exists and is Task/Event), `update_task`. All fetch-mutate-PUT with `updated_at` bump, commit author `queryd`, return `{"ok": ...}` — never raise into the agent loop; full document logged at INFO.
- **Hard limits**: `MAX_TOOL_ITERATIONS` per request (agent must answer with what it has on cap), `REQUEST_TIMEOUT_SECONDS` → clean 504, provider errors → 502 without leaking keys/prompts.
- **Extension point**: a single `build_tools(settings)` registry with a marked slot for the future `semantic_search` tool.

### 6.4 Reflex frontend (`lms-frontend`)

A client of the services, **not** of the database: chat via queryd (rendering `tool_trace` in a debug drawer), inbox/tasks/agenda/contexts views, quick capture, and the source-chain view ("where did this come from?") on every entity. Mobile-first — the phone is the primary capture and review device. No business logic in the UI layer.

### 6.5 Planned services

- **reminderd** — trigger evaluation loop (APScheduler-style): fire due reminders via ntfy with `Snooze`/`Done` action buttons hitting an ack endpoint; nag until acknowledged. Blocked on the schema additions in §8.
- **transcriberd** — first-class replacement for the n8n STT hop.
- **Semantic search** — vector service plugging into queryd's marked tool slot.
- **Branch review tooling** — per-commit review + promote flow for staging-branch ingestion (successor to the retired proposal queue).

---

## 7. Plugin Mechanism

Discovery via `importlib.metadata.entry_points`:

| Entry-point group | Protocol | Contributes |
| --- | --- | --- |
| `lms.ingestd.extractors` | `ExtractorPlugin` | proposal models (unique `kind` literals), prompt snippet, linking context, `build_documents(proposal, ctx)` |
| `lms.queryd.tools` | `ToolPlugin` | Pydantic AI tool objects (write tools still globally gated by `ENABLE_WRITES`) |

Startup behavior in **both** services: discover plugins → `check_requirements` per plugin against the `SchemaModule` registry → unmet requirements **skip** the plugin with a WARNING (service still starts); `--strict-plugins` turns skips into fatal errors; final active plugin list logged at INFO on every start. Collisions (proposal `kind`s, tool names) are startup errors.

The reference implementation is `examples/lms-module-library`: schema module `library` (class `Book` ← `Source`+`Context`, `lent_to → Person` via a declared dependency on `people`), an extractor turning "Anna hat mir Dune ausgeliehen" into a `Book`, and a `set_book_status` tool. The dev-gated integration test runs the full story — install package, drop module dir, compose → apply → codegen, restart services, ingest a seeded note, query the book through queryd — and **is the definition of "the plugin architecture works."**

---

## 8. Schema: current gaps & planned changes

Status of the original gap list against the live schema, rerouted through the module system (each change now names its module and semver impact):

| # | Change | Module → bump | Status |
| --- | --- | --- | --- |
| 1 | `InboxAudio.transcription` → Optional (doesn't exist at `status=new`) | inbox → **2.0** (required→optional is breaking) + trivial migration | **Open** — currently worked around by the capture pipeline writing an empty string |
| 2 | `ReminderStatus` enum (`pending/triggered/snoozed/dismissed`) + `status` on Reminder | reminders → 2.0 | **Open** — blocks reminderd |
| 3 | Reminder: `snoozed_until`, `nag_interval_minutes`, `last_notified_at` (all Optional) | reminders → same change set as #2 | **Open** — blocks reminderd |
| 4 | ~~`Proposal` staging class~~ | — | **Superseded** (§9.1) |
| 5 | `dropped` in `TaskStatus` + Optional `completed_at` on Task | planning → 1.x (additive) | **Open** — required by the guilt-free-dropping principle; cheap, do with the next planning touch |
| 6 | `Location` class | people | **Done** (name, aliases, coordinates, address) |
| 7 | Work-claiming (`claimed_at` or intermediate statuses) | inbox → 1.x | **Deferred** — v1 runs one strictly sequential worker; becomes relevant only with concurrent workers |
| 8 | Conventions: duration in minutes, priority 1 = highest, UTC storage / Europe/Zurich display | — | **Adopted** — encoded in §5 and in both services' prompts/models |
| 9 | `SchemaModule` + `SchemaMigration` registry classes | core | **Done** (part of modularization rollout) |

New since the original document (already live in the schema): the full **Trigger family** (Schedule/Relative/Context/Event/Composite with enable + validity windows), **Routine/RoutineStep/Activity** (schema-only; no service drives them yet), **Contact** as a `Person` subdocument, **ExternalRef** (@subdocument convention for synced external systems).

Module re-cut (alpha-spec §4): `triggers` (abstract Trigger + concrete types + enums, split from core/planning), `places` (Location, split from people), `reminders` (Reminder, split from planning). Core now owns only contentless markers (Source/Context/Remindable) + registry + ExternalRef. Planning shrinks to Task/Event/specs/enums. Routines depends on planning + triggers.

Evolution process: edit the module fragment (+ migration if breaking) → `compose` → `diff` (guardrails) → `apply` on a dev branch → `validate` → tests → `apply`/`promote` against production per §11.

---

## 9. Superseded Decisions (what changed, and why)

1. **Proposal documents + review queue → provenance + branches.** The application-level staging table required a review UI before the ingestion vertical could ever be "always usable", duplicated machinery TerminusDB provides natively (branches as staging, commits as review units), and added a materialization step. Replaced by: `derived_from` on every AI document, `author=ingestd`, one commit per inbox item, `DRY_RUN`, and `TDB_BRANCH` as the trust dial. Per-item acceptance returns later as branch-review tooling — as an optional module, not a prerequisite.
2. **Monolithic `schema.py` schema-as-code → module fragments + composer.** One Python file could not support independent versioning, third-party modules, or enforced dependency boundaries. The JSON fragments + `lms-schema` toolchain can, and the composed output is provably equivalent to the pre-split schema (test-pinned).
3. **Hand-written Pydantic models → codegen.** Hand-mirroring the schema was the drift risk the original document already worried about ("one place to fix"). Now there is zero places to fix: regenerate.
4. **Frontend importing `lms_core` directly → frontend as an HTTP client of queryd.** Keeps the UI replaceable, keeps all write gating server-side, and gives every future client (shortcuts, bots, TUIs) the same contract.
5. **Generic worker zoo (watcher/transcriber/extractor as siblings) → named services with specs.** Extraction is `ingestd` (spec'd, tested, plugin-hosting); transcription stays behind the status interface (n8n today, `transcriberd` later); the reminder engine is `reminderd` (future). Same topology, but each unit now has a contract instead of a folder.

---

## 10. Cross-cutting Concerns

- **Configuration** — env vars only, per-service prefixes (`INGESTD_*`, `QUERYD_*`) over the shared `TDB_*` base; no config files. `DRY_RUN`, `ENABLE_WRITES`, `--strict-plugins` are the three safety dials.
- **Logging** — structlog everywhere; every processed inbox document produces lines with its IRI and outcome; every pipeline transition logs `doc_id, from_status, to_status`; every write logs the full document at INFO; failures set `status=failed` and are visible in the UI, never silently dropped.
- **Testing** — workspace-wide pytest with **no network**: respx-mocked TerminusDB, Pydantic AI TestModel/FunctionModel for the LLM; golden JSON round-trip tests pin document shapes; codegen-freshness check; a small golden set of real captures guards prompt regressions; dev-container-gated integration tests cover bootstrap → ingest → query and the §7 library-module story. Crash-between-insert-and-flip idempotency is an explicit test.
- **Security** — single-user; Traefik + Authentik in front of all HTTP; bearer tokens on `/v1/chat` and the capture endpoint (constant-time comparison); queryd's GraphQL tool is read-only by code-level guard; write tools are typed, flag-gated, and narrow; error bodies never leak keys or prompts; ntfy topics treated as secrets.
- **Backups** — nightly TerminusDB dump to off-machine storage; **versioning is not a backup**. The production-bootstrap step of the modularization rollout requires a fresh backup + documented restore path *before* first touch (§11).
- **Deployment** — `compose.yaml` for production (external TerminusDB); `compose.bundled-tdb.yaml` overlay for self-contained development with a bundled TerminusDB container. Multi-stage, non-root images; conventional commits per stage.

---

## 11. Rollout State & Migration Path

The system is migrated **in place** — production data is never wiped; every step is shippable and reversible:

1. ✅ `ingestd` end-to-end (models → verified tdb client → extraction → linking → pipeline → bootstrap).
2. ✅ Workspace refactor (Phase 0: `lms-core` extracted, ingestd unchanged-and-green) + `queryd`.
3. ✅ `lms-schema` compose/diff/codegen + module split (composed ≡ current schema confirmed; codegen passes ported golden tests).
4. ✅ Registry classes (core 1.1.0) + plan/apply/validate/promote (verified against dev instance).
5. ⏳ **Production bootstrap** — `apply` on a production branch adds only the two registry classes + registry docs at current versions; backup + restore path documented in `docs/production-bootstrap.md`; validate, promote. First and riskiest production touch; requires explicit operator confirmation.
6. ⏳ Switch to generated models (test suites are the proof of identical behavior); deploy.
7. ⏳ ingestd plugin refactor, then queryd plugin refactor (existing tests pass with at most import-path changes).
8. ⏳ Library example module end-to-end in dev — the architecture's acceptance test.

Steps that touch production each get a `CHANGELOG.md` entry.

---

## 12. Assumptions (flag if wrong)

1. Single user, self-hosted on one always-on machine reachable from the phone (WireGuard/Traefik+Authentik or LAN).
2. Voice memos reach the server via existing file sync (Syncthing) **or** the capture endpoint; sync is the zero-effort default.
3. Cloud LLM via the LiteLLM proxy is acceptable for extraction and querying; local models are a supported fallback behind the same interface, not the default.
4. Captures are mixed German/French/English; the multilingual Whisper model and the language rules in both agents' prompts handle this.
5. TerminusDB API details (document endpoints, schema replacement semantics, GraphQL filter syntax, branch merge behavior) are **verified empirically against a dev instance** wherever a spec says VERIFY — never assumed from training data.
6. n8n remains optional glue for capture/transcription; nothing downstream depends on it existing.

---

_Last updated: 2026-07-05 — reconciled with the ingestd/queryd/modularization specs: uv-workspace layout, schema module system + lms-schema toolchain + codegen, plugin mechanism with registry-checked requirements, service contracts for ingestd/queryd, updated gap table (Location done, Proposal superseded, ReminderStatus/dropped-status still open), new Superseded Decisions section, and the ordered live-data migration path._
