# CLI Reference

Canonical command-line interface reference for all firnline services and the
schema toolchain.

## `firnline-schema`

Schema module composition and lifecycle management. Installed with the
`firnline-schema` package.

### `firnline-schema compose`

Compose modules into a single schema, lock file, and meta file.

| Arg | Default | Description |
|---|---|---|
| `--modules-dir` | `schema/modules` | Directory containing module sub-directories |
| `--out-dir` | `build` | Output directory for composed schema, lock, and meta |
| `--no-entry-points` | `false` | Skip discovery of `firnline.schema_modules` entry points |

**Outputs:**
- `composed.schema.json` — the full composed schema array
- `modules.lock.json` — `{"modules": {"<name>": {"version", "checksum", "source?"}}}`
- `composed.meta.json` — `{"classes": {...}, "targets": {...}, "imports": {...}}`

**Example:**
```bash
firnline-schema compose --modules-dir schema/modules --out-dir build
```

### `firnline-schema diff`

Compute diff between current modules and a baseline (fragment or live TDB).
Classifies changes as additive or breaking and checks guardrails.

| Arg | Default | Description |
|---|---|---|
| `--modules-dir` | `schema/modules` | Directory containing module sub-directories |
| `--baseline-modules` | — | Path to baseline modules directory (e.g. git worktree) |
| `--baseline-lock` | — | Path to baseline `modules.lock.json` |
| `--tdb-url` | — | TerminusDB URL for live-instance diff |
| `--tdb-org` | — | TerminusDB organisation |
| `--tdb-db` | — | TerminusDB database |
| `--tdb-user` | — | TerminusDB username |
| `--tdb-password` | — | TerminusDB password (env: `FIRNLINE_SCHEMA_TDB_PASSWORD`) |
| `--branch` | `main` | TDB branch to diff against |
| `--no-entry-points` | `false` | Skip entry-point module discovery |
| `--allow-extra-live-classes` | `false` | Downgrade live-only classes from breaking to warnings |

**Requires at least one** of `--baseline-lock`, `--baseline-modules`, or
`--tdb-url`.

**Example:**
```bash
firnline-schema diff --modules-dir schema/modules \
  --baseline-lock build/modules.lock.json \
  --baseline-modules /tmp/old-schema/modules
```

### `firnline-schema plan`

Show pending actions on a branch without applying them (dry-run).

| Arg | Default | Description |
|---|---|---|
| `--modules-dir` | `schema/modules` | Directory containing module sub-directories |
| `--tdb-url` | — (required) | TerminusDB URL |
| `--tdb-org` | — (required) | TerminusDB organisation |
| `--tdb-db` | — (required) | TerminusDB database |
| `--tdb-user` | — (required) | TerminusDB username |
| `--tdb-password` | — (required) | TerminusDB password |
| `--branch` | `main` | TDB branch |

**Example:**
```bash
firnline-schema plan --tdb-url http://localhost:6363 \
  --tdb-org admin --tdb-db firnline --tdb-user admin \
  --tdb-password secret --branch staging
```

### `firnline-schema apply`

Apply composed schema, run migrations, and upsert the registry on a branch.
Creates the branch from main if it does not exist. Idempotent.

| Arg | Default | Description |
|---|---|---|
| `--modules-dir` | `schema/modules` | Directory containing module sub-directories |
| `--tdb-url` | — (required) | TerminusDB URL |
| `--tdb-org` | — (required) | TerminusDB organisation |
| `--tdb-db` | — (required) | TerminusDB database |
| `--tdb-user` | — (required) | TerminusDB username |
| `--tdb-password` | — (required) | TerminusDB password |
| `--branch` | `main` | TDB branch |

**Example:**
```bash
firnline-schema apply --modules-dir schema/modules \
  --tdb-url http://localhost:6363 --tdb-org admin \
  --tdb-db firnline --tdb-user admin --tdb-password secret \
  --branch staging
```

### `firnline-schema validate`

Validate schema and registry consistency on a branch (GraphQL smoke tests,
registry ↔ lock check).

| Arg | Default | Description |
|---|---|---|
| `--modules-dir` | `schema/modules` | Directory containing module sub-directories |
| `--tdb-url` | — (required) | TerminusDB URL |
| `--tdb-org` | — (required) | TerminusDB organisation |
| `--tdb-db` | — (required) | TerminusDB database |
| `--tdb-user` | — (required) | TerminusDB username |
| `--tdb-password` | — (required) | TerminusDB password |
| `--branch` | `main` | TDB branch |

**Example:**
```bash
firnline-schema validate --modules-dir schema/modules \
  --tdb-url http://localhost:6363 --tdb-org admin \
  --tdb-db firnline --tdb-user admin --tdb-password secret \
  --branch staging
```

### `firnline-schema promote`

Fast-forward main to a branch tip.

| Arg | Default | Description |
|---|---|---|
| `--modules-dir` | `schema/modules` | Directory containing module sub-directories |
| `--tdb-url` | — (required) | TerminusDB URL |
| `--tdb-org` | — (required) | TerminusDB organisation |
| `--tdb-db` | — (required) | TerminusDB database |
| `--tdb-user` | — (required) | TerminusDB username |
| `--tdb-password` | — (required) | TerminusDB password |
| `--branch` | `main` | TDB branch to promote to main |
| `--force` | `false` | Promote even if main has diverged |

**Example:**
```bash
firnline-schema promote --modules-dir schema/modules \
  --tdb-url http://localhost:6363 --tdb-org admin \
  --tdb-db firnline --tdb-user admin --tdb-password secret \
  --branch staging
```

### `firnline-schema codegen`

Regenerate Pydantic models from composed schema per owning package via
`models_target`.

| Arg | Default | Description |
|---|---|---|
| `--composed` | `build/composed.schema.json` | Path to composed schema |
| `--meta` | `build/composed.meta.json` | Path to composed meta mapping |
| `--only` | — (all) | Only generate code for listed module names |

**Example:**
```bash
firnline-schema codegen --composed build/composed.schema.json \
  --meta build/composed.meta.json
```

## Service entry-points

### `captured`

FastAPI capture-ingress daemon. No CLI arguments — all configuration via
environment variables (prefix `CAPTURED_`).

```bash
captured
```

Binds to `CAPTURED_LISTEN_ADDR` (default `0.0.0.0:8088`).

### `queryd`

FastAPI GraphQL read proxy + write-tool endpoints. No CLI arguments — all
configuration via environment variables (prefix `QUERYD_`).

```bash
queryd
```

Binds to `QUERYD_LISTEN_ADDR` (default `0.0.0.0:8087`).

### `ingestd`

LLM-powered polling worker for inbox extraction.

```bash
ingestd [--once] [--dry-run]
```

| Flag | Description |
|---|---|
| `--once` | Run a single extraction cycle and exit |
| `--dry-run` | Extract but do not write anything to database |

Configuration via environment variables (prefix `INGESTD_`).

### `triggerd`

Polling worker that evaluates Trigger documents and materializes
`TriggerFiring` records.

```bash
triggerd [--once] [--dry-run]
```

| Flag | Description |
|---|---|
| `--once` | Run a single evaluation cycle and exit |
| `--dry-run` | Evaluate but do not write anything to database |

Configuration via environment variables (prefix `TRIGGERD_`).

### `indexed`

FastAPI precision grounding service with background poller.

```bash
indexed
```

No CLI arguments. Binds to `INDEXED_LISTEN_ADDR` (default `0.0.0.0:8089`).
Configuration via environment variables (prefix `INDEXED_`).

### `effectd`

Effect delivery daemon — polls `TriggerFiring` documents and executes via
channel/executor plugins.

```bash
effectd [--once]
```

| Flag | Description |
|---|---|
| `--once` | Run a single delivery cycle and exit |

Configuration via environment variables (prefix `EFFECTD_`).

### `mcpd`

MCP server exposing firnline to external AI agents via streamable HTTP.

```bash
mcpd
```

No CLI arguments. Binds to `MCPD_HOST`:`MCPD_PORT` (default `0.0.0.0:8090`).
Configuration via environment variables (prefix `MCPD_`).

## Related documents

- [Configuration reference](configuration.md)
- [Getting started: Installation](../getting-started/installation.md)
- [Local development](../development/local-development.md)
