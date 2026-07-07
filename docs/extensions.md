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
- **Query tool plugins** — write tools the conversational agent can use
   (`firnline.queryd.tools`).
- **Indexer plugins** — tell the `indexed` service which TDB classes to
   mirror into the hybrid search index (`firnline.indexed.indexers`).
- **Capture handlers** — handler for captured's `/v1/capture/note` and
   `/v1/capture/file` endpoints (`firnline.captured.handlers`).
- **Notification channels** — deliver `TriggerFiring` records via external
   notification services (`firnline.notifyd.channels`).

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
planning = "firnline_ext_planning"

[project.entry-points."firnline.ingestd.sources"]
inbox_note = "ingestd.sources:inbox_note_plugin"

[project.entry-points."firnline.ingestd.extractors"]
planning_people = "firnline_ext_planning.extract:plugin"

[project.entry-points."firnline.queryd.tools"]
planning_tools = "firnline_ext_planning.tools:plugin"

[project.entry-points."firnline.captured.handlers"]
inbox_note = "captured.handlers:inbox_note_handler"

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
planning = "firnline_ext_planning:SCHEMA_MODULE_DIR"
```
```python
# firnline_ext_planning/__init__.py
import importlib.resources
SCHEMA_MODULE_DIR = str(importlib.resources.files("firnline_ext_planning"))
```

### `firnline.ingestd.sources` — IngestSourcePlugin

```python
class IngestSourcePlugin(Protocol):
    name: str
    requires: list[ModuleRequirement]
    document_type: str       # e.g. "InboxNote"
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
    produces: list[str]  # class @id values this extractor creates (e.g. ["Task", "Event"])

    def proposal_models(self) -> list[type[BaseModel]]: ...
    def prompt_snippet(self) -> str: ...
    async def linking_context(self, tdb, *, index, branch: str) -> str: ...
    async def build_documents(self, proposal: BaseModel, ctx: BuildContext) -> list[dict]: ...
```

`produces` declares which TDB class `@id` values the extractor creates.
An empty list is valid (e.g. for a linking-only extractor like
`firnline-ext-people`).

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

### `firnline.notifyd.channels` — NotificationChannel

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
entry point that forwards firings to a Gotify server. Configure via
`GOTIFY_URL`, `GOTIFY_TOKEN`, `GOTIFY_PRIORITY`, `GOTIFY_TIMEOUT_SECONDS`
(see [Configuration](configuration.md)).

## Schema Module Format

`manifest.json`:

```json
{
  "name": "planning",
  "version": "0.1.0",
  "depends_on": [{"name": "places", "range": ">=0.1.0 <0.2.0"}],
  "models_target": "firnline_ext_planning.models",
  "exports": ["Task", "TaskSpec", "Event", "TaskStatus", "EventStatus"],
  "description": "Tasks, events and their specs"
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
`ComposeL3Error`).  `queryd` derives its agent briefing from these
`@documentation` comments.

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

1. Discover all plugins for the service's entry-point group.
2. Load each plugin; a plugin that fails to import is logged at ERROR.
3. `check_requirements` against the `SchemaModule` registry in TerminusDB.
4. Plugins with unmet requirements are **skipped with a WARNING** — the service
   still starts.
5. Name/kind collisions between plugins are **fatal** at startup.
6. `--strict-plugins` / `{PREFIX}_STRICT_PLUGINS=true` makes all skips and
   load failures fatal.
7. The active plugin set is logged at INFO on every startup.

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
- PyPI name: `firnline_ext_people>=0.1.0`
- Git URL: `git+https://github.com/user/firnline-ext-foo.git`
- Wheel filename: `firnline_ext_people-0.1.0-py3-none-any.whl` (resolved
  against `/extensions/` in the image)

First-party extension wheels are baked into service images at build time —
no host-side `dist/` directory needed.

## Worked Example: firnline-ext-people

`firnline-ext-people` is a first-party extension that contributes the
`people` schema module (`Person`, `Contact` subdocument) and an extractor
plugin that provides linking context for person names during extraction.

### Package structure

```
extensions/firnline-ext-people/
├── pyproject.toml
└── src/firnline_ext_people/
    ├── __init__.py       # SCHEMA_MODULE_DIR = str(importlib.resources.files(…))
    ├── manifest.json     # name: "people", depends_on: [{places, >=0.1.0 <0.2.0}], models_target: "firnline_ext_people.models"
    ├── schema.json       # Person (Source+Context), Contact (@subdocument)
    ├── models.py         # generated by firnline-schema codegen (never hand-edit)
    └── extract.py        # PeopleLinkingPlugin: linking_context providing known person names
```

### Entry points in pyproject.toml

```toml
[project.entry-points."firnline.schema_modules"]
people = "firnline_ext_people:SCHEMA_MODULE_DIR"

[project.entry-points."firnline.ingestd.extractors"]
people_linking = "firnline_ext_people.extract:plugin"
```

### Using it

Add to `.env`:
```
FIRNLINE_EXTENSIONS=...,firnline_ext_people-0.1.0a1-py3-none-any.whl
```

Then re-bootstrap and restart services. The `people` schema module is composed
into the schema, and ingestd's extractor picks up person-name linking context.

> For the full set of first-party extensions and what each provides, see the
> extension tables in the root [README](../README.md).
