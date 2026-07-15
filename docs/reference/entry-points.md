# Entry Points

Complete reference of all Python entry-point groups in firnline. Extensions
register via `[project.entry-points."<group>"]` in `pyproject.toml`.

## Group summary

| Entry-point group | Protocol | Consumed by | Purpose |
|---|---|---|---|
| `firnline.schema_modules` | directory path | firnline-schema | Contribute a schema module (manifest + schema + migrations) |
| `firnline.ingestd.sources` | `IngestSourcePlugin` | ingestd | Define what document type + status to poll |
| `firnline.ingestd.extractors` | `ExtractorPlugin` | ingestd | Provide proposal models, prompt snippets, linking context, document builders |
| `firnline.queryd.tools` | `ToolSpecPlugin` (canonical) / `ToolPlugin` (legacy) | queryd | Register write-tool specs exposed via `/v1/tools` |
| `firnline.captured.handlers` | `CaptureHandler` | captured | Handle capture requests by kind (e.g. "note", "file") |
| `firnline.triggerd.evaluators` | `TriggerEvaluator` | triggerd | Evaluate trigger types, propose occurrence instants |
| `firnline.indexed.indexers` | `IndexerPlugin` | indexed | Declare which TDB classes to mirror and how to extract entity text + aliases |
| `firnline.effectd.executors` | `ActionExecutor` | effectd | Execute external effects (notification, webhook, home-automation, etc.) |
| `firnline.notifyd.channels` | `NotificationChannel` | effectd | **Deprecated** — auto-adapted to `ActionExecutor`. Migrate to `firnline.effectd.executors`. |

## `firnline.schema_modules`

Each entry point must resolve to a directory containing `manifest.json` +
`schema.json` (+ optionally `migrations/`). The entry-point name must match
the `name` field in `manifest.json`.

The value may be:
- A `str` / `os.PathLike` attribute holding the directory path.
- A package/module object — `importlib.resources.files(obj)` locates it.

```toml
[project.entry-points."firnline.schema_modules"]
time_management = "firnline_ext_time_management:SCHEMA_MODULE_DIR"
```

See [schema-modules reference](schema-modules.md) for the module format.

## `firnline.ingestd.sources` — `IngestSourcePlugin`

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

## `firnline.ingestd.extractors` — `ExtractorPlugin`

```python
class ExtractorPlugin(Protocol):
    name: str
    requires: list[ModuleRequirement]
    requires_classes: list[str]     # optional — class @id values from registry exports
    produces: list[str]             # class @id values this extractor creates

    def proposal_models(self) -> list[type[BaseModel]]: ...
    def prompt_snippet(self) -> str: ...
    async def linking_context(self, tdb, *, index, branch: str) -> str: ...
    async def build_documents(self, proposal: BaseModel, ctx: BuildContext) -> list[dict]: ...
```

`produces` declares which TDB class `@id` values the extractor creates.
An empty list is valid (e.g. linking-only extractors). Proposal model
`kind` literals must be globally unique across all extractors (collision
is a startup error).

`BuildContext` provides `tdb`, `captured_iri`, `now()`, `branch`, and
`ensure_entity` — a type-agnostic entity-linker.

### `BuildContext.ensure_entity` contract

```python
async def ensure_entity(type_name: str, name: str, factory: Callable[[], dict | None]) -> str | None
```

Consults the generic `EntityIndex` + `indexed` service (if enabled) to
resolve an entity by `name`, or creates one via a client-supplied
`factory()` that returns a `dict` with an `@id`. All inserts are queued in
a single batch; exactly one commit per inbox item.

## `firnline.queryd.tools` — `ToolSpecPlugin` (canonical)

```python
class ToolSpecPlugin(Protocol):
    name: str
    requires: list[ModuleRequirement]

    def tool_specs(self) -> list[ToolSpec]: ...
```

`ToolSpec` is framework-neutral (name, description, input_schema,
args_model, handler). This is the canonical interface. The legacy
`ToolPlugin` protocol (`def tools(self, deps) -> list[Tool]`) is still
accepted for backward compatibility.

Write tools are only registered when `QUERYD_ENABLE_WRITES=true`. Tools
should fetch-mutate-PUT with `updated_at` bump and commit author `queryd`.

## `firnline.captured.handlers` — `CaptureHandler`

```python
class CaptureHandler(Protocol):
    name: str
    kinds: tuple[str, ...]    # e.g. ("note", "file")
    requires: list[ModuleRequirement]

    async def handle(self, payload: CapturePayload, ctx: CaptureContext) -> str: ...
```

`CapturePayload` has `kind`, `text`, `blob_sha256`, `filename`,
`content_type`, `metadata`, `captured_at`. `CaptureContext` provides `tdb`,
`blob_store`, `logger`, `now()`. The handler returns the created document
id. If two handlers claim the same `kind`, it's a startup error.

## `firnline.triggerd.evaluators` — `TriggerEvaluator`

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
`trigger_types`. Duplicate `@type` registrations are a startup error.
`occurrences` receives the raw trigger document dict and a half-open
evaluation window. Returns a list of tz-aware UTC datetimes.

`EvalContext` fields: `tdb`, `default_tz` (ZoneInfo), `now()`,
`resolve_anchor(anchor_ref)`, `get_occurrences(...)`, `changes` (list of
`ChangeEvent`).

## `firnline.indexed.indexers` — `IndexerPlugin`

```python
class IndexerPlugin(Protocol):
    name: str
    requires: list[ModuleRequirement]

    def indexed_classes(self) -> list[str]: ...
    def entity_text(self, doc: dict) -> str: ...
    def entity_name(self, doc: dict) -> str: ...
    def entity_aliases(self, doc: dict) -> list[str]: ...
```

Each plugin declares which TDB document classes to mirror into the hybrid
search index. `entity_text` provides the searchable description (embedded
as a vector); `entity_name` provides the primary display label;
`entity_aliases` provides extra lexical keys for FTS matching. Duplicate
class registrations across active plugins are a startup error.

## `firnline.effectd.executors` — `ActionExecutor`

```python
class ActionExecutor(Protocol):
    name: str
    requires: list[ModuleRequirement]
    kinds: tuple[str, ...]   # e.g. ("notify:gotify",), ("webhook",), ("hass",)

    async def execute(
        self,
        action: dict,
        firing: dict,
        subject: dict | None,
        ctx: ActionContext,
    ) -> ExecutionResult: ...
```

Each executor handles one or more executor-kind strings matched against
`Action.executor`. Collisions between active executors on the same kind
are fatal at startup.

`ActionContext` provides `tdb`, `logger`, `now()` (tz-aware UTC),
`idempotency_key`, and `dry_run`. When `dry_run` is `True`, executors
MUST NOT produce side effects.

`ExecutionResult(ok, detail, retryable, external_ref)`.

## `firnline.notifyd.channels` — `NotificationChannel` (deprecated)

> **Deprecated.** Channels are auto-adapted to executors with kind
> `notify:<name>` at effectd startup via `ChannelExecutorAdapter`.
> Migrate to `firnline.effectd.executors`.

```python
class NotificationChannel(Protocol):
    name: str
    requires: list[ModuleRequirement]

    async def deliver(
        self,
        firing: dict,
        subject: dict | None,
        ctx: NotifyContext,  # alias of ActionContext
    ) -> DeliveryResult: ...  # alias of ExecutionResult
```

Each channel plugin delivers a `TriggerFiring` dict (and its resolved
`subject` document if available) to an external notification service.
Duplicate channel `name` values across active plugins are a startup error.

## `ModuleRequirement`

Used by all plugin protocols to declare schema-module dependencies:

```python
class ModuleRequirement(BaseModel):
    name: str     # module name
    range: str    # semver range, e.g. ">=1.0.0 <2.0.0"
```

## Startup sequence

All host services boot through the shared `PluginHost` in `firnline-core`:

1. **Discover** all plugins for the service's entry-point group.
2. **Validate** structural conformance against the protocol.
3. **Fetch** the `SchemaModule` registry from TerminusDB.
4. **check_requirements** against installed modules (semver ranges +
   `requires_classes` against registry `exports`).
5. **Collision check** — duplicate keys (capture kind, tool name, trigger
   type, indexed class, executor kind, channel name) across active plugins
   are **fatal**.
6. **Select** — active plugins pass all checks; failures are skipped or
   fatal depending on `HostPolicy`.
7. **Log** the active set at INFO on every startup.

## `HostPolicy` per service

| Service | `broken_entry_point_fatal` | `zero_active_fatal` | `strict` | `tdb_unavailable_fatal` |
|---|---|---|---|---|
| ingestd | `True` | `True` | configurable (`INGESTD_STRICT_PLUGINS`) | `True` (default) |
| queryd | configurable (`QUERYD_STRICT_PLUGINS`) | `False` | configurable (`QUERYD_STRICT_PLUGINS`) | `False` (graceful degradation) |
| captured | `True` | `False` | configurable (`CAPTURED_STRICT_PLUGINS`) | `False` (graceful degradation) |
| triggerd | `True` | `False` | configurable (`TRIGGERD_STRICT_PLUGINS`) | `True` (default) |
| indexed | configurable (`INDEXED_STRICT_PLUGINS`) | `False` | configurable (`INDEXED_STRICT_PLUGINS`) | `True` (default) |
| effectd | `False` | `False` | `False` (n/a — no STRICT_PLUGINS on channels) | `True` (default) |

The `{PREFIX}_STRICT_PLUGINS` env var drives the `strict` policy (makes
requirement failures fatal). `broken_entry_point_fatal` controls
entry-point load failures. `zero_active_fatal` controls whether an empty
active plugin list is an error or a warning.

## Related documents

- [Plugin system](../concepts/plugin-system.md)
- [Architecture](../concepts/architecture.md)
- [Extension development](../development/extension-development.md)
- [Schema modules](schema-modules.md)
