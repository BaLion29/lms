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

## Configuration

See [Configuration reference](../../docs/reference/configuration.md) for all
`TRIGGERD_*` environment variables and [Concept: Architecture](../../docs/concepts/architecture.md)
for how triggerd fits into the data flow.

## Tests

Run tests from the monorepo root:

```bash
uv run pytest services/triggerd/
```
