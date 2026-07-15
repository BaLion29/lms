# Backup and Restore

Procedures for backing up and restoring the TerminusDB volume, including rollback after a schema change.

## Prerequisites

- Docker access to the host running the TerminusDB container.
- The TerminusDB volume name — `terminusdb_data` when using the bundled-TDB overlay, or your own named volume for external deployments.

## Volume Snapshot (Recommended)

Stop the TerminusDB container, create a compressed tar of the storage volume, restart, and verify.

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

# 4. Verify contents
tar tzf "$BACKUP_FILE" | head -20
# Should list admin/, _system/, _meta/, ...

# 5. Restart
docker start <terminusdb-container>

# 6. Smoke test
curl -f -u admin:$TDB_PASSWORD \
  "http://<tdb-host>:6363/api/info/admin/firnline"
```

Store the backup file off-machine before proceeding with any schema mutation.

## Restore

Restore from a previously created backup archive:

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

## Rollback

Two rollback strategies depending on how far the schema change progressed.

### Full Restore

Follow the [Restore](#restore) procedure above using a pre-operation snapshot. This returns the entire instance — schema and data — to the pre-change state.

### Branch-Reset Rollback

Use when a schema change was applied to a branch and promoted to `main`, and you need to undo the promotion without a full volume restore.

**If promotion already happened**, reset main to the pre-promote commit.

Record main's current head **before** promoting:

```bash
curl -s -u admin:$TDB_PASSWORD \
  "http://<tdb-host>:6363/api/log/admin/firnline/local/branch/main?count=1" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['identifier'])"

# Save as PRE_PROMOTE_MAIN_HEAD
```

Reset main to the saved commit:

```bash
curl -s -u admin:$TDB_PASSWORD \
  -X POST "http://<tdb-host>:6363/api/reset/admin/firnline/local/branch/main" \
  -H "Content-Type: application/json" \
  -d '{"commit_descriptor": "admin/firnline/local/commit/PRE_PROMOTE_MAIN_HEAD"}'
```

Delete the bootstrap branch:

```bash
curl -s -u admin:$TDB_PASSWORD \
  -X DELETE "http://<tdb-host>:6363/api/branch/admin/firnline/local/branch/schema-bootstrap"
```

**If promotion has NOT happened yet** (stuck at apply/validate), simply delete the branch:

```bash
curl -s -u admin:$TDB_PASSWORD \
  -X DELETE "http://<tdb-host>:6363/api/branch/admin/firnline/local/branch/schema-bootstrap"
```

### Verify After Rollback

```bash
# Confirm schema reverted:
curl -s -u admin:$TDB_PASSWORD \
  -X POST "http://<tdb-host>:6363/api/graphql/admin/firnline" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ Captured { _id } }"}'
# Should return documents unchanged.
```

## Related Documents

- [deployment.md](deployment.md) — service topology and volumes reference
- [schema-changes.md](schema-changes.md) — the compose → diff → apply → promote workflow
