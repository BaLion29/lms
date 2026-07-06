# ingestd

**ingestd** is a background daemon that watches TerminusDB for new
`InboxNote`/`InboxAudio` documents and turns them into validated `Task`,
`Event`, `Reminder`, and `Person` documents via an LLM. Every extracted
document records its provenance through the `derived_from` link back to the
original inbox item.

## How it works

ingestd runs a poll loop against TerminusDB:

1. Fetch all known `Person` and `Location` entities to build an entity index.
2. Gather `InboxNote` documents with `status="new"` and `InboxAudio` documents
   with `status="transcribed"`.
3. Pre-fetch existing `Task`, `Event`, and `Reminder` documents and build an
   idempotency set from their `derived_from` fields — an inbox item is skipped
   if any output already points back to it.
4. For each inbox item, send the text to a Pydantic AI extraction agent that
   returns typed proposals (`TaskProposal`, `EventProposal`, `ReminderProposal`,
   `PersonProposal`) with language preserved and relative dates resolved against
   the note's `created_at`/`recorded_at`.
5. Run naive entity linking: case-insensitive exact match on known `Person` and
   `Location` names; new `Location` names are auto-created on the fly.
6. Insert the resulting documents in one commit per inbox item. If TerminusDB
   rejects the documents (schema violation), the rejection body is fed back to
   the LLM verbatim and extraction is retried up to `INGESTD_MAX_LLM_RETRIES`
   times.
7. On success, flip the inbox document status to `processed`; on exhaustion,
   flip to `failed`. The loop never aborts on a single-document failure.
8. On `SIGTERM`/`SIGINT`, finish the current document and exit gracefully.

## Configuration

All settings are read from environment variables with the `INGESTD_` prefix.
Required variables are validated at startup.

| Env var                       | Default                  | Required | Description                                      |
|-------------------------------|--------------------------|----------|--------------------------------------------------|
| `INGESTD_TDB_URL`             | `http://localhost:6363`  | No       | TerminusDB base URL                              |
| `INGESTD_TDB_ORG`             | `admin`                  | No       | TerminusDB organisation                          |
| `INGESTD_TDB_DB`              | —                        | **Yes**  | TerminusDB database name                         |
| `INGESTD_TDB_BRANCH`          | `main`                   | No       | TerminusDB branch                                |
| `INGESTD_TDB_USER`            | `admin`                  | No       | TerminusDB basic-auth username                   |
| `INGESTD_TDB_PASSWORD`        | —                        | **Yes**  | TerminusDB basic-auth password                   |
| `INGESTD_LLM_BASE_URL`        | `""`                     | **Yes**  | LLM API base URL (e.g. LiteLLM gateway)          |
| `INGESTD_LLM_API_KEY`         | `""`                     | **Yes**  | LLM API key                                      |
| `INGESTD_LLM_MODEL`           | `""`                     | **Yes**  | LLM model name                                   |
| `INGESTD_POLL_INTERVAL_SECONDS`| `60`                    | No       | Seconds between poll cycles                      |
| `INGESTD_MAX_LLM_RETRIES`     | `3`                      | No       | Max retries on TerminusDB rejection per inbox item|
| `INGESTD_DRY_RUN`             | `false`                  | No       | Run extraction without writing to the database   |

## Run modes

- **Service** (default): `uv run ingestd` — polls TerminusDB indefinitely,
  processing new inbox items as they arrive.
- **Once**: `uv run ingestd --once` — runs a single extraction cycle and exits.
  Returns exit code 1 if the cycle encounters an error.
- **Dry-run**: `uv run ingestd --dry-run` or `INGESTD_DRY_RUN=true uv run ingestd` —
  performs real LLM calls but writes nothing to the database. This is the
  primary manual testing mode.
- **Once + dry-run**: `uv run ingestd --once --dry-run` — one cycle, no writes.

## Deployment

ingestd has **zero runtime dependencies on extensions** (spec §2).  In production
you **must** install at least one source+extractor extension (e.g. `lms-ext-inbox`)
alongside the kernel.  Without extension packages, ingestd discovers no sources
and exits at startup by design.

## Local development

For a full dockerised environment (TerminusDB + bootstrap + all services),
see the root `compose.yaml` quickstart:

```bash
# From repo root:
cp .env.example .env && vim .env                    # edit secrets
docker compose --profile bootstrap up bootstrap --abort-on-container-exit
docker compose up -d
```

If you prefer to run ingestd directly on the host (with an external TerminusDB):

```bash
# 1. Start TerminusDB (only dependency)
#    (use root compose.yaml or point at an
#     external instance via TDB_URL)

# 2. Create the database and push the schema (idempotent)
uv run python schema/bootstrap.py

# 3. Seed example inbox documents (idempotent)
uv run python schema/seed.py

# 4. Run a dry-run extraction cycle (reads + LLM calls, zero writes)
uv run ingestd --once --dry-run

# 5. Run a real extraction cycle
uv run ingestd --once

# Tests
uv run pytest

# Lint + format check
uv run ruff check
uv run ruff format --check
```

Required environment exports (use placeholder values, not a real API key):

```bash
export INGESTD_TDB_DB=ingestd_dev
export INGESTD_TDB_PASSWORD=root
export INGESTD_LLM_BASE_URL=http://localhost:4000
export INGESTD_LLM_API_KEY=sk-placeholder
export INGESTD_LLM_MODEL=gpt-4o
```

## Example extraction

German seed note "Ich muss bis Freitag den Mietvertrag unterschreiben und an
Anna Meier schicken." (created Sunday 2026-07-05) produced the following
extraction:

```json
{
  "@type": "Task",
  "name": "Mietvertrag unterschreiben und an Anna Meier schicken",
  "status": "open",
  "derived_from": "InboxNote/z6iL7sujPwLfOMSi",
  "due_date": "2026-07-10T00:00:00Z",
  "created_at": "2026-07-05T19:19:26Z",
  "updated_at": "2026-07-05T19:19:26Z"
}
```

"bis Freitag" was resolved to 2026-07-10, the correct absolute Friday relative
to the note's creation date (Sunday 2026-07-05 → Friday = +5 days).

## Architecture sketch

| Module           | Responsibility                                               |
|------------------|--------------------------------------------------------------|
| `settings`       | Application settings loaded from environment (`INGESTD_`)   |
| `models`         | Pydantic v2 document models mirroring the TerminusDB schema |
| `tdb`            | Async TerminusDB HTTP client (documents, GraphQL, lifecycle)|
| `extraction`     | Pydantic AI agent turning freeform notes into typed proposals|
| `linking`        | Entity index, context blocks, case-insensitive name matching |
| `pipeline`       | Orchestration: fetch → extract → link → insert → flip status|
| `main`           | CLI entrypoint (`ingestd` console script), signal handling   |
