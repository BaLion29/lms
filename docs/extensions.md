# Extensions

An **extension** is one pip-installable Python package that can add a complete
vertical slice to firnline — capture, extraction, storage, and query — without
touching kernel code.

An extension package may contain any subset of:

- A **schema module** — contributes class/enum definitions to the composed
  schema (discovers via `firnline.schema_modules` entry point). Third-party
  extension models are emitted into the extension's own package via
  `models_target`.
- **Ingest sources** — tell ingestd which document types and statuses to poll
  (`firnline.ingestd.sources`).
- **Extractor plugins** — LLM extraction logic for turning text into typed
  documents (`firnline.ingestd.extractors`).
- **Query tool plugins** — guarded write tools exposed via queryd's `/v1/tools` REST surface
  (`firnline.queryd.tools`).
- **Indexer plugins** — tell the `indexed` service which TDB classes to
  mirror into the hybrid search index (`firnline.indexed.indexers`).
- **Capture handlers** — handler for captured's `/v1/capture/note` and
  `/v1/capture/file` endpoints (`firnline.captured.handlers`).
- **Trigger evaluator plugins** — evaluate trigger conditions for triggerd
  (`firnline.triggerd.evaluators`).
- **Notification channels** — deliver `TriggerFiring` records via external
  notification services (`firnline.notifyd.channels`, legacy group name, consumed by effectd).
- **Action executors** — execute external effects (webhook, notification, home-automation)
  via `firnline.effectd.executors` (canonical group).
- **MCP tools** — mcpd exposes firnline tools and resources to external
  AI agents via Model Context Protocol. See [mcpd.md](mcpd.md).

## Package Layout

```
firnline-ext-example/
├── pyproject.toml
└── src/
    └── firnline_ext_example/
        ├── manifest.json        # schema module manifest
        ├── schema.json          # class/enum definitions
        ├── __init__.py          # optionally expose module paths
        ├── sources.py           # IngestSourcePlugin(s)
        ├── extract.py           # ExtractorPlugin(s)
        ├── tools.py             # ToolPlugin(s)
        └── capture.py           # CaptureHandler(s)
```

## Entry-point Groups and Protocols

Register entry points in `pyproject.toml`:

```toml
[project.entry-points."firnline.schema_modules"]
time_management = "firnline_ext_time_management"

[project.entry-points."firnline.ingestd.sources"]
inbox_note = "ingestd.sources:inbox_note_plugin"

[project.entry-points."firnline.ingestd.extractors"]
time_management_extractor = "firnline_ext_time_management.extract:plugin"

[project.entry-points."firnline.queryd.tools"]
time_management_tools = "firnline_ext_time_management.tools:plugin"

[project.entry-points."firnline.captured.handlers"]
inbox_note = "captured.handlers:captured_note_handler"

[project.entry-points."firnline.triggerd.evaluators"]
oneshot = "firnline_ext_reminders.evaluators:oneshot_plugin"

[project.entry-points."firnline.notifyd.channels"]
gotify = "firnline_ext_gotify.channel:plugin"
```

### `firnline.schema_modules`

Each entry point must resolve to a directory containing `manifest.json` +
`schema.json` (+ optionally `migrations/`). The entry point name must match
the `name` in `manifest.json`.

The entry-point value may be:
- A `str` / `os.PathLike` attribute holding the directory path.
- A package/module object — `importlib.resources.files(obj)` locates the
  directory.

Example:
```toml
[project.entry-points."firnline.schema_modules"]
time_management = "firnline_ext_time_management:SCHEMA_MODULE_DIR"
```
```python
# firnline_ext_time_management/__init__.py
import importlib.resources
SCHEMA_MODULE_DIR = str(importlib.resources.files("firnline_ext_time_management"))
```

### `firnline.ingestd.sources` — IngestSourcePlugin

```python
class IngestSourcePlugin(Protocol):
    name: str
    requires: list[ModuleRequirement]
    document_type: str       # e.g. "Captured"
    ready_status: str        # e.g. "new"
    done_status: str         # e.g. "processed"
    failed_status: str       # e.g. "failed"

    def text(self, doc: dict) -> str: ...
    def reference_time(self, doc: dict) -> datetime: ...
```

ingestd polls `document_type` documents with `status == ready_status`. The
`text()` method extracts the text fed to the extraction agent. Duplicate
`(document_type, ready_status)` pairs are a startup error.

### `firnline.ingestd.extractors` — ExtractorPlugin

```python
class ExtractorPlugin(Protocol):
    name: str
    requires: list[ModuleRequirement]
    requires_classes: list[str]  # optional — class @id values from registry exports
    produces: list[str]  # class @id values this extractor creates (e.g. ["Task", "Event"])
```

`produces` declares which TDB class `@id` values the extractor creates.
An empty list is valid (e.g. for a linking-only extractor like
`firnline-ext-address-book`).

Proposal model `kind` literals must be globally unique across all extractors
(collisions are startup errors). `BuildContext` provides `tdb`, `inbox_iri`,
`now()`, `branch`, and `ensure_entity` — a type-agnostic entity-linker
contract (see below).

### `BuildContext.ensure_entity` contract

Extractors build documents via `build_documents(proposal, ctx)`. The
`ctx.ensure_entity` async callable is the type-agnostic entity linker:

```
async def ensure_entity(type_name: str, name: str, factory: Callable[[], dict | None]) -> str | None
```

It consults the generic `EntityIndex` + `indexed` service (if enabled) to
resolve an entity by `name`, or creates one via a client-supplied `factory()`
that returns a `dict` with an `@id` (e.g. `"Person/anna-meier"`). All
inserts are queued in a single batch; exactly **one commit per inbox item**
is made. Returns the IRI immediately (only `None` if `factory()` returns
`None` and no match was found).

### `firnline.queryd.tools` — ToolPlugin

```python
class ToolPlugin(Protocol):
    name: str
    requires: list[ModuleRequirement]
    requires_classes: list[str]  # optional

    def tools(self, deps) -> list[Tool]: ...
```

Write tools are only registered when `QUERYD_ENABLE_WRITES=true`. Tools
should fetch-mutate-PUT with `updated_at` bump and commit author `queryd`.

### `firnline.indexed.indexers` — IndexerPlugin

```python
class IndexerPlugin(Protocol):
    name: str
    requires: list[ModuleRequirement]

    def indexed_classes(self) -> list[str]: ...
    def entity_text(self, doc: dict) -> str: ...
    def entity_aliases(self, doc: dict) -> list[str]: ...
```

Each plugin declares which TDB document classes to mirror into the hybrid
search index. `entity_text` provides the searchable description (embedded
as a vector); `entity_aliases` provides extra lexical keys for FTS matching.
Duplicate class registrations across active plugins are a startup error.

### `firnline.captured.handlers` — CaptureHandler

```python
class CaptureHandler(Protocol):
    name: str
    kinds: tuple[str, ...]    # e.g. ("note", "file")
    requires: list[ModuleRequirement]

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str: ...
```

`CapturePayload` has `kind`, `text`, `blob_sha256`, `filename`,
`content_type`, `metadata`, `captured_at`. `CaptureContext` provides `tdb`,
`blob_store`, `logger`, `now()`. The handler returns the created document id.
If two handlers claim the same `kind`, it's a startup error.

### `firnline.triggerd.evaluators` — TriggerEvaluator

```python
class TriggerEvaluator(Protocol):
    name: str
    requires: list[ModuleRequirement]
    trigger_types: tuple[str, ...]   # e.g. ("OneShotTrigger", "ScheduleTrigger")

    async def occurrences(
        self,
        trigger: dict,
        *,
        window_start: datetime,
        window_end: datetime,
        ctx: EvalContext,
    ) -> list[datetime]: ...
```

Each evaluator declares which Trigger `@type` strings it handles via
`trigger_types`.  Duplicate `@type` registrations across active evaluators
are a startup error.

`occurrences` receives the raw trigger document dict and the half-open
evaluation window `(window_start, window_end]`.  It must return a list of
timezone-aware UTC `datetime` objects representing the exact instants the
trigger fires — zero-length if the trigger does not fire within the
window.  The engine handles deduplication and insertion.

`EvalContext` fields available to evaluators:

- **`tdb`** — the TerminusDB client (for resolving operands, anchors, etc.)
- **`default_tz`** — the service-configured default timezone (`ZoneInfo`)
- **`now`** — callable returning the current UTC datetime
- **`resolve_anchor(anchor_ref)`** — async, resolves an anchor reference to a datetime
- **`get_occurrences(trigger_dict, window_start, window_end, visited)`** —
  async, dispatches a sub-trigger through the same evaluation pipeline
  (used by composite evaluators)
- **`changes`** — list of `ChangeEvent` from the kernel change feed
  (`TdbClient.changes_since`), consumed by `EventTrigger` evaluators

### `firnline.notifyd.channels` — NotificationChannel (legacy)

> **Deprecated.** Channels are auto-adapted to executors with kind
> `notify:<name>` at effectd startup via `ChannelExecutorAdapter`.
> Migrate to `firnline.effectd.executors`.

```python
class NotificationChannel(Protocol):
    name: str
    requires: list[ModuleRequirement]

    async def deliver(
        self,
        firing: dict[str, Any],
        subject: dict[str, Any] | None,
        ctx: NotifyContext,
    ) -> DeliveryResult: ...
```

Each channel plugin delivers a `TriggerFiring` dict (and its resolved
`subject` document if available) to an external notification service. It
returns a `DeliveryResult(ok, detail, retryable)`. Duplicate channel
`name` values across active plugins are a startup error.

`NotifyContext` provides `tdb`, `logger`, and `now()`.

Example: `firnline-ext-gotify` registers a `firnline.notifyd.channels`
entry point (legacy group name, consumed by effectd) that forwards firings to a Gotify server.
`firnline-ext-webhook` is the reference `firnline.effectd.executors` implementation
that calls arbitrary HTTP endpoints. Configure via
`GOTIFY_URL`, `GOTIFY_TOKEN`, `GOTIFY_PRIORITY`, `GOTIFY_TIMEOUT_SECONDS`,
`WEBHOOK_DEFAULT_TOKEN`, `WEBHOOK_TIMEOUT_SECONDS`
(see [Configuration](configuration.md)).

### `firnline.effectd.executors` — ActionExecutor

```python
class ActionExecutor(Protocol):
    name: str
    requires: list[ModuleRequirement]
    kinds: tuple[str, ...]   # e.g. ("notify:gotify",), ("webhook",), ("hass",)

    async def execute(
        self,
        action: dict[str, Any],
        firing: dict[str, Any],
        subject: dict[str, Any] | None,
        ctx: ActionContext,
    ) -> ExecutionResult: ...
```

Each executor handles one or more executor-kind strings matched against
`Action.executor`. Collisions between active executors on the same kind
are fatal at startup.

`ActionContext` provides `tdb`, `logger`, `now()` (tz-aware UTC default),
`idempotency_key`, and `dry_run`. When `dry_run` is `True`, executors
MUST NOT produce side effects.

```toml
[project.entry-points."firnline.effectd.executors"]
gotify = "firnline_ext_gotify.executor:plugin"
webhook = "firnline_ext_webhook.executor:plugin"
```

## Schema Module Format

`manifest.json`:

```json
{
  "name": "time_management",
  "version": "0.1.0",
  "depends_on": [{"name": "address_book", "range": ">=0.2.0 <0.3.0"}, {"name": "reminders", "range": ">=0.1.0 <0.2.0"}, {"name": "triggers", "range": ">=0.1.0 <0.2.0"}],
  "models_target": "firnline_ext_time_management.models",
  "exports": ["Task", "TaskSpec", "Event", "TaskStatus", "EventStatus", "Routine", "RoutineStep", "Activity", "ActivitySpec"],
  "description": "Tasks, events, routines, activities and their specs"
}
```

Fields:
- `name` — module name, must match entry-point name.
- `version` — semver. Additive changes bump MINOR; breaking changes bump MAJOR
  and require a migration file.
- `depends_on` — modules this module depends on with semver ranges.
- `models_target` — **required**. Dotted Python module path for codegen output.
  Kernel modules use `firnline_core.generated.<name>`; extension modules use
  `firnline_ext_<name>.models` (the owning package). Codegen resolves this
  via `importlib` and writes the generated Pydantic models there.
- `exports` — class/enum `@id` values this module makes available to others.
- `description` — human-readable.

`schema.json` — a JSON array of TerminusDB class/enum definitions in the
standard WOQL schema format. The `@context` object is owned by the `core`
module only; domain modules must not include it.

Every class/enum listed in `exports` **must** carry an `@documentation` key
with a non-empty `@comment` string — "the schema is a prompt". The
`firnline-schema compose` step enforces this (L3 lint violation raises
`ComposeL3Error`). `queryd` derives its agent briefing from these
`@documentation` comments.

**Schema authoring — `@metadata` keys:**

- **`label_field`** — **required** on every exported concrete (non-abstract)
  `Entity` subclass. Names one of the class's own fields whose value is used as
  the display label (L4 composer validation). Example:
  `"@metadata": {"label_field": "name"}`.
- **`anchor_field`** — **required** on every concrete class implementing the
  `Anchored` role marker. Names an `xsd:dateTime` field that holds the
  canonical temporal instant. If the field is unset on a document, relative
  triggers referencing it are dormant (L5 composer validation). Example:
  `"@metadata": {"anchor_field": "start"}`.

**Removed from core** — extensions that previously relied on core constructs
must adapt:
- **`Remindable`** is gone; extensions define their own markers or use
  `Triggerable` (from triggers module) for trigger-owning semantics.
- **`anchor_at`** no longer exists; `Anchored` is a pure role marker — use
  `@metadata.anchor_field` on the implementing class instead.
- **`Provenance.source`** no longer exists; `Provenance` carries only
  `agent`, `at`, `method`, `confidence`. Multi-source derivation lives in
  `Entity.derived_from: Set<Source>`.

`migrations/` — optional directory of `NNNN_description.py` files, each
exporting `async def up(tdb, branch)`. Migrations are **data** migrations
(backfills, copies, status rewrites), not schema shape changes.

## How Third-Party Extensions Get Typed Models

1. The extension's `manifest.json` declares `models_target`, e.g.
   `"models_target": "firnline_ext_myapp.models"`.
2. When `firnline-schema compose` discovers the extension via the
   `firnline.schema_modules` entry point, it records the
   `module_name → models_target` mapping in `ComposeResult.module_to_target`.
3. `firnline-schema codegen` resolves each `models_target` to a filesystem
   path using `importlib` (locating the owning package), classifies classes
   by owning module, and emits one `models.py` per owning package.
4. At runtime, the extension's code imports from its own `models.py` like
   any other Python module — no central registry, no `firnline-core`
   dependency needed for the generated code. Kernel modules land in
   `firnline_core.generated/`; extension models land in the extension's
   own package tree.

## Startup Behaviour (all host services)

All host services boot through the shared `PluginHost` in `firnline-core`:

1. **Discover** all plugins for the service's entry-point group.
2. **Validate** structural conformance against the protocol (when a protocol
   is supplied).
3. **Fetch** the `SchemaModule` registry from TerminusDB (unless pre-fetched).
4. **check_requirements** against installed modules (semver ranges +
   `requires_classes` against registry `exports`).
5. **Collision check** — duplicate keys (e.g. capture kind, tool name, trigger
   type, indexed class) across active plugins are **fatal**.
6. **Select** — active plugins pass all checks; failures are skipped or
   fatal depending on `HostPolicy`.
7. **Log** the active set at INFO on every startup.

Each service configures its own `HostPolicy(broken_entry_point_fatal,
zero_active_fatal, strict, tdb_unavailable_fatal)`. See the per-service table
in [Architecture](architecture.md) for exact values. The `{PREFIX}_STRICT_PLUGINS`
env var drives `strict` (makes requirement failures fatal). Broken
entry-points and zero active plugins can be fatal or warning per service.

## Installing Extensions in Docker

The `docker/entrypoint.sh` script manages extensions via a shared overlay
volume (`firnline_ext_venv`):

1. The **bootstrap** container mounts the overlay read-write, runs
   `pip install --target` for each extension specifier in `FIRNLINE_EXTENSIONS`.
2. Service containers mount the overlay **read-only** and verify extension
   presence at startup.
3. Set `FIRNLINE_EXTENSIONS_PURGE=true` to wipe the overlay before
   reinstalling (e.g. after removing extensions from the list).

Accepted specifier formats:
- PyPI name: `firnline_ext_address_book>=0.2.0`
- Git URL: `git+https://github.com/user/firnline-ext-foo.git`
- Wheel filename: `firnline_ext_address_book-0.2.0-py3-none-any.whl` (resolved
  against `/extensions/` in the image)

First-party extension wheels are baked into service images at build time —
no host-side `dist/` directory needed.

## Worked Example: firnline-ext-address-book

`firnline-ext-address-book` is a first-party extension (module name
`address_book`, version 0.2.0) that contributes the `address_book` schema
module (`Person`, `Contact`, `Location`, `Organization`, `Affiliation`) plus
an entity-linking extractor, an indexer, and a geocoding enricher.

### Package structure

```
extensions/firnline-ext-address-book/
├── pyproject.toml
└── src/firnline_ext_address_book/
    ├── __init__.py       # module_dir = importlib.resources.files(…) / "schema"
    ├── manifest.json     # name: "address_book", version: "0.2.0"
    ├── schema.json       # Person, Contact, Location, Organization, Affiliation
    ├── models.py         # generated by firnline-schema codegen (never hand-edit)
    ├── extract.py        # AddressBookLinkingPlugin: linking_context for entity names
    ├── indexer.py        # AddressBookIndexer: indexes Person/Location/Organization
    └── enrich.py         # Geocoding enricher (effectd executor)
```

### Entry points in pyproject.toml

```toml
[project.entry-points."firnline.schema_modules"]
address_book = "firnline_ext_address_book"

[project.entry-points."firnline.ingestd.extractors"]
address_book_linking = "firnline_ext_address_book.extract:plugin"

[project.entry-points."firnline.indexed.indexers"]
address_book_indexer = "firnline_ext_address_book.indexer:plugin"

[project.entry-points."firnline.effectd.executors"]
address_book_geocoder = "firnline_ext_address_book.enrich:plugin"
```

### Using it

Add to `.env`:
```
FIRNLINE_EXTENSIONS=...,firnline_ext_address_book-0.2.0-py3-none-any.whl
```

Then re-bootstrap and restart services. The `address_book` schema module is
composed into the schema, ingestd's extractor provides entity-linking context,
indexed mirrors Person/Location/Organization documents, and effectd can
geocode Location addresses.

> For the full set of first-party extensions and what each provides, see the
> extension tables in the root [README](../README.md).
