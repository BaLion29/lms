# triggerd

Background daemon that polls TerminusDB for Trigger documents, evaluates
them via pluggable evaluator plugins, and materializes TriggerFiring
records — one commit per evaluation cycle.

## Quickstart

From the monorepo root:

```bash
docker compose --profile bootstrap up bootstrap --abort-on-container-exit
docker compose up -d                        # starts triggerd (polling)
```

For local dev without Docker:

```bash
export TRIGGERD_TDB_DB=dev
export TRIGGERD_TDB_PASSWORD=root

uv run triggerd              # daemon mode (poll every 60s)
uv run triggerd --once       # single evaluation cycle
uv run triggerd --dry-run    # real evaluation, no writes
```

## How it works

1. Discover active evaluator plugins (each declares which Trigger `@type` strings it
   can evaluate).
2. Fetch Trigger documents that have been modified within the lookback window.
3. For each Trigger, run the matching evaluator to compute candidate occurrences.
4. Deduplicate against existing TriggerFiring documents.
5. Insert new TriggerFiring documents (or suppress duplicates). On `SIGTERM`/`SIGINT`,
   finish the current cycle and exit gracefully.

> **Invariant:** The database is the only integration point. triggerd has no HTTP
> API — it reads Trigger documents and writes TriggerFiring documents exclusively
> via the TDB client.

## Environment variables

| Variable                          | Default          | Description                              |
|-----------------------------------|------------------|------------------------------------------|
| `TRIGGERD_TDB_DB`                 | *(required)*     | TerminusDB database name                 |
| `TRIGGERD_TDB_PASSWORD`           | *(required)*     | TerminusDB password                      |
| `TRIGGERD_TDB_URL`                | `http://localhost:6363` | TerminusDB server URL             |
| `TRIGGERD_TDB_ORG`                | `admin`          | TerminusDB organization                  |
| `TRIGGERD_TDB_BRANCH`             | `main`           | TerminusDB branch                        |
| `TRIGGERD_TDB_USER`               | `admin`          | TerminusDB user                          |
| `TRIGGERD_POLL_INTERVAL_SECONDS`  | `60`             | Seconds between evaluation cycles        |
| `TRIGGERD_LOOKBACK_SECONDS`       | `900`            | How far back to look for Trigger changes |
| `TRIGGERD_DEFAULT_TIMEZONE`       | `Europe/Zurich`  | Fallback timezone for date parsing       |
| `TRIGGERD_DRY_RUN`                | `false`          | Evaluate but skip writes (`--dry-run`)   |
| `TRIGGERD_STRICT_PLUGINS`         | `false`          | Fail startup if any plugin is skipped    |
| `TRIGGERD_LIVENESS_FILE`         | `/tmp/triggerd-alive` | Path touched on each successful cycle (for healthchecks) |

## CLI flags

| Flag           | Description                                    |
|----------------|------------------------------------------------|
| `--once`       | Run a single evaluation cycle and exit.        |
| `--dry-run`    | Evaluate but do not write to the database.     |

## Tests

Run tests from the monorepo root:

```bash
uv run pytest services/triggerd/
```
