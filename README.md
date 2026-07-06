# lms

An opinionated ADHD-focussed Life-Management System. It captures thoughts
(text notes, voice memos, files), runs them through AI extraction pipelines
to turn unstructured input into linked, typed documents (tasks, events,
people, places, reminders, routines), and stores everything in a TerminusDB
graph database — the single source of truth. The result is a queryable,
branch-safe knowledge base that a conversational agent can reason over.

## Architecture at a glance

| Unit | Role |
|---|---|
| **terminusdb** | SSOT graph database (TerminusDB v12). All state lives here. |
| **captured** (`:8088`) | Ingestion API — accepts notes, files, voice memos; dispatches to handler plugins. |
| **ingestd** | Polling worker — picks up `new` inbox items, runs extractor plugins via LLM, writes typed documents. |
| **queryd** (`:8087`) | Conversational agent API — read tools, GraphQL, and optional gated write-tool plugins. |
| **bootstrap** | One-shot container (profile `bootstrap`) — creates database, composes & applies schema (including extension schema modules), installs extensions into a shared overlay volume. |

Full details: [ARCHITECTURE.md](./ARCHITECTURE.md).

**External prerequisite:** An OpenAI-compatible LLM endpoint (e.g. a
[LiteLLM](https://github.com/BerriAI/litellm) proxy) is **required** and
NOT part of this compose stack. Set `LMS_LLM_BASE_URL` to its address.

## Quickstart (Docker Compose)

**Prerequisites:** Docker + Docker Compose ≥ 2.24 (the `!reset` YAML tag
used by the external-TDB overlay requires v2.24+; the base stack works with
any reasonably recent version).

```bash
# 1. Copy and edit the env template
cp .env.example .env
vim .env   # set TDB_PASSWORD, CAPTURED_API_TOKEN, QUERYD_API_TOKEN,
           # LMS_LLM_BASE_URL (+ LMS_LLM_API_KEY if needed), and optionally
           # choose LMS_EXTENSIONS

# 2. Bootstrap (one-shot: creates DB, pushes schema, installs extensions)
docker compose --profile bootstrap up bootstrap --abort-on-container-exit

# 3. Start the runtime services
docker compose up -d

# 4. Verify
curl localhost:8087/healthz   # queryd
curl localhost:8088/healthz   # captured
```

**First capture** (replace `$TOKEN` with the value of `CAPTURED_API_TOKEN`):

```bash
curl -s -X POST http://localhost:8088/v1/capture/note \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy milk on the way home", "kind": "note"}'
```

The response is `201` with `{"id": "...", "kind": "note"}`.  ingestd will
pick it up on its next poll cycle, extract structured data via the LLM, and
write the resulting documents to TerminusDB.

## Extensions

An **extension** is one pip-installable Python package. It can contain any
subset of: a schema module (contributes class/enum definitions to the
composed schema), ingestd source/extractor plugins, queryd write-tool
plugins, and captured handler plugins.  Extensions are discovered via five
standard entry-point groups — see [docs/alpha-spec.md §6](docs/alpha-spec.md)
for the packaging convention.

### Adding extensions

1. Edit `LMS_EXTENSIONS` in `.env` — comma-separated list.
2. Re-run the bootstrap profile:
   ```bash
   docker compose --profile bootstrap up bootstrap --abort-on-container-exit
   ```
3. Restart the services so they pick up the new overlay:
   ```bash
   docker compose restart captured ingestd queryd
   ```

### Removing extensions

1. Remove the entry from `LMS_EXTENSIONS` in `.env`.
2. Set `LMS_EXTENSIONS_PURGE=true` in `.env`.
3. Re-run bootstrap (it wipes the overlay first, then reinstalls the
   remaining extensions).
4. Restart services and set `LMS_EXTENSIONS_PURGE=false` again.

> **Important:** Removing an extension stops its plugins from loading, but
> its schema module and any documents already written remain in TerminusDB.
> Removing schema is a breaking change — it requires an explicit `lms-schema`
> operation outside the compose workflow.

### Accepted specifier formats

Entries in `LMS_EXTENSIONS` may be:

- **PyPI name** (with optional version): `lms_ext_inbox>=0.1.0`
- **Git URL**: `git+https://github.com/user/lms-ext-foo.git`
- **Wheel filename** (resolved against `./dist`): `lms_ext_inbox-0.1.0a1-py3-none-any.whl`

### First-party extensions

Build wheels into `./dist/` with `uv build`, then list them in `LMS_EXTENSIONS`:

| Extension | Description |
|---|---|
| `lms-ext-inbox` | InboxNote/InboxAudio schema, ingest sources, and capture handlers |
| `lms-ext-people` | Person/Contact schema module |
| `lms-ext-places` | Location schema module |
| `lms-ext-planning` | Task/Event schema module and queryd write tools |
| `lms-ext-reminders` | Reminder/Trigger schema modules and queryd write tools |
| `lms-ext-routines` | Routine/RoutineStep/Activity/ActivitySpec schema module |

### Writing your own

See **[docs/alpha-spec.md §6](docs/alpha-spec.md)** for the packaging
convention, the five entry-point groups (`lms.schema_modules`,
`lms.ingestd.sources`, `lms.ingestd.extractors`, `lms.queryd.tools`,
`lms.captured.handlers`), and the contract every extension must fulfill.

## Using an external TerminusDB / production

To connect to an already-running TerminusDB instance instead of the bundled one:

```bash
# Set TDB_URL in .env (uncomment and fill in):
#   TDB_URL=http://10.0.10.20:6364

docker compose -f compose.yaml -f compose.external-tdb.yaml \
  --profile bootstrap up bootstrap --abort-on-container-exit

docker compose -f compose.yaml -f compose.external-tdb.yaml up -d
```

> ⚠️ **Before touching a production database**, read
> **[docs/production-bootstrap.md](docs/production-bootstrap.md)** — it
> covers the mandatory backup/promote/rollback discipline.  Schema changes
> on a live instance require a cold volume snapshot first.

## Development

This is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/).

```bash
uv run pytest          # all tests
uv run ruff check      # lint
uv run ruff format     # format
```

The services can also run outside Docker — set the environment variables
documented in each service's README and start them directly:

- [services/captured/](services/captured/) (no standalone README yet)
- [services/ingestd/README.md](services/ingestd/README.md)
- [services/queryd/README.md](services/queryd/README.md)

## Configuration reference

Every variable from `.env.example` (and compose.yaml-only variables with
defaults):

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `TDB_PASSWORD` | (empty) | **yes** — generate e.g.: `openssl rand -hex 32` | TerminusDB admin password |
| `TDB_ORG` | `admin` | no | TerminusDB organization name |
| `TDB_DB` | `lms` | no | TerminusDB database name |
| `TDB_USER` | `admin` | no | TerminusDB user |
| `TDB_BRANCH` | `main` | no | TerminusDB branch for schema operations |
| `TDB_HOST_PORT` | `6363` | no | Host port mapped to TerminusDB's 6363 |
| `TDB_URL` | — | external overlay only | TerminusDB base URL (required with external overlay) |
| `LMS_LLM_BASE_URL` | `http://host.docker.internal:4000` | **yes** | OpenAI-compatible LLM endpoint (e.g. LiteLLM proxy) |
| `LMS_LLM_API_KEY` | (empty) | no | API key for the LLM endpoint |
| `LMS_LLM_MODEL` | `gpt-4.1-mini` | no | Model name passed to the LLM endpoint |
| `CAPTURED_API_TOKEN` | (empty) | **yes** — generate e.g.: `openssl rand -hex 32` | Bearer token for `POST /v1/capture/*` |
| `QUERYD_API_TOKEN` | (empty) | **yes** — generate e.g.: `openssl rand -hex 32` | Bearer token for queryd endpoints |
| `QUERYD_ENABLE_WRITES` | `false` | no | Gate write-tool plugins in queryd |
| `CAPTURED_HOST_PORT` | `8088` | no | Host port for captured |
| `QUERYD_HOST_PORT` | `8087` | no | Host port for queryd |
| `LMS_EXTENSIONS` | (empty) | no | Comma-separated extension specifiers to install |
| `LMS_EXTENSIONS_PURGE` | `false` | no | Set `true` to wipe the shared overlay before reinstalling |
| `INGESTD_POLL_INTERVAL_SECONDS` | `60` | no | Seconds between ingestd poll cycles |
| `INGESTD_MAX_LLM_RETRIES` | `3` | no | Max LLM call retries per item |
| `INGESTD_DRY_RUN` | `false` | no | If `true`, extract but do not write to TerminusDB |
