# lms-schema

Schema module composition, validation, difference computation, and migration
management for the LMS (Life Management System).

## Usage

```bash
# Compose modules into a single schema + lock file
lms-schema compose --modules-dir schema/modules --out-dir build

# Compose without installed extension modules
lms-schema compose --modules-dir schema/modules --out-dir build --no-entry-points

# Diff modules against a baseline (checks guardrails)
lms-schema diff --modules-dir schema/modules \
  --baseline-modules /path/to/old/modules \
  --baseline-lock  build/modules.lock.json

# Diff composed schema against a live TerminusDB instance
lms-schema diff --modules-dir schema/modules \
  --tdb-url https://example.com --tdb-org org --tdb-db db \
  --tdb-user admin --tdb-password secret
```

## Entry-point module discovery

Installed packages can register schema modules via the `lms.schema_modules`
entry-point group.  Each entry point must resolve to a directory containing
`manifest.json` + `schema.json` (and optionally `migrations/`).  The entry
point **name** must equal the module's manifest `name`.

The entry-point value may be either:

- A `str` or `os.PathLike` attribute holding the module directory path, or
- A package/module object — `importlib.resources.files(obj)` is used to
  locate the directory.

Example `pyproject.toml`:

```toml
[project.entry-points."lms.schema_modules"]
planning = "lms_ext_planning:SCHEMA_MODULE_DIR"
```

Discovery runs automatically during `lms-schema compose` (opt-out with
`--no-entry-points`).  A broken or misconfigured entry point produces a
hard error listing all failures — extensions are never silently ignored.

## Rules

- **Abstract classes** may be defined by any module.  Core owns the
  contentless universal markers (`Source`, `Context`, `Remindable`), the
  registry classes, and `ExternalRef` (L1).
- **`@context`** must live exclusively in `core/context.json` — never in any
  module's `schema.json` (L1).
- **Exports** must reference `@id`s that are actually defined in the module's
  `schema.json`.  Exports are validated during composition; a bogus export
  causes a hard error naming the module and the invalid `@id`.
- **Enums** are module-private by default.  A module **may** export enums if
  external modules need to reference them — add the enum's `@id` to the
  manifest's `exports` list.
- **Dependency ranges** must be satisfied by the resolved module versions.
- **Checksums** are computed via the canonical form:

      sha256(json.dumps(fragment_array, sort_keys=True, separators=(",", ":")))

## Lock file format

`build/modules.lock.json` records each module with its origin:

```json
{
  "modules": {
    "core": {
      "version": "1.1.0",
      "checksum": "abc123...",
      "source": "repo:core"
    },
    "planning": {
      "version": "0.1.0a1",
      "checksum": "def456...",
      "source": "pkg:lms-ext-planning==0.1.0a1"
    }
  }
}
```

The `source` field was added for entry-point modules.  Old lock files
without `source` are still accepted (backward-compatible).
