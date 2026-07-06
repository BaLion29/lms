# lms-schema

Schema module composition, validation, difference computation, and migration
management for the LMS (Life Management System).

## Usage

```bash
# Compose modules into a single schema + lock file
lms-schema compose --modules-dir schema/modules --out-dir build

# Diff modules against a baseline (checks guardrails)
lms-schema diff --modules-dir schema/modules \
  --baseline-modules /path/to/old/modules \
  --baseline-lock  build/modules.lock.json

# Diff composed schema against a live TerminusDB instance
lms-schema diff --modules-dir schema/modules \
  --tdb-url https://example.com --tdb-org org --tdb-db db \
  --tdb-user admin --tdb-password secret
```

## Rules

- **Abstract classes** may only be defined by the `core` module (L1).
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
