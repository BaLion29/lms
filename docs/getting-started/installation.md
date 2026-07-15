# Installation

Install the firnline stack on any host with Docker.

## Prerequisites

- **Docker** and **Docker Compose v2** (≥2.24).
- An **OpenAI-compatible LLM endpoint** (e.g. [LiteLLM](https://github.com/BerriAI/litellm)). The stack does not run an LLM itself — you must provide `FIRNLINE_LLM_BASE_URL` pointing to your proxy. Set `FIRNLINE_LLM_API_KEY` if the endpoint requires authentication.
- **Python ≥ 3.12** and **[uv](https://docs.astral.sh/uv/)** — only needed for local development (see [development/local-development.md](../development/local-development.md)).
- **TerminusDB** — pick one:
  - **External**: an existing TerminusDB v12.0.6 instance you manage separately. Requires network access from the Docker host.
  - **Bundled**: a self-contained TerminusDB container managed by Docker Compose (no separate database setup).

## Configure the environment

```bash
cp .env.example .env
vim .env
```

Required variables:

| Variable | Purpose |
|---|---|
| `TDB_URL` | TerminusDB base URL. For bundled: `http://terminusdb:6363`. For external: your instance URL. |
| `TDB_PASSWORD` | TerminusDB admin password. Generate: `openssl rand -hex 32` |
| `CAPTURED_API_TOKEN` | Bearer token for the capture API. Generate: `openssl rand -hex 32` |
| `QUERYD_API_TOKEN` | Bearer token for queryd endpoints. Generate: `openssl rand -hex 32` |
| `FIRNLINE_LLM_BASE_URL` | Your LiteLLM / OpenAI-compatible endpoint (e.g. `http://host.docker.internal:4000`) |

Optional but common:

| Variable | Default | Purpose |
|---|---|---|
| `FIRNLINE_LLM_API_KEY` | (empty) | API key for the LLM endpoint |
| `FIRNLINE_LLM_MODEL` | `gpt-4.1-mini` | Model name routed through your LLM proxy |
| `TDB_ORG` / `TDB_DB` / `TDB_USER` | `admin` / `firnline` / `admin` | TerminusDB connection details |
| `TDB_BRANCH` | `main` | TerminusDB branch |
| `FIRNLINE_EXTENSIONS` | (empty) | Comma-separated extension specifiers (see `.env.example` for formats) |
| `WEBUI_PASSWORD` | (empty) | Optional UI password gate; empty = open |

See [reference/configuration.md](../reference/configuration.md) for the full environment variable reference.

## Bootstrap the schema

The bootstrap profile creates the database (if it doesn't exist), composes all schema modules (core + installed extensions), applies the schema to TerminusDB, and installs extensions into a shared overlay volume. Run it once per setup and whenever you change extensions.

**External TerminusDB:**

```bash
docker compose --profile bootstrap up bootstrap --abort-on-container-exit
```

**Bundled TerminusDB:**

```bash
# Ensure TDB_URL=http://terminusdb:6363 is set in .env
docker compose -f compose.yaml -f compose.bundled-tdb.yaml \
  --profile bootstrap up bootstrap --abort-on-container-exit
```

## Start the runtime services

**External TerminusDB:**

```bash
docker compose up -d
```

**Bundled TerminusDB:**

```bash
docker compose -f compose.yaml -f compose.bundled-tdb.yaml up -d
```

This starts:

| Service | Port | Description |
|---|---|---|
| `captured` | 8088 | Capture-ingress API daemon |
| `ingestd` | — | AI ingestion polling worker (LLM extraction + entity linking) |
| `triggerd` | — | Trigger evaluation daemon |
| `effectd` | — | Effect delivery daemon |
| `queryd` | 8087 | GraphQL read proxy + document lookup + write-tool endpoints |
| `indexed` | 8089 | Search index sidecar (SQLite + embeddings) |
| `mcpd` | 8090 | MCP server for external AI agents |
| `webui` | 3000 | Reflex WebUI |

The bundled overlay additionally starts `terminusdb` on port 6363.

## Verify the deployment

```bash
curl http://localhost:8087/healthz   # queryd
curl http://localhost:8088/healthz   # captured
curl http://localhost:8089/healthz   # indexed
curl http://localhost:8090/healthz   # mcpd
```

All return `200` with `{"status": "ok", ...}`. The WebUI is available at <http://localhost:3000>.

## Common pitfalls

- **`TDB_URL` not set**: the compose file enforces `TDB_URL` with `${TDB_URL:?}` — Docker refuses to start if it's empty. Copy `.env.example` and fill in all required values.
- **Bundled mode with wrong `TDB_URL`**: if `.env` has an external URL but you use `compose.bundled-tdb.yaml`, services will fail to connect. Set `TDB_URL=http://terminusdb:6363`.
- **LLM unreachable**: ingestd/indexed need access to `FIRNLINE_LLM_BASE_URL`. When the LLM proxy runs on the host, use `http://host.docker.internal:4000`. The `extra_hosts` configuration in `compose.yaml` makes this available inside containers.
- **Bundled TerminusDB slow to start**: the health check retries up to 30 times (5s interval). Allow ~2 minutes for the first boot.

## Related documents

- [Quickstart](quickstart.md) — first capture and query after installation
- [Configuration reference](../reference/configuration.md) — all environment variables
- [Deployment guide](../guides/deployment.md) — production deployment considerations
