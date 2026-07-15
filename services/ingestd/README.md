# ingestd

Background daemon that polls TerminusDB for new inbox items, runs LLM
extraction via pluggable extractor plugins, and writes typed documents
(Task, Event, Reminder, Person, etc.) back to TerminusDB — one commit per
inbox item, with full provenance via `derived_from`.

## Quickstart

From the monorepo root:

```bash
docker compose --profile bootstrap up bootstrap --abort-on-container-exit
docker compose up -d                        # starts ingestd (polling)
```

For local dev without Docker:

```bash
export INGESTD_TDB_DB=dev
export INGESTD_TDB_PASSWORD=root
export INGESTD_LLM_BASE_URL=http://localhost:4000
export INGESTD_LLM_API_KEY=sk-placeholder
export INGESTD_LLM_MODEL=gpt-4.1-mini

uv run ingestd              # daemon mode (poll every 60s)
uv run ingestd --once       # single poll cycle
uv run ingestd --dry-run    # real LLM calls, no writes
```

## How it works

1. Discover active source plugins (document type + status to poll).
2. Build entity index (known Person, Location).
3. Fetch inbox items matching source criteria.
4. Skip items that already have derived documents (idempotency guard).
5. Send text to LLM extraction agent with typed output schemas from extractors.
6. Link known entities (case-insensitive exact match).
7. Insert documents in one commit per item. On schema rejection, feed error
   back to LLM and retry (up to `INGESTD_MAX_LLM_RETRIES`).
8. Flip inbox status to `processed` or `failed`.
9. On `SIGTERM`/`SIGINT`, finish current item and exit gracefully.

ingestd requires at least one source+extractor extension installed to be
useful — without extensions it discovers no sources and exits.

## Configuration, extensions, and tests

Full documentation:

- [Configuration reference](../../docs/reference/configuration.md) — all `INGESTD_*` env vars
- [Architecture](../../docs/concepts/architecture.md) — how ingestd fits into the system
- [Extension development](../../docs/development/extension-development.md) — writing source and extractor plugins

Run tests from the monorepo root:

```bash
uv run pytest services/ingestd/
```
