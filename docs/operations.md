# Operations

Production runbook for schema changes using the `firnline-schema` toolchain.
This assumes a running firnline deployment with an external TerminusDB.

> **Always back up first.** Schema changes on a live instance require a cold
> volume snapshot before any mutation.

## Backup

### Volume snapshot (recommended)

Stop the TerminusDB container, tar the storage volume, restart.

```bash
# 1. Stop
docker stop <terminusdb-container>

# 2. Verify stopped
docker ps -a --filter name=<terminusdb-container> --format '{{.Status}}'
# Expect: Exited (...)

# 3. Tar (read-only mount)
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_FILE="firnline-backup-${TIMESTAMP}.tar.gz"

docker run --rm \
  -v <terminusdb-volume>:/data:ro \
  -v "$(pwd):/out" \
  alpine:3.20 \
  tar czf "/out/${BACKUP_FILE}" -C /data .

# 4. Verify
tar tzf "$BACKUP_FILE" | head -20
# Should list admin/, _system/, _meta/, ...

# 5. Restart
docker start <terminusdb-container>

# 6. Smoke test
curl -f -u admin:$TDB_PASSWORD \
  "http://<tdb-host>:6363/api/info/admin/firnline"
```

Store the backup off-machine before proceeding.

### Restore

```bash
docker stop <terminusdb-container>

# Empty the volume (destructive — confirmed operator action)
docker run --rm -v <terminusdb-volume>:/data alpine:3.20 \
  sh -c 'rm -rf /data/* /data/.[!.]* /data/..?*'

# Restore
docker run --rm \
  -v <terminusdb-volume>:/data \
  -v "$(pwd):/in:ro" \
  alpine:3.20 \
  tar xzf "/in/${BACKUP_FILE}" -C /data

docker start <terminusdb-container>
```

## Schema Workflow

The `firnline-schema` CLI provides the full lifecycle. All commands that talk
to TerminusDB accept `--tdb-url`, `--tdb-org`, `--tdb-db`, `--tdb-user`, and
read the password from the `FIRNLINE_SCHEMA_TDB_PASSWORD` environment variable.

### 1. Compose

```bash
firnline-schema compose --modules-dir schema/modules --out-dir build
```

Assembles all modules (repo tree + installed extensions via entry points) into
`build/composed.schema.json` and `build/modules.lock.json`.

### 2. Diff

```bash
firnline-schema diff --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch main
```

Compares the composed schema against the live instance. Reports additive vs.
breaking changes. Exit code 0 = no changes, 1 = changes detected (guardrails
satisfied), 2+ = errors or guardrail violations.

### 3. Plan

```bash
firnline-schema plan --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch schema-bootstrap
```

Dry-run description of what `apply` will do: schema push needed, registry
updates, pending migrations.

### 4. Apply

```bash
firnline-schema apply --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch schema-bootstrap
```

Pushes the composed schema to the specified branch (auto-creates it from
`main` if it doesn't exist), runs pending migrations in order, upserts
`SchemaModule` and `SchemaMigration` registry documents. **Idempotent** —
re-running is safe.

Apply to a branch first, never directly to main.

### 5. Validate

```bash
firnline-schema validate --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch schema-bootstrap
```

Runs GraphQL smoke tests (one query per concrete class), verifies registry
matches the composed lock file. Exit code 0 if everything checks out.

### 6. Promote

Record main's current head before promoting:

```bash
curl -s -u admin:$TDB_PASSWORD \
  "http://<tdb-host>:6363/api/log/admin/firnline/local/branch/main?count=1" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['identifier'])"

# Save as PRE_PROMOTE_MAIN_HEAD
```

Promote the validated branch to main:

```bash
firnline-schema promote --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch schema-bootstrap
```

This fast-forwards main to the branch head (verifying that main is an
ancestor first) and re-validates the main schema post-reset.

## Rollback

### Full restore

Follow the restore procedure in the Backup section above. This returns the
entire instance to the pre-operation state.

### Branch-reset rollback

If promotion already happened, reset main to the pre-promote commit:

```bash
curl -s -u admin:$TDB_PASSWORD \
  -X POST "http://<tdb-host>:6363/api/reset/admin/firnline/local/branch/main" \
  -H "Content-Type: application/json" \
  -d '{"commit_descriptor": "admin/firnline/local/commit/PRE_PROMOTE_MAIN_HEAD"}'
```

Then delete the bootstrap branch:

```bash
curl -s -u admin:$TDB_PASSWORD \
  -X DELETE "http://<tdb-host>:6363/api/branch/admin/firnline/local/branch/schema-bootstrap"
```

If promotion has NOT happened yet (stuck at apply/validate), simply delete
the branch.

### Verify after rollback

```bash
# Confirm schema reverted:
curl -s -u admin:$TDB_PASSWORD \
  -X POST "http://<tdb-host>:6363/api/graphql/admin/firnline" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ Captured { _id } }"}'
# Should return documents unchanged.
```

## Post-change Verification

```bash
firnline-schema validate --modules-dir schema/modules \
  --tdb-url http://<tdb-host>:6363 --tdb-org admin --tdb-db firnline \
  --tdb-user admin --branch main
```

Then confirm all services are healthy:

```bash
curl http://localhost:8087/healthz   # queryd
curl http://localhost:8088/healthz   # captured
curl http://localhost:8089/healthz   # indexed
```

For polling workers (ingestd, triggerd, notifyd), verify liveness files
are fresh (< 5 minutes old):

```bash
docker compose exec ingestd find /tmp/ingestd-alive -mmin -5
docker compose exec triggerd find /tmp/triggerd-alive -mmin -5
docker compose exec notifyd find /tmp/notifyd-alive -mmin -5
```
