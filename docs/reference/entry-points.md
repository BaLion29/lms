# Entry-point groups reference

## Purpose

This page is the single source of truth for every entry-point group in
firnline's plugin system. It lists the protocol, loading service, and purpose
for each group plus the per-service startup behaviour. For tutorial content,
see [guides/writing-extensions.md](../guides/writing-extensions.md).

## Entry-point groups

| Group | Protocol / signature | Loaded by | Purpose |
|---|---|---|---|
| `firnline.schema_modules` | Directory path containing `manifest.json` + `schema.json` (+ optional `migrations/`) | `firnline-schema` (compose, diff, plan, apply, validate, promote) | Contribute a schema module |
| `firnline.ingestd.sources` | `IngestSourcePlugin` — `name`, `requires`, `document_type`, `ready_status`, `done_status`, `failed_status`, `text(doc)`, `reference_time(doc)` | ingestd | Define what document type and status to poll |
| `firnline.ingestd.extractors` | `ExtractorPlugin` — `name`, `requires`, `requires_classes`, `produces`; `build_documents(proposal, ctx)` produces typed documents via LLM | ingestd | Extract typed documents from free text |
| `firnline.queryd.tools` | `ToolSpecPlugin` — `name`, `requires`, `requires_classes`; `tool_specs()` returns `list[ToolSpec]` (name, description, input_schema, handler) | queryd | Register guarded write-tool endpoints (`/v1/tools`) |
| `firnline.captured.handlers` | `CaptureHandler` — `name`, `kinds` (tuple of kind strings), `requires`; `handle(payload, ctx) -> str` | captured | Handle capture requests by kind (e.g. `"note"`, `"file"`) |
| `firnline.triggerd.evaluators` | `TriggerEvaluator` — `name`, `requires`, `trigger_types` (tuple of `@type` strings); `occurrences(trigger, window_start, window_end, ctx) -> list[datetime]` | triggerd | Evaluate trigger conditions, propose occurrence instants |
| `firnline.indexed.indexers` | `IndexerPlugin` — `name`, `requires`; `indexed_classes() -> list[str]`, `entity_text(doc) -> str`, `entity_aliases(doc) -> list[str]` | indexed | Declare which TDB classes to mirror and how to extract text + aliases for hybrid search |
| `firnline.notifyd.channels` | `NotificationChannel` (legacy) — `name`, `requires`; `deliver(firing, subject, ctx) -> DeliveryResult` | effectd | Deliver `TriggerFiring` records to external notification services (auto-adapted to executors) |
| `firnline.effectd.executors` | `ActionExecutor` — `name`, `requires`, `kinds` (tuple of kind strings); `execute(action, firing, subject, ctx) -> ExecutionResult` | effectd | Execute external effects (notification, webhook, home-automation) |

> `firnline.notifyd.channels` is a legacy group name consumed by effectd.
> Channels are auto-adapted to executors with kind `notify:<name>` via
> `ChannelExecutorAdapter`. New integrations should implement
> `firnline.effectd.executors`.

## PluginHost startup behaviour

All host services boot plugins through the shared `PluginHost` in
`firnline-core`:

1. **Discover** all plugins for the service's entry-point group.
2. **Validate** structural conformance against the protocol.
3. **Fetch** the `SchemaModule` registry from TerminusDB (unless pre-fetched).
4. **check_requirements** — semver ranges against installed modules +
   `requires_classes` against registry `exports`.
5. **Collision check** — duplicate keys (capture kind, tool name, trigger type,
   indexed class, executor kind) across active plugins are fatal at startup.
6. **Select** — active plugins pass all checks; failures are skipped or fatal
   depending on `HostPolicy`.
7. **Log** the active set at INFO on every startup.

## HostPolicy per service

| Service | `broken_entry_point_fatal` | `zero_active_fatal` | `strict` | `tdb_unavailable_fatal` |
|---|---|---|---|---|
| ingestd | `true` | `true` | configurable (`INGESTD_STRICT_PLUGINS`) | default (`true`) |
| queryd | configurable (`QUERYD_STRICT_PLUGINS`) | `false` | configurable | `false` (graceful degradation) |
| captured | `true` | `false` | configurable (`CAPTURED_STRICT_PLUGINS`) | `false` (graceful degradation) |
| triggerd | `true` | `false` | configurable (`TRIGGERD_STRICT_PLUGINS`) | default (`true`) |
| indexed | configurable (`INDEXED_STRICT_PLUGINS`) | `false` | configurable | default (`true`) |
| effectd | `false` | `false` | `false` | default (`true`) |

## EvalContext

`EvalContext` is passed to `TriggerEvaluator.occurrences()` and provides the
following fields to evaluators:

| Attribute | Type | Description |
|---|---|---|
| `tdb` | TerminusDB client | For resolving operands, anchors, etc. |
| `default_tz` | `ZoneInfo` | Service-configured default timezone |
| `now` | `() -> datetime` | Callable returning the current UTC datetime |
| `resolve_anchor(anchor_ref)` | `async (str) -> datetime` | Resolves an anchor reference to a datetime |
| `get_occurrences(trigger_dict, window_start, window_end, visited)` | async dispatcher | Dispatches a sub-trigger through the same evaluation pipeline (used by composite evaluators) |
| `changes` | `list[ChangeEvent]` | List from the kernel change feed (`TdbClient.changes_since`), consumed by `EventTrigger` evaluators |

## Related documents

- [Writing extensions guide](../guides/writing-extensions.md) — tutorial for building extensions
- [Configuration reference](configuration.md) — `{PREFIX}_STRICT_PLUGINS` env vars
- [API reference](api.md) — REST endpoints exposed by plugin-backed services
- [CLI reference](cli.md) — `firnline-schema` commands for schema modules
