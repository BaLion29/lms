# Production Bootstrap Runbook

First production touch of the modularized schema toolchain.  This procedure adds
only the two registry classes (`SchemaModule`, `SchemaMigration`) and registry
documents recording every module at its current version.  **Instance data is never
touched.**

> **Risk level**: low (additive-only schema change on a dedicated branch, with
> promotion only after validation).  A full backup + verified restore path is
> mandatory before starting.

---

## 0. Preconditions

- [ ] All tests green: `uv run pytest`
- [ ] Full dev-instance run-through completed (compose → diff → plan → apply → validate → promote → codegen on a local/dev TerminusDB).
- [ ] Operator has read and acknowledged this runbook.
- [ ] `LMS_SCHEMA_TDB_PASSWORD` env var is set in the shell where commands are run.

---

## 1. Backup

### 1.1 Baseline: storage volume snapshot

The safe, reliable baseline is a **cold** tar of the TerminusDB storage directory.
This captures every database, schema graph, commit graph, and user config
atomically — no API surface can do better.

**Production context:**
- Container name: `<terminusdb-container>` (the container running the v12.0.6 image, bound to `http://10.0.10.20:6364`)
- Storage directory inside container: `/app/terminusdb/storage`
- Docker volume name: `<terminusdb-volume>` (the volume mounted at `/app/terminusdb/storage`)

**Step 1 — Stop the container:**
```bash
docker stop <terminusdb-container>
```
Wait for SIGTERM grace period (TerminusDB flushes WAL on shutdown).  Verify the
container is stopped:
```bash
docker ps -a --filter name=<terminusdb-container> --format '{{.Status}}'
# Expect: Exited (...)
```

**Step 2 — Tar the storage volume:**
```bash
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_FILE="lms-backup-${TIMESTAMP}.tar.gz"

docker run --rm \
  -v <terminusdb-volume>:/data:ro \
  -v "$(pwd):/out" \
  alpine:3.20 \
  tar czf "/out/${BACKUP_FILE}" -C /data .
```
The `:ro` mount ensures nothing writes to the volume.

**Step 3 — Verify the backup:**
```bash
# Check the archive is readable and contains expected paths
tar tzf "$BACKUP_FILE" | head -20
# Should list directories like: admin/, _system/, _meta/, ...
```

```bash
# Check size looks plausible
ls -lh "$BACKUP_FILE"
# Approximate expectation: tens of MB for a running LMS instance
```

**Step 4 — Restart the container:**
```bash
docker start <terminusdb-container>
```

**Step 5 — Smoke test the live instance:**
```bash
# Wait ~10 s for server startup, then:
curl -f -u admin:$LMS_SCHEMA_TDB_PASSWORD \
  "http://10.0.10.20:6364/api/info/admin/lms" | python3 -m json.tool | head -5
# Expect: JSON response with database info, not an error.
```

### 1.2 Alternative: `terminusdb db dump`

The CLI command `terminusdb db dump admin/lms` (or the equivalent API endpoint
if available in v12.0.6) may produce a logical backup.  **This has not been
empirically verified against this project's instance** — the data format,
restore path, and handling of schema/commit/branch graphs are not documented in
`docs/terminusdb-notes.md`.  If the operator chooses to investigate and validate
this path, it can become a lighter-weight nightly option.  For this runbook,
**the volume snapshot (§1.1) is the required baseline.**

### 1.3 Restore from backup (if needed)

```bash
# 1. Stop the container
docker stop <terminusdb-container>

# 2. Empty the volume (destructive — confirmed operator action)
docker run --rm \
  -v <terminusdb-volume>:/data \
  alpine:3.20 \
  sh -c 'rm -rf /data/* /data/.[!.]* /data/..?*'

# 3. Restore the tar
docker run --rm \
  -v <terminusdb-volume>:/data \
  -v "$(pwd):/in:ro" \
  alpine:3.20 \
  tar xzf "/in/${BACKUP_FILE}" -C /data

# 4. Start the container
docker start <terminusdb-container>

# 5. Verify with a document count query
#    Wait ~10 s, then:
curl -s -u admin:$LMS_SCHEMA_TDB_PASSWORD \
  -X POST "http://10.0.10.20:6364/api/graphql/admin/lms" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ InboxNote { _id } }"}' | python3 -c "
import sys, json
data = json.load(sys.stdin)
count = len(data.get('data', {}).get('InboxNote', []))
print(f'InboxNote count: {count}')
# Should match the pre-backup count (operator should record
#   this number before step 1 above).
"
```

---

## 2. Bootstrap Procedure

All commands run from the repo root (`/home/basti/lms` or equivalent checkout).
The TDB password is read from the `LMS_SCHEMA_TDB_PASSWORD` env var.

**Shared connection args** (used in every command below):
```
--tdb-url http://10.0.10.20:6364 --tdb-org admin --tdb-db lms --tdb-user admin
```

### 2.1 Compose

```bash
uv run lms-schema compose --modules-dir schema/modules --out-dir build
```

**Expected:**
- Exit code 0
- Output:
  ```
  Composed N modules → build/composed.schema.json
  Lock file written → build/modules.lock.json
  Meta file written → build/composed.meta.json
  ```
  (`N` matches the number of modules in `schema/modules/`)
- `build/composed.schema.json` contains `@context` + all class/enum definitions
  including `SchemaModule` and `SchemaMigration`.
- `build/modules.lock.json` lists every module with version and checksum.

**Abort if:** exit code ≠ 0.

### 2.2 Diff against production main

```bash
uv run lms-schema diff \
  --modules-dir schema/modules \
  --tdb-url http://10.0.10.20:6364 \
  --tdb-org admin --tdb-db lms --tdb-user admin \
  --branch main
```

**Expected:**
- Exit code 1 (changes detected)
- Output shows exactly **two additive changes** under `[core]`:
  ```
  [core]
    + Class 'SchemaModule' added
    + Class 'SchemaMigration' added
  ```
- Final line:
  ```
  ✓  Changes detected, all guardrails satisfied.
  ```

**Abort if:**
- Exit code ≠ 1
- **Any change other than the two registry classes above** — if the diff shows
  anything about other classes (modified, removed, renamed), or any breaking
  changes, **STOP**.  Something is unexpected.  Do not proceed.
- Any guardrail violations or errors.

### 2.3 Plan the bootstrap

```bash
uv run lms-schema plan \
  --modules-dir schema/modules \
  --tdb-url http://10.0.10.20:6364 \
  --tdb-org admin --tdb-db lms --tdb-user admin \
  --branch schema-bootstrap
```

**Expected:**
- Exit code 1 (actions pending)
- Output shows:
  ```
  ⚠  Bootstrap: SchemaModule class not found on branch — registry writes will happen after schema push.

  Schema push needed: composed schema differs from live instance.

  Registry updates needed: N module(s)
    • core @ 1.1.0 (checksum: <hex>...)
    • inbox @ <version> (checksum: <hex>...)
    • ...

  Pending migrations: 0
  ```
  (one registry update per module in the workspace)

**Abort if:** exit code ≠ 1, or the plan shows pending migrations > 0, or any errors.

### 2.4 Apply to the bootstrap branch

```bash
uv run lms-schema apply \
  --modules-dir schema/modules \
  --tdb-url http://10.0.10.20:6364 \
  --tdb-org admin --tdb-db lms --tdb-user admin \
  --branch schema-bootstrap
```

`apply` will auto-create the `schema-bootstrap` branch from `main` if it does
not exist (the first run on a fresh branch).

**Expected:**
- Exit code 0
- Output sequence:
  ```
  Schema up to date — skipping push.   # existing classes match; context unchanged
  Pushing composed schema...
    Schema pushed.
  N registry module(s) upserted.
  Apply complete.
  ```
  (On the first run the schema IS pushed because SchemaModule/SchemaMigration
  don't exist on the branch yet.  A re-run shows "nothing to do".)

**Abort if:** exit code ≠ 0, or any error message appears.

### 2.5 Validate the bootstrap branch

```bash
uv run lms-schema validate \
  --modules-dir schema/modules \
  --tdb-url http://10.0.10.20:6364 \
  --tdb-org admin --tdb-db lms --tdb-user admin \
  --branch schema-bootstrap
```

**Expected:**
- Exit code 0
- Output:
  - GraphQL smoke tests pass for every concrete class on the branch.
  - Registry (SchemaModule docs) matches the composed lock file.
  - Final line:
    ```
    ✓ Validation passed.
    ```

**Abort if:** exit code ≠ 0, or any validation error.

### 2.6 Record main's pre-promote head

**Before promoting, record main's current commit identifier.**  This is needed
for the lighter rollback path in §3.2.

```bash
# Using curl (the same auth as the CLI):
curl -s -u admin:$LMS_SCHEMA_TDB_PASSWORD \
  "http://10.0.10.20:6364/api/log/admin/lms/local/branch/main?count=1" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['identifier'])"

# Save this value — label it PRE_PROMOTE_MAIN_HEAD.
```

Example output (save the full identifier, not just the prefix):
```
b19d8e49a7f3c2e1...
```

> **Note:** `get_branch_head` is the TdbClient method name; the equivalent REST
> call is the `/api/log` call above (see `docs/terminusdb-notes.md` §6).

### 2.7 Promote the bootstrap branch to main

```bash
uv run lms-schema promote \
  --modules-dir schema/modules \
  --tdb-url http://10.0.10.20:6364 \
  --tdb-org admin --tdb-db lms --tdb-user admin \
  --branch schema-bootstrap
```

**Expected:**
- Exit code 0
- Output:
  ```
  WARNING: promote fast-forwards main to the branch head (XXXXXXXXXX...), including any other commits on that branch.
  Promoted 'schema-bootstrap' → main.
    Main is now at commit: XXXXXXXXXX...
  ```
  (`promote` verifies that main's head is an ancestor of the branch before
  fast-forwarding, and re-verifies the main schema post-reset.)

**Abort if:** exit code ≠ 0.

---

## 3. Rollback

### 3.1 Full restore from backup

If anything went wrong before, during, or after the bootstrap — or if the
operator wants a clean undo — follow §1.3 (restore from the tar backup).  This
returns the entire instance to the exact pre-bootstrap state.

### 3.2 Lighter rollback: reset main to pre-promote commit

If the bootstrap completed but must be undone (and promotion already happened):

**Prerequisite:** `PRE_PROMOTE_MAIN_HEAD` was recorded in §2.6.

```bash
curl -s -u admin:$LMS_SCHEMA_TDB_PASSWORD \
  -X POST "http://10.0.10.20:6364/api/reset/admin/lms/local/branch/main" \
  -H "Content-Type: application/json" \
  -d '{"commit_descriptor": "admin/lms/local/commit/PRE_PROMOTE_MAIN_HEAD"}'
```

**Expected:** HTTP 200.

This resets main's branch pointer back to the pre-promote commit, undoing the
schema change and registry documents.  The `schema-bootstrap` branch can then
be deleted:

```bash
curl -s -u admin:$LMS_SCHEMA_TDB_PASSWORD \
  -X DELETE "http://10.0.10.20:6364/api/branch/admin/lms/local/branch/schema-bootstrap"
```

**If promotion has NOT happened yet** (i.e., stuck at step 2.4–2.6): simply
delete the `schema-bootstrap` branch:

```bash
curl -s -u admin:$LMS_SCHEMA_TDB_PASSWORD \
  -X DELETE "http://10.0.10.20:6364/api/branch/admin/lms/local/branch/schema-bootstrap"
```

### 3.3 Verify after rollback

```bash
# Confirm main no longer has SchemaModule/SchemaMigration:
curl -s -u admin:$LMS_SCHEMA_TDB_PASSWORD \
  -X POST "http://10.0.10.20:6364/api/graphql/admin/lms" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ SchemaModule(limit:1) { _id } }"}'
# Expect: "Cannot query field" error — the class no longer exists.

# Confirm instance data is intact:
curl -s -u admin:$LMS_SCHEMA_TDB_PASSWORD \
  -X POST "http://10.0.10.20:6364/api/graphql/admin/lms" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ InboxNote { _id } }"}'
# Should return the same documents as before.
```

---

## 4. Post-Bootstrap Verification

After successful promotion (§2.7), confirm the production state:

```bash
# Main now has SchemaModule registry docs:
uv run lms-schema validate \
  --modules-dir schema/modules \
  --tdb-url http://10.0.10.20:6364 \
  --tdb-org admin --tdb-db lms --tdb-user admin \
  --branch main

# Expect: exit 0, "✓ Validation passed."
```

Confirm services still work (queryd health, ingestd processing) — these are
read-only with respect to the schema change and should be unaffected.

---

## 5. Operator Decisions & Gaps

1. **Container/volume names**: The runbook uses placeholder `<terminusdb-container>` and `<terminusdb-volume>`.  The operator must substitute the actual names from the production docker compose setup.

2. **Backup storage**: The backup tarball must be stored **off-machine** (at minimum, copied off the host before proceeding).  The runbook writes to the current working directory; the operator must verify sufficient disk space and arrange off-machine copy.

3. **`terminusdb db dump`**: Not verified for v12.0.6 in this project's context.  If the operator validates it, it can become a lighter nightly backup option.  For now the volume snapshot is mandatory.

4. **Quiescence**: The backup step stops the container.  This means the system is unavailable during the backup window.  The operator should schedule accordingly and notify users.  Expected downtime: 3–5 minutes for the backup, plus another 2–3 minutes for the bootstrap steps if all goes well.

5. **Post-promote service restart**: The schema change is backward-compatible (additive only), so services do not require a restart.  However, if any service caches the schema internally, a restart is recommended.
