# Schema Modules

Schema modules are the composable building blocks of firnline's data model.
Each module contributes class and enum definitions; the `firnline-schema`
CLI composes them into a single `Schema` graph in TerminusDB.

## Directory structure

```
<module_name>/
├── manifest.json          # metadata, dependencies, exports, codegen routing
├── schema.json            # JSON array of TerminusDB class/enum definitions
└── migrations/            # optional — NNNN_description.py data migration scripts
```

## `manifest.json` format

```json
{
  "name": "time_management",
  "version": "0.2.0",
  "depends_on": [
    {"name": "places", "range": ">=0.1.0 <0.2.0"},
    {"name": "reminders", "range": ">=0.1.0 <0.2.0"},
    {"name": "triggers", "range": ">=0.1.0 <0.2.0"}
  ],
  "models_target": "firnline_ext_time_management.models",
  "models_import": "firnline_ext_time_management.models",
  "exports": ["Task", "TaskSpec", "Event", "TaskStatus"],
  "description": "Tasks, events, routines, activities and their specs"
}
```

| Field | Required | Description |
|---|---|---|
| `name` | yes | Module name. Must match the entry-point name. |
| `version` | yes | Semver version string (e.g. `0.1.0`). |
| `depends_on` | yes | Array of `{"name": str, "range": str}` objects with semver ranges. |
| `models_target` | yes | Dotted Python module path for codegen output. Kernel modules use `firnline_core.generated.<name>`; extensions use `firnline_ext_<name>.models`. |
| `models_import` | no | Dotted Python module path for runtime imports. Defaults to `models_target` if omitted. |
| `exports` | yes | Array of class/enum `@id` values this module makes available to others. |
| `description` | yes | Human-readable description. |

### `models_target` routing

Kernel modules (`schema/modules/`) write codegen output to
`firnline_core.generated/<name>`. Extension modules write to their own
package tree (e.g. `firnline_ext_time_management.models`).

Codegen uses `importlib` to resolve each `models_target` to a filesystem
path, classifies classes by owning module, and emits one `models.py` per
owning package. Extension models have zero dependency on `firnline-core`.

## `schema.json` format

A JSON array of TerminusDB class/enum definitions in standard WOQL schema
format. The `@context` object is owned exclusively by the `core` module;
domain modules must not include it.

Every class/enum listed in `exports` **must** carry an `@documentation` key
with a non-empty `@comment` string — "the schema is a prompt". The
`firnline-schema compose` step enforces this (L3 lint violation raises
`ComposeL3Error`). `queryd` derives its agent briefing from these
`@documentation` comments.

## `@metadata` keys

Placed on class definitions in `schema.json`. Validated by the composer at
specific layers.

| Key | Required on | Description | Validated at |
|---|---|---|---|
| `label_field` | Every exported concrete (non-abstract) `Entity` subclass | Names one of the class's own fields whose value is used as the display label | L4 |
| `anchor_field` | Every concrete class implementing the `Anchored` role marker | Names an `xsd:dateTime` field holding the canonical temporal instant | L5 |

**L4 example:**
```json
{
  "@id": "Task",
  "@type": "Class",
  "@metadata": {"label_field": "name"},
  ...
}
```

**L5 example:**
```json
{
  "@id": "Event",
  "@type": "Class",
  "@parent": ["Anchored"],
  "@metadata": {"anchor_field": "start"},
  ...
}
```

If `anchor_field` is unset on a document, relative triggers referencing it
are dormant.

## Semver policy

- **MINOR** bump — additive only: new classes, new Optional fields, new enum
  values, widened exports.
- **MAJOR** bump — anything else (new required field, type change, removal,
  narrowing exports) — must ship with at least one migration file in
  `migrations/`.

The `firnline-schema diff` command classifies all changes and checks
version-bump guardrails.

## Composer lint layers

During `firnline-schema compose`, the following validations run:

| Layer | Check | Severity |
|---|---|---|
| L1 | `@context` must live exclusively in `core` module | Hard error |
| L1 | `exports` must reference `@id` values defined in the module's `schema.json` | Hard error |
| L1 | Module names must be unique across all discovered modules | Hard error |
| L3 | Every class/enum in `exports` must carry `@documentation` with non-empty `@comment` | `ComposeL3Error` |
| L4 | Every exported concrete `Entity` subclass must declare `@metadata.label_field` | `ComposeL4Error` |
| L5 | Classes implementing `Anchored` must declare `@metadata.anchor_field` naming an `xsd:dateTime` field | `ComposeL5Error` |

L3–L5 violations are composition failures that prevent the composed output
from being written. The `--allow-extra-live-classes` flag on `diff`
downgrades live-only classes to warnings.

## Migrations

`migrations/` contains ordered `NNNN_description.py` files, each exporting:

```python
async def up(tdb, branch):
    """Apply data migration."""
    ...
```

Migrations are **data** migrations (backfills, copies, status rewrites), not
schema shape changes. Shape changes come from `schema.json` diffs applied
by `firnline-schema apply`.

Migration files are run in numeric order by `apply`. Each migration is
recorded in the `SchemaMigration` registry to ensure it runs exactly once.

## Lock file format

`modules.lock.json` is the output of `firnline-schema compose`:

```json
{
  "modules": {
    "core": {
      "version": "0.1.0",
      "checksum": "abc123...",
      "source": "repo:core"
    },
    "time_management": {
      "version": "0.2.0",
      "checksum": "def456...",
      "source": "pkg:firnline-ext-time-management==0.2.0"
    }
  }
}
```

| Field | Description |
|---|---|
| `version` | Semver version from `manifest.json` |
| `checksum` | `sha256(json.dumps(fragment_array, sort_keys=True, separators=(",", ":")))` — canonical form |
| `source` | Optional origin: `repo:<name>` for repo-tree modules, `pkg:<package>==<version>` for entry-point modules |

The `source` field is omitted for modules discovered from `schema/modules/`
in older lock files (backward-compatible).

## Discovery

Modules are discovered from two sources:

1. **Repo tree** — subdirectories of `schema/modules/` containing `manifest.json`.
2. **Entry points** — installed packages registered under
   `firnline.schema_modules`. Each entry point must resolve to a directory
   with `manifest.json` + `schema.json`. The entry-point name must match
   `manifest.json` `name`.

Discovery runs during `firnline-schema compose`. Use `--no-entry-points` to
skip entry-point modules.

## Related documents

- [Entry points reference](entry-points.md)
- [CLI reference](cli.md)
- [Plugin system](../concepts/plugin-system.md)
- [Extension development](../development/extension-development.md)
