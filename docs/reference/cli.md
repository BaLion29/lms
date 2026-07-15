# CLI reference — firnline-schema

## Purpose

This page is the exhaustive reference for the `firnline-schema` command-line
tool. It covers every subcommand, flag, and default. For a step-by-step
walkthrough of a schema change, see [guides/schema-changes.md](../guides/schema-changes.md).

## Synopsis

```
firnline-schema <command> [options]
```

The CLI manages the lifecycle of schema modules — composition, diffing against
baselines or live TerminusDB instances, applying changes to branches, and
promoting to main.

## Commands

### compose

```
firnline-schema compose [--modules-dir DIR] [--out-dir DIR] [--no-entry-points]
```

Composes all schema modules into a single JSON schema plus a lock file and meta
file.

| Flag | Default | Description |
|---|---|---|
| `--modules-dir` | `schema/modules` | Directory containing module sub-directories |
| `--out-dir` | `build` | Output directory for `composed.schema.json`, `modules.lock.json`, `composed.meta.json` |
| `--no-entry-points` | `false` | Skip discovery of `firnline.schema_modules` entry points |

Output files:

- `composed.schema.json` — single JSON array with `@context` + all class/enum definitions
- `modules.lock.json` — per-module `version`, `checksum`, and `source` (origin)
- `composed.meta.json` — class→module mapping (`classes`), module→target (`targets`), module→import (`imports`)

Entry-point module discovery is automatic. Each `firnline.schema_modules` entry
point must resolve to a directory containing `manifest.json` + `schema.json`.
The entry point name must equal the manifest `name`. A broken entry point is a
hard error — extensions are never silently ignored.

### codegen

```
firnline-schema codegen [--composed PATH] [--meta PATH] [--only MODULE...]
```

Generates Pydantic models from the composed schema.

| Flag | Default | Description |
|---|---|---|
| `--composed` | `build/composed.schema.json` | Path to composed schema |
| `--meta` | `build/composed.meta.json` | Path to composed meta mapping |
| `--only` | (all) | Only generate code for listed module names |

Resolves each module's `models_target` (from `manifest.json`) to a filesystem
path via `importlib`, classifies classes by owning module, and writes one
`models.py` per owning package. Kernel models land in
`firnline_core.generated/`; extension models land in the extension's own
package tree.

### diff

```
firnline-schema diff --modules-dir DIR
    [--baseline-modules DIR] [--baseline-lock PATH]
    [--tdb-url URL --tdb-org ORG --tdb-db DB --tdb-user USER --tdb-password PW] [--branch BRANCH]
    [--no-entry-points] [--allow-extra-live-classes]
```

Computes schema differences against a baseline and checks guardrails (semver,
migration files, export changes).

| Flag | Default | Description |
|---|---|---|
| `--modules-dir` | `schema/modules` | Current modules directory |
| `--baseline-modules` | — | Path to baseline modules directory (e.g. git worktree) |
| `--baseline-lock` | — | Path to baseline `modules.lock.json` |
| `--tdb-url` | — | TerminusDB base URL (all-or-nothing: requires all five TDB args) |
| `--tdb-org` | — | TerminusDB organisation |
| `--tdb-db` | — | TerminusDB database name |
| `--tdb-user` | — | TerminusDB username |
| `--tdb-password` | — | TerminusDB password (falls back to `FIRNLINE_SCHEMA_TDB_PASSWORD` env var) |
| `--branch` | `main` | TDB branch to diff against |
| `--no-entry-points` | `false` | Skip entry-point module discovery |
| `--allow-extra-live-classes` | `false` | Downgrade live-only classes from breaking to warnings |

At least one of `--baseline-lock`, `--baseline-modules`, or `--tdb-url` must
be provided. Fragment-based diff and live-instance diff run independently.
Changes are classified as additive (`+`) or breaking (`!`) per module.

Guardrail violations (missing migration file for a MAJOR bump, version not
bumped despite breaking changes, etc.) cause a non-zero exit code.

### plan

```
firnline-schema plan --modules-dir DIR
    --tdb-url URL --tdb-org ORG --tdb-db DB --tdb-user USER --tdb-password PW
    [--branch BRANCH]
```

Dry-run description of pending schema actions (schema push, migration runs,
registry updates) on a TDB branch. Exit code 1 means there are pending actions;
exit code 2 means errors.

### apply

```
firnline-schema apply --modules-dir DIR
    --tdb-url URL --tdb-org ORG --tdb-db DB --tdb-user USER --tdb-password PW
    [--branch BRANCH]
```

Pushes the composed schema, runs data migrations, and upserts registry entries
on a TDB branch. Creates the branch from `main` if it does not exist.
Idempotent — running apply twice against the same modules produces the same
result.

### validate

```
firnline-schema validate --modules-dir DIR
    --tdb-url URL --tdb-org ORG --tdb-db DB --tdb-user USER --tdb-password PW
    [--branch BRANCH]
```

Validates that the composed schema and registry on a TDB branch are consistent.
Runs GraphQL smoke tests (one query per non-abstract class) and verifies that
the registry exports match the lock file.

### promote

```
firnline-schema promote --modules-dir DIR
    --tdb-url URL --tdb-org ORG --tdb-db DB --tdb-user USER --tdb-password PW
    [--branch BRANCH] [--force]
```

Fast-forwards `main` to the branch head. Verifies that `main` head is an
ancestor of the branch (refusing the promote if `main` has diverged).

| Flag | Default | Description |
|---|---|---|
| `--force` | `false` | Promote even if `main` has diverged |

## Typical workflow

```
compose  →  diff  →  plan  →  apply  →  validate  →  promote
```

Then `codegen` to regenerate Pydantic models. See
[guides/schema-changes.md](../guides/schema-changes.md) for the full walkthrough.

## Entry-point module discovery

Installed packages register schema modules via the `firnline.schema_modules`
entry-point group. The entry point value must be:

- A `str` or `os.PathLike` attribute holding the module directory path, or
- A package/module object — `importlib.resources.files(obj)` locates the directory.

Example `pyproject.toml`:

```toml
[project.entry-points."firnline.schema_modules"]
time_management = "firnline_ext_time_management:SCHEMA_MODULE_DIR"
```

Discovery runs during `compose`, `diff`, `plan`, `apply`, `validate`, and
`promote`. Opt out with `--no-entry-points`. A misconfigured entry point is
a hard error.

## Related documents

- [Schema changes guide](../guides/schema-changes.md) — step-by-step schema change workflow
- [Entry-point reference](entry-points.md) — all plugin entry-point groups
- [Configuration reference](configuration.md) — TDB connection variables
- [TerminusDB notes](terminusdb-notes.md) — empirically verified TDB API behaviour
