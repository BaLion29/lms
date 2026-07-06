# Getting Started

## Prerequisites

- **Docker** and **Docker Compose v2**.
- An **OpenAI-compatible LLM endpoint** — the stack requires an external LLM
  proxy (e.g. [LiteLLM](https://github.com/BerriAI/litellm)) and does NOT run
  one. Set `FIRNLINE_LLM_BASE_URL` to its address.
- **TerminusDB** — either an existing external instance, or use the bundled
  container (see below).

For local development you also need **Python ≥ 3.12** and
[uv](https://docs.astral.sh/uv/).

## Quickstart (Docker Compose)

### 1. Configure the environment

```bash
cp .env.example .env
vim .env
```

Set at minimum:
- `TDB_URL` — your TerminusDB base URL
- `TDB_PASSWORD` — TerminusDB admin password (generate with `openssl rand -hex 32`)
- `CAPTURED_API_TOKEN` — bearer token for the capture API
- `QUERYD_API_TOKEN` — bearer token for the query agent
- `FIRNLINE_LLM_BASE_URL` — your LiteLLM/OpenAI-compatible endpoint
- Optionally `FIRNLINE_LLM_API_KEY` if your endpoint requires one

### 2. Bootstrap the schema

The bootstrap profile creates the database (if it doesn't exist), composes all
schema modules (core + installed extensions), applies the schema to TerminusDB,
and installs extensions into a shared overlay volume.

```bash
docker compose --profile bootstrap up bootstrap --abort-on-container-exit
```

### 3. Start the runtime services

```bash
docker compose up -d
```

This starts **captured** (port 8088), **ingestd**, and **queryd** (port 8087).

### 4. Verify

```bash
curl http://localhost:8087/healthz   # queryd
curl http://localhost:8088/healthz   # captured
```

Both should return 200 with `{"status": "ok", ...}`.

### 5. First capture

Replace `$TOKEN` with your `CAPTURED_API_TOKEN` value:

```bash
curl -s -X POST http://localhost:8088/v1/capture/note \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy milk on the way home", "kind": "note"}'
```

Returns `201` with `{"id": "...", "kind": "note"}`. ingestd picks it up on its
next poll cycle (default: every 60 seconds), runs extraction via the LLM, and
writes structured documents to TerminusDB.

## Bundled TerminusDB (self-contained)

To run a bundled TerminusDB container alongside the services instead of
connecting to an external one:

```bash
# 1. Set TDB_URL=http://terminusdb:6363 in .env
#    Also set TDB_PASSWORD — it's used as the TerminusDB admin password.

# 2. Bootstrap
docker compose -f compose.yaml -f compose.bundled-tdb.yaml \
  --profile bootstrap up bootstrap --abort-on-container-exit

# 3. Start
docker compose -f compose.yaml -f compose.bundled-tdb.yaml up -d
```

The `compose.bundled-tdb.yaml` overlay adds a `terminusdb` service
(`terminusdb/terminusdb-server:v12.0.6`), sets up health checks, and adds
`depends_on` relationships so services wait for TerminusDB to be healthy.
Data is persisted in the `terminusdb_data` Docker volume.

## Chatting with queryd

```bash
curl -s -X POST http://localhost:8087/v1/chat \
  -H "Authorization: Bearer $QUERYD_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What do I need to do today?"}]}'
```

The response includes a `message` (natural-language answer) and a `tool_trace`
(debug information about tool calls the agent made).

To enable write tools (e.g. marking tasks done), set
`QUERYD_ENABLE_WRITES=true` in `.env` and restart.

## Adding or changing extensions

Edit `FIRNLINE_EXTENSIONS` in `.env` (comma-separated), then re-run the
bootstrap profile:

```bash
docker compose --profile bootstrap up bootstrap --abort-on-container-exit
docker compose restart captured ingestd queryd
```

To purge and reinstall from scratch, set `FIRNLINE_EXTENSIONS_PURGE=true`,
run bootstrap, then set it back to `false`.

> Removing an extension stops its plugins from loading, but its schema module
> and any documents already written remain in TerminusDB. Removing schema is a
> breaking change — it requires an explicit `firnline-schema` operation.

## Local Development

```bash
# Install dependencies
uv sync

# Run all tests (no network required — uses respx mocks and TestModel)
uv run pytest

# Lint and format
uv run ruff check
uv run ruff format --check
```

To run a service directly on the host (with an external TerminusDB), set the
required environment variables and use `uv run`:

```bash
# queryd example
QUERYD_TDB_URL=http://localhost:6363 \
QUERYD_TDB_DB=dev \
QUERYD_TDB_PASSWORD=root \
QUERYD_API_TOKEN=dev-token \
QUERYD_LLM_BASE_URL=http://localhost:4000 \
QUERYD_LLM_API_KEY=sk-placeholder \
QUERYD_LLM_MODEL=gpt-4.1-mini \
uv run queryd
```

See [Configuration](configuration.md) for the full list of per-service
environment variables.

## Next Steps

- Read the [Architecture](architecture.md) overview to understand the component
  model.
- Learn how to [write an extension](extensions.md) to add new domains.
- Review the [Operations](operations.md) runbook for production schema
  management.
