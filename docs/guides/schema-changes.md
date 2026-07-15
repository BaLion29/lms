# Schema changes

## Purpose

How to plan, apply, validate, and promote schema changes in a running firnline
deployment using the `firnline-schema` toolchain. This guide covers the
full lifecycle from module composition to production promotion.

## Prerequisites

- A running firnline deployment with TerminusDB accessible.
- The `firnline-schema` CLI installed (comes with the `firnline-schema`
  package; available in the bootstrap container).
- The TerminusDB password exported as `FIRNLINE_SCHEMA_TDB_PASSWORD`.

> **Always back up first.** Schema changes on a live instance require a cold
> volume snapshot before any mutation. See [Backup and restore](backup-and-restore.md).

## The workflow

The `firnline-schema` CLI provides the full lifecycle. All commands that talk
to TerminusDB accept `--tdb-url`, `--tdb-org`, `--tdb-db`, `--tdb-user`, and
read the password from the `FIRNLINE_SCHEMA_TDB_PASSWORD` environment variable.
See [../reference/cli.md](../reference/cli.md) for the complete flag reference.
For the schema module system architecture, see
[../concepts/architecture.md](../concepts/architecture.md).

### 1. Compose

Assemble all modules (repo tree + installed extensions via entry points) into
a single schema and lock file:

```bash
firnline-schema compose --modules-dir schema/modules --out-dir build
```

Output: `build/composed.schema.json` and `build/modules.lock.json`.

### 2. Diff

Compare the composed schema against the live instance. Reports additive vs.
breaking changes and enforces guardrails:

```bash
firnline-schema diff --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch main
```

Exit codes: `0` = no changes, `1` = changes detected (guardrails satisfied),
`2+` = errors or guardrail violations.

### 3. Plan

Dry-run description of what `apply` will do — schema push needed, registry
updates, pending migrations:

```bash
firnline-schema plan --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch schema-bootstrap
```

### 4. Apply

Push the composed schema to the specified branch (auto-creates it from `main`
if it doesn't exist), run pending migrations in order, and upsert
`SchemaModule` and `SchemaMigration` registry documents:

```bash
firnline-schema apply --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch schema-bootstrap
```

Apply to a branch first, **never** directly to main. This command is
**idempotent** — re-running is safe.

### 5. Validate

Run GraphQL smoke tests (one query per concrete class) and verify the registry
matches the composed lock file:

```bash
firnline-schema validate --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch schema-bootstrap
```

Exit code `0` if everything checks out.

### 6. Promote

Record main's current head before promoting:

```bash
curl -s -u admin:$TDB_PASSWORD \
  "http://<tdb-host>:6363/api/log/admin/firnline/local/branch/main?count=1" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['identifier'])"

# Save the output as PRE_PROMOTE_MAIN_HEAD
```

Promote the validated branch to main:

```bash
firnline-schema promote --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch schema-bootstrap
```

This fast-forwards main to the branch head (verifying that main is an ancestor
first) and re-validates the main schema post-reset.

## Post-change verification

Run the validate command against main:

```bash
firnline-schema validate --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch main
```

Confirm all services are healthy:

```bash
curl http://localhost:8080/healthz   # apid (captured + queryd + indexed + mcpd)
```

For polling workers, verify liveness files are fresh (< 5 minutes old):

```bash
docker compose exec ingestd find /tmp/ingestd-alive -mmin -5
docker compose exec triggerd find /tmp/triggerd-alive -mmin -5
docker compose exec effectd find /tmp/effectd-alive -mmin -5
```

## Related documents

- [../reference/cli.md](../reference/cli.md) — full `firnline-schema` flag reference
- [../concepts/architecture.md](../concepts/architecture.md) — schema module system concept
- [Backup and restore](backup-and-restore.md) — backup procedure before schema changes
- [Deployment](deployment.md) — production deployment and upgrades
