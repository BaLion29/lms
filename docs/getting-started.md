# Getting Started

## Prerequisites

- **Docker** and **Docker Compose v2** (≥ 2.24).
- An **OpenAI-compatible LLM endpoint** — the stack requires an external LLM
  proxy (e.g. [LiteLLM](https://github.com/BerriAI/litellm)) and does NOT run
  one by default.  See [LLM options](#llm-options) below.

For local development you also need **Python ≥ 3.12** and
[uv](https://docs.astral.sh/uv/).

## 1. Configure the environment

```bash
cp .env.example .env
vim .env
```

Set the **4 required values**:

| Variable | Purpose | How to generate |
|---|---|---|
| `TDB_PASSWORD` | TerminusDB admin password | `openssl rand -hex 32` |
| `CAPTURED_API_TOKEN` | Bearer token for the capture API | `openssl rand -hex 32` |
| `QUERYD_API_TOKEN` | Bearer token for the queryd API | `openssl rand -hex 32` |
| `FIRNLINE_LLM_BASE_URL` | Your OpenAI-compatible LLM endpoint | See [LLM options](#llm-options) |

The bundled TerminusDB uses `TDB_URL=http://terminusdb:6363` by default — you
do **not** need to set `TDB_URL` unless you're using an external instance (see
[Using external TerminusDB](#using-external-terminusdb)).

## 2. Start the stack

```bash
docker compose up -d
```

This does everything in one command:

1. **Bootstrap** runs first as a one-shot init container.  It waits for
   TerminusDB (bundled or external), creates the `firnline` database if it
   doesn't exist, composes all schema modules (core + installed extensions),
   applies the schema + migrations, and installs extensions into a shared
   overlay volume.
2. Once bootstrap completes successfully, all other services start: **captured**
   (port 8088), **ingestd**, **indexed** (port 8089), **queryd** (port 8087),
   **triggerd**, **effectd**, **mcpd** (port 8090), and **webui** (port 3000).

Bootstrap is **idempotent** — re-running it is safe whether or not the
database already exists and the schema is already applied.

### Checking health

```bash
# All services and their health states
docker compose ps

# Bootstrap output (for troubleshooting)
docker compose logs bootstrap

# Per-service health endpoints
curl http://localhost:8087/healthz   # queryd
curl http://localhost:8088/healthz   # captured
curl http://localhost:8089/healthz   # indexed
curl http://localhost:8090/healthz   # mcpd
```

Every endpoint returns `{"status": "ok", ...}` with HTTP 200 when healthy.

## 3. First capture

Replace `$TOKEN` with your `CAPTURED_API_TOKEN` value:

```bash
curl -s -X POST http://localhost:8088/v1/capture/note \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy milk on the way home", "kind": "note"}'
```

Returns `201` with `{"id": "...", "kind": "note"}`.  `ingestd` picks it up on
its next poll cycle (default: every 60 seconds), runs extraction via the LLM,
and writes structured documents to TerminusDB.

### Querying queryd

```bash
curl -s -X POST http://localhost:8087/v1/graphql \
  -H "Authorization: Bearer $QUERYD_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ Task { id name done } }"}'
```

The response is a standard GraphQL JSON payload listing all Task documents.

To list available write tools, call `GET /v1/tools`. Tools are gated by
`QUERYD_ENABLE_WRITES` (see [mcpd](mcpd.md) for dynamic MCP tool registration).

## Using external TerminusDB

By default, the stack includes a bundled TerminusDB container.  To use your own
TerminusDB instance instead:

1. Open `compose.yaml` and delete or comment out the **`terminusdb`** service
   block and the **`terminusdb_data`** volume at the bottom.
2. In `.env`, uncomment and set `TDB_URL` to your instance (and set
   `TDB_PASSWORD` to its admin password).
3. Run `docker compose up -d` as usual — bootstrap will wait for your external
   TerminusDB before proceeding.

## LLM options

The stack requires an OpenAI-compatible LLM endpoint.  You have two options:

### Option A: Host-local LLM via host-gateway (default)

Set `FIRNLINE_LLM_BASE_URL=http://host.docker.internal:4000` in `.env` and run
your LLM proxy (e.g. LiteLLM) on the Docker host at port 4000.  The compose
file already includes `extra_hosts: host.docker.internal:host-gateway` on every
service that needs LLM access, so this works on Linux too — no extra
configuration needed.

### Option B: LiteLLM inside Docker (commented block)

`compose.yaml` includes a **commented-out** `litellm` service block near the
top.  Uncomment it, create a `litellm_config.yaml` file in the repo root, and
set `FIRNLINE_LLM_BASE_URL=http://litellm:4000` in `.env`.  The block uses the
`ghcr.io/berriai/litellm:main-stable` image.

### LLM authentication

If your endpoint requires an API key, set `FIRNLINE_LLM_API_KEY` in `.env`.
Leave it empty for unauthenticated endpoints.

## Adding or changing extensions

Edit `FIRNLINE_EXTENSIONS` in `.env` (comma-separated), then re-run bootstrap
and restart the affected services:

```bash
docker compose up bootstrap
docker compose restart captured ingestd queryd
```

To purge and reinstall from scratch, set `FIRNLINE_EXTENSIONS_PURGE=true`, run
the bootstrap container, then set it back to `false`.

> Removing an extension stops its plugins from loading, but its schema module
> and any documents already written remain in TerminusDB. Removing schema is a
> breaking change — it requires an explicit `firnline-schema` operation.

## Troubleshooting

### Bootstrap fails: "TerminusDB not reachable"

This means bootstrap could not connect to TerminusDB within 120 seconds.

- **Bundled TerminusDB**: check `docker compose logs terminusdb` for startup
  errors.  The bundled DB needs `TDB_PASSWORD` set.
- **External TerminusDB**: verify `TDB_URL` is correct and the instance is
  reachable from the Docker network.  Try `docker compose exec bootstrap
  python -c "import httpx; print(httpx.get('$TDB_URL/api/info'))"` to test
  connectivity.

### Services show unhealthy status

Check health states with `docker compose ps`.  Services with `(unhealthy)`
status may need a restart or are waiting on dependencies.

- `webui` takes **30–60 seconds** to compile the frontend at first boot
  (healthcheck `start_period` allows 120s).
- Polling workers (`ingestd`, `triggerd`, `effectd`) may be unhealthy for the
  first few minutes if no poll cycle has completed yet.

### Voice memo pipeline

Voice memos are captured through the same `POST /v1/capture/file` endpoint as
other files.  The `captured` service accepts audio uploads (common formats:
WAV, MP3, M4A, OGG/Opus).  `ingestd` extracts text via the LLM (if your LLM
supports audio transcription), then processes the transcript through the
standard extraction pipeline.

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
