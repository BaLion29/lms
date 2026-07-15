# Schema Changes

The production workflow for schema changes using the `firnline-schema` CLI.

## Prerequisites

- A running firnline deployment with TerminusDB accessible.
- The `firnline-schema` image (built as part of the stack).
- `FIRNLINE_SCHEMA_TDB_PASSWORD` environment variable set (the CLI reads the TDB password from this variable).
- **Back up first** — create a volume snapshot before any schema mutation (see [backup-and-restore.md](backup-and-restore.md)).

## Workflow Overview

```
compose → diff → plan → apply → validate → promote
```

All commands that talk to TerminusDB accept `--tdb-url`, `--tdb-org`, `--tdb-db`, `--tdb-user`, and read the password from `FIRNLINE_SCHEMA_TDB_PASSWORD`. The default branch for read operations is `main`.

### 1. Compose

Assemble all schema modules (repo tree under `schema/modules` + installed extensions via entry points) into build artifacts:

```bash
firnline-schema compose --modules-dir schema/modules --out-dir build
```

Produces `build/composed.schema.json` and `build/modules.lock.json`.

### 2. Diff

Compare the composed schema against the live instance on `main`:

```bash
firnline-schema diff --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch main
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | No changes detected |
| 1 | Changes detected (guardrails satisfied) |
| 2+ | Error or guardrail violation |

Reports classify changes as additive vs. breaking.

### 3. Plan

Dry-run description of what `apply` will do:

```bash
firnline-schema plan --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch schema-bootstrap
```

Describes: schema push needed, registry updates, pending migrations — without making any changes.

### 4. Apply

Push the composed schema to a **branch** (never directly to `main`):

```bash
firnline-schema apply --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch schema-bootstrap
```

What it does:

- Auto-creates the branch from `main` if it doesn't exist.
- Pushes the composed schema to the branch.
- Runs pending data migrations in order.
- Upserts `SchemaModule` and `SchemaMigration` registry documents.

**Idempotent** — re-running is safe.

TerminusDB validates the full database against the new schema at push time. If **any** existing instance document violates the new schema, the push fails immediately with `400 api:SchemaCheckFailure`. No partial schema is committed — you get a clean go/no-go signal.

### 5. Validate

Run verification on the branch:

```bash
firnline-schema validate --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch schema-bootstrap
```

Runs GraphQL smoke tests (one query per concrete class) and verifies the `SchemaModule` registry matches the composed lock file. Exit code 0 = everything checks out.

### 6. Promote

Record main's current head **before** promoting:

```bash
curl -s -u admin:$TDB_PASSWORD \
  "http://<tdb-host>:6363/api/log/admin/firnline/local/branch/main?count=1" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['identifier'])"

# Save as PRE_PROMOTE_MAIN_HEAD
```

Promote the validated branch to `main`:

```bash
firnline-schema promote --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch schema-bootstrap
```

This fast-forwards `main` to the branch head (verifying that `main` is an ancestor first) and re-validates the schema on `main` post-reset.

## Post-Change Verification

After promotion, verify the live schema and service health:

```bash
# Validate schema on main
firnline-schema validate --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch main
```

Confirm HTTP services respond:

```bash
curl http://localhost:8087/healthz   # queryd
curl http://localhost:8088/healthz   # captured
curl http://localhost:8089/healthz   # indexed
```

Confirm polling worker liveness files are fresh (< 5 minutes):

```bash
docker compose exec ingestd find /tmp/ingestd-alive -mmin -5
docker compose exec triggerd find /tmp/triggerd-alive -mmin -5
docker compose exec effectd find /tmp/effectd-alive -mmin -5
```

## Common Pitfalls

- **Pushing directly to `main`.** Always apply to a branch first (`--branch schema-bootstrap`), validate, then promote. Branch-based apply isolates schema mutations and gives a clean rollback path.
- **Skipping the diff step.** Run `diff` before `apply` to classify changes and catch guardrail violations early.
- **Forgetting the pre-promote head.** Record main's commit identifier before `promote` so you can reset main via the branch-reset rollback if needed.

## Related Documents

- [backup-and-restore.md](backup-and-restore.md) — snapshot and rollback procedures
- [../reference/cli.md](../reference/cli.md) — full `firnline-schema` CLI reference
- [../reference/schema-modules.md](../reference/schema-modules.md) — schema module format and versioning
