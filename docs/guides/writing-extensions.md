# Writing extensions

## Purpose

How to build, package, and register a firnline extension. Extensions add
complete vertical slices — capture handlers, extractors, tools, schema modules,
and more — without modifying kernel code. This guide covers package layout,
schema module format, entry-point registration, and runtime behaviour.

An extension is one pip-installable Python package. A single extension package
may contain any subset of the available plugin types.

## Package layout

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

## Entry-point registration

Register your plugins in `pyproject.toml` under the appropriate entry-point
groups. Each group corresponds to one extension point in a specific firnline
service:

| Group | What you implement | Managed by |
|---|---|---|
| `firnline.schema_modules` | Schema module directory with `manifest.json` + `schema.json` (+ optional `migrations/`) | All services (via `firnline-core`) |
| `firnline.ingestd.sources` | `IngestSourcePlugin` — declares what ingestd polls | ingestd |
| `firnline.ingestd.extractors` | `ExtractorPlugin` — LLM extraction logic for text → typed docs | ingestd |
| `firnline.queryd.tools` | `ToolPlugin` — guarded write tools on `/v1/tools` REST surface | queryd |
| `firnline.indexed.indexers` | `IndexerPlugin` — TDB classes to mirror into hybrid search index | indexed |
| `firnline.captured.handlers` | `CaptureHandler` — handles `/v1/capture/note` and `/v1/capture/file` | captured |
| `firnline.triggerd.evaluators` | `TriggerEvaluator` — evaluates trigger conditions | triggerd |
| `firnline.notifyd.channels` | `NotificationChannel` (legacy; auto-adapted to executors) | effectd |
| `firnline.effectd.executors` | `ActionExecutor` — executes external effects (webhook, notify, home-automation) | effectd |

For the full protocol signatures, required fields, and collision rules for
each group, see [../reference/entry-points.md](../reference/entry-points.md).

Example `pyproject.toml`:

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

## Schema module format

A schema module contributes class and enum definitions to the composed schema.
It is discovered via the `firnline.schema_modules` entry-point group.

### manifest.json

```json
{
  "name": "time_management",
  "version": "0.1.0",
  "depends_on": [
    {"name": "address_book", "range": ">=0.2.0 <0.3.0"},
    {"name": "reminders", "range": ">=0.1.0 <0.2.0"},
    {"name": "triggers", "range": ">=0.1.0 <0.2.0"}
  ],
  "models_target": "firnline_ext_time_management.models",
  "exports": ["Task", "TaskSpec", "Event", "EventStatus", "Routine", "RoutineStep", "Activity", "ActivitySpec"],
  "description": "Tasks, events, routines, activities and their specs"
}
```

Fields:

- `name` — module name, must match the entry-point name.
- `version` — semver. Additive changes bump MINOR; breaking changes bump MAJOR
  and require a migration file.
- `depends_on` — modules this module depends on, with semver ranges.
- `models_target` — **required**. Dotted Python module path where codegen
  writes Pydantic models. Kernel modules use `firnline_core.generated.<name>`;
  extension modules use `firnline_ext_<name>.models` (the owning package).
- `exports` — class/enum `@id` values this module makes available to others.
- `description` — human-readable.

### schema.json

A JSON array of TerminusDB class/enum definitions in the standard WOQL schema
format. The `@context` object is owned by the `core` module only; domain
modules must **not** include it.

Every class/enum listed in `exports` **must** carry an `@documentation` key
with a non-empty `@comment` string — "the schema is a prompt". The compose
step enforces this. `queryd` derives its agent briefing from these comments.

### @metadata keys

- **`label_field`** — **required** on every exported concrete (non-abstract)
  `Entity` subclass. Names one of the class's own fields whose value is used as
  the display label.
- **`anchor_field`** — **required** on every concrete class implementing the
  `Anchored` role marker. Names an `xsd:dateTime` field that holds the
  canonical temporal instant. If the field is unset on a document, relative
  triggers referencing it are dormant.

#### Migration notes

**Removed from core** — extensions that previously relied on core constructs
must adapt:

- **`Remindable`** is gone; extensions define their own markers or use
  `Triggerable` (from triggers module) for trigger-owning semantics.
- **`anchor_at`** no longer exists; `Anchored` is a pure role marker — use
  `@metadata.anchor_field` on the implementing class instead.
- **`Provenance.source`** no longer exists; `Provenance` carries only
  `agent`, `at`, `method`, `confidence`. Multi-source derivation lives in
  `Entity.derived_from: Set<Source>`.

### migrations/

Optional directory of `NNNN_description.py` files, each exporting
`async def up(tdb, branch)`. Migrations are **data** migrations (backfills,
copies, status rewrites), not schema shape changes.

## BuildContext.ensure_entity contract

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

## How third-party extensions get typed models

1. The extension's `manifest.json` declares `models_target`, e.g.
   `"models_target": "firnline_ext_myapp.models"`.
2. When `firnline-schema compose` discovers the extension via the
   `firnline.schema_modules` entry point, it records the
   `module_name → models_target` mapping.
3. `firnline-schema codegen` resolves each `models_target` to a filesystem
   path using `importlib` (locating the owning package), classifies classes
   by owning module, and emits one `models.py` per owning package.
4. At runtime, the extension's code imports from its own `models.py` like
   any other Python module — no central registry, no `firnline-core`
   dependency needed for the generated code. Kernel modules land in
   `firnline_core.generated/`; extension models land in the extension's
   own package tree.

See [../reference/cli.md](../reference/cli.md) for the `codegen` command flags.

## Startup behaviour (all host services)

All host services boot through the shared `PluginHost` in `firnline-core`:

1. **Discover** all plugins for the service's entry-point group.
2. **Validate** structural conformance against the protocol (when supplied).
3. **Fetch** the `SchemaModule` registry from TerminusDB (unless pre-fetched).
4. **check_requirements** against installed modules (semver ranges +
   `requires_classes` against registry `exports`).
5. **Collision check** — duplicate keys (e.g. capture kind, tool name, trigger
   type, indexed class) across active plugins are **fatal**.
6. **Select** — active plugins pass all checks; failures are skipped or
   fatal depending on `HostPolicy`.
7. **Log** the active set at INFO on every startup.

Each service configures its own `HostPolicy(broken_entry_point_fatal,
zero_active_fatal, strict, tdb_unavailable_fatal)`. The `{PREFIX}_STRICT_PLUGINS`
env var drives `strict` (makes requirement failures fatal).

## Docker installation

Extensions are installed into the shared `firnline_ext_venv` overlay volume
managed by `docker/entrypoint.sh`. Add extension specifiers to
`FIRNLINE_EXTENSIONS` in `.env`. See [Deployment](deployment.md) for the full
extension installation workflow, accepted specifier formats, and purge behaviour.

## Worked example: firnline-ext-address-book

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

### Entry points

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

## Related documents

- [../reference/entry-points.md](../reference/entry-points.md) — full protocol signatures for every entry-point group
- [../reference/cli.md](../reference/cli.md) — `firnline-schema` CLI flags including `codegen`
- [Deployment](deployment.md) — Docker extension installation workflow
- [Automations](automations.md) — building action executors (the `effectd.executors` group in action)
- [../concepts/architecture.md](../concepts/architecture.md) — plugin system architecture
