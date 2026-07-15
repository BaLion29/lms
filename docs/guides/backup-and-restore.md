# Backup and restore

## Purpose

How to back up and restore a firnline deployment's TerminusDB storage,
including volume snapshots, full restores, and branch-reset rollbacks.

## Prerequisites

- A running firnline deployment with the TerminusDB container accessible.
- Shell access on the Docker host.
- `docker compose ps` to find the actual TerminusDB container name.

> The commands below use `<terminusdb-container>` and `<terminusdb-volume>` as
> placeholders. Find the real values with:
>
> ```bash
> docker compose ps     # container name is in the NAME column
> docker volume ls      # volume name is typically <project>_terminusdb_data
> ```

## Volume snapshot (recommended)

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

## Full restore

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

A full restore returns the entire instance to the pre-operation state. All
service containers should recover automatically on restart (the bootstrap
container re-validates the schema; runtime services reconnect to TerminusDB).

## Branch-reset rollback

If a schema promotion already happened and you want to roll back without
restoring the volume, reset main to the pre-promote commit.

Record main's current head before promoting (capture this value first):

```bash
curl -s -u admin:$TDB_PASSWORD \
  "http://<tdb-host>:6363/api/log/admin/firnline/local/branch/main?count=1" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['identifier'])"

# Save as PRE_PROMOTE_MAIN_HEAD
```

Reset main to that commit:

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

If promotion has **not** happened yet (stuck at apply/validate), simply delete
the branch — no reset needed.

## Verify after rollback

```bash
# Confirm schema reverted:
curl -s -u admin:$TDB_PASSWORD \
  -X POST "http://<tdb-host>:6363/api/graphql/admin/firnline" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ Captured { _id } }"}'
# Should return documents unchanged.
```

## Related documents

- [Schema changes](schema-changes.md) — schema change workflow (backup before applying)
- [Deployment](deployment.md) — production deployment overview
- [../concepts/architecture.md](../concepts/architecture.md) — architecture and data flow
