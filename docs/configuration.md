# Configuration

All configuration is done via environment variables. There are no config files.
The `.env.example` in the repo root lists every variable; copy it to `.env` and
edit as needed.

## Shared TerminusDB settings

Every service inherits these from `firnline_core.settings.TdbSettings`, using
its own prefix (`CAPTURED_`, `INGESTD_`, `QUERYD_`, `TRIGGERD_`, `EFFECTD_`):

| Variable | Default | Required | Consumed by |
|---|---|---|---|
| `{PREFIX}_TDB_URL` | `http://localhost:6363` | yes | captured, ingestd, queryd, triggerd, effectd |
| `{PREFIX}_TDB_ORG` | `admin` | no | captured, ingestd, queryd, triggerd, effectd |
| `{PREFIX}_TDB_DB` | — | yes | captured, ingestd, queryd, triggerd, effectd |
| `{PREFIX}_TDB_BRANCH` | `main` | no | captured, ingestd, queryd, triggerd, effectd |
| `{PREFIX}_TDB_USER` | `admin` | no | captured, ingestd, queryd, triggerd, effectd |
| `{PREFIX}_TDB_PASSWORD` | — | yes | captured, ingestd, queryd, triggerd, indexed, effectd |

In `compose.yaml`, these are populated from the shared `TDB_*` variables
(e.g. `CAPTURED_TDB_URL: ${TDB_URL:?}`).

## LLM settings (shared across services)

| Variable | Default | Required | Consumed by |
|---|---|---|---|
| `FIRNLINE_LLM_BASE_URL` | `http://host.docker.internal:4000` | yes | ingestd, queryd |
| `FIRNLINE_LLM_API_KEY` | (empty) | no | ingestd, queryd |
| `FIRNLINE_LLM_MODEL` | `gpt-4.1-mini` | no | ingestd, queryd |

In `compose.yaml`, these are mapped to `INGESTD_LLM_BASE_URL` /
`QUERYD_LLM_BASE_URL` etc. When running services directly on the host, set
the prefixed versions instead.

## Auth tokens

| Variable | Default | Required | Consumed by |
|---|---|---|---|
| `CAPTURED_API_TOKEN` | (empty) | yes | captured |
| `QUERYD_API_TOKEN` | (empty) | yes | queryd |

Generate with `openssl rand -hex 32`.

## captured

Prefixed `CAPTURED_`.

| Variable | Default | Description |
|---|---|---|
| `CAPTURED_TDB_URL` | `http://localhost:6363` | TerminusDB base URL |
| `CAPTURED_TDB_ORG` | `admin` | TerminusDB organisation |
| `CAPTURED_TDB_DB` | `firnline` | TerminusDB database name |
| `CAPTURED_TDB_BRANCH` | `main` | TerminusDB branch |
| `CAPTURED_TDB_USER` | `admin` | TerminusDB username |
| `CAPTURED_TDB_PASSWORD` | — | TerminusDB password |
| `CAPTURED_API_TOKEN` | — | Bearer token for capture endpoints |
| `CAPTURED_LISTEN_ADDR` | `0.0.0.0:8088` | Host:port to bind |
| `CAPTURED_STRICT_PLUGINS` | `false` | Fail startup on plugin load/requirement failures |
| `CAPTURED_MAX_UPLOAD_BYTES` | `50000000` (50 MB) | Max file upload size for `/v1/capture/file` |
| `FIRNLINE_BLOB_ROOT` | — | Root directory for blob storage (captured) |

The compose file additionally uses:

| Variable | Default | Description |
|---|---|---|
| `CAPTURED_HOST_PORT` | `8088` | Host port mapped to the container's 8088 |

## ingestd

Prefixed `INGESTD_`.

| Variable | Default | Description |
|---|---|---|
| `INGESTD_TDB_URL` | `http://localhost:6363` | TerminusDB base URL |
| `INGESTD_TDB_ORG` | `admin` | TerminusDB organisation |
| `INGESTD_TDB_DB` | `firnline` | TerminusDB database name |
| `INGESTD_TDB_BRANCH` | `main` | TerminusDB branch |
| `INGESTD_TDB_USER` | `admin` | TerminusDB username |
| `INGESTD_TDB_PASSWORD` | — | TerminusDB password |
| `INGESTD_LLM_BASE_URL` | `""` | LLM API base URL |
| `INGESTD_LLM_API_KEY` | `""` | LLM API key |
| `INGESTD_LLM_MODEL` | `""` | LLM model name |
| `INGESTD_POLL_INTERVAL_SECONDS` | `60` | Seconds between poll cycles |
| `INGESTD_MAX_LLM_RETRIES` | `3` | Max retries on schema-rejection per inbox item |
| `INGESTD_DRY_RUN` | `false` | Run extraction without writing to database |
| `INGESTD_STRICT_PLUGINS` | `false` | Fail startup on plugin load/requirement failures |
| `INGESTD_LIVENESS_FILE` | `/tmp/ingestd-alive` | Path touched on each successful cycle for healthchecks |

## triggerd

Prefixed `TRIGGERD_`.

| Variable | Default | Description |
|---|---|---|
| `TRIGGERD_TDB_URL` | `http://localhost:6363` | TerminusDB base URL |
| `TRIGGERD_TDB_ORG` | `admin` | TerminusDB organisation |
| `TRIGGERD_TDB_DB` | `firnline` | TerminusDB database name |
| `TRIGGERD_TDB_BRANCH` | `main` | TerminusDB branch |
| `TRIGGERD_TDB_USER` | `admin` | TerminusDB username |
| `TRIGGERD_TDB_PASSWORD` | — | TerminusDB password |
| `TRIGGERD_POLL_INTERVAL_SECONDS` | `60` | Seconds between evaluation cycles |
| `TRIGGERD_LOOKBACK_SECONDS` | `900` | How far back to look for Trigger changes |
| `TRIGGERD_DEFAULT_TIMEZONE` | `Europe/Zurich` | Fallback timezone for date parsing |
| `TRIGGERD_DRY_RUN` | `false` | Evaluate but skip writes |
| `TRIGGERD_STRICT_PLUGINS` | `false` | Fail startup on plugin load/requirement failures |
| `TRIGGERD_LIVENESS_FILE` | `/tmp/triggerd-alive` | Path touched on each successful cycle for healthchecks |

## effectd

Prefixed `EFFECTD_`.

| Variable | Default | Description |
|---|---|---|
| `EFFECTD_TDB_URL` | `http://localhost:6363` | TerminusDB base URL |
| `EFFECTD_TDB_ORG` | `admin` | TerminusDB organisation |
| `EFFECTD_TDB_DB` | `firnline` | TerminusDB database name |
| `EFFECTD_TDB_BRANCH` | `main` | TerminusDB branch |
| `EFFECTD_TDB_USER` | `admin` | TerminusDB username |
| `EFFECTD_TDB_PASSWORD` | — | TerminusDB password |
| `EFFECTD_POLL_INTERVAL_SECONDS` | `30` | Seconds between poll cycles |
| `EFFECTD_LIVENESS_FILE` | `/tmp/effectd-alive` | Path touched on each successful cycle for healthchecks |
| `EFFECTD_DRY_RUN` | `false` | Global override: forces all executions to `skipped` |
| `EFFECTD_LEGACY_NOTIFICATION_LOOP` | `true` | Run the zero-config default notify path (nag policy renotify/expire/snooze) |
| `EFFECTD_DEFAULT_NOTIFY_EXECUTOR` | `notify:gotify` | Executor kind for the legacy notify loop |
| `EFFECTD_PLANNING_LOOKBACK` | `P7D` | ISO-8601 duration bounding the planner query window |
| `EFFECTD_MAX_EXECUTIONS_PER_CYCLE` | `50` | Max pending executions processed per poll cycle |
| `EFFECTD_DEFAULT_MAX_ATTEMPTS` | `3` | Default retry limit per execution |
| `EFFECTD_DEFAULT_RETRY_BACKOFF` | `PT1M` | Base backoff, doubled per attempt |
| `EFFECTD_DEFAULT_TIMEOUT` | `PT30S` | Default per-execution timeout |
| `EFFECTD_STRICT_PLUGINS` | `false` | Fail startup on plugin load/requirement failures |

## gotify (extension firnline-ext-gotify)

Prefixed `GOTIFY_`.

| Variable | Default | Description |
|---|---|---|
| `GOTIFY_URL` | `""` | Gotify server URL (e.g. `https://gotify.example.com`) |
| `GOTIFY_TOKEN` | `""` | Gotify app token |
| `GOTIFY_PRIORITY` | `5` | Gotify message priority (0–10, higher = more urgent) |
| `GOTIFY_TIMEOUT_SECONDS` | `10.0` | HTTP timeout for Gotify API calls |

## webhook (extension firnline-ext-webhook)

Prefixed `WEBHOOK_`.

| Variable | Default | Description |
|---|---|---|
| `WEBHOOK_DEFAULT_TOKEN` | `""` | Optional bearer token sent as `Authorization: Bearer <token>` |
| `WEBHOOK_TIMEOUT_SECONDS` | `10.0` | HTTP timeout for webhook calls |

## indexed

Prefixed `INDEXED_`.

| Variable | Default | Description |
|---|---|---|
| `INDEXED_TDB_URL` | `http://localhost:6363` | TerminusDB base URL |
| `INDEXED_TDB_ORG` | `admin` | TerminusDB organisation |
| `INDEXED_TDB_DB` | `firnline` | TerminusDB database name |
| `INDEXED_TDB_BRANCH` | `main` | TerminusDB branch |
| `INDEXED_TDB_USER` | `admin` | TerminusDB username |
| `INDEXED_TDB_PASSWORD` | — | TerminusDB password |
| `INDEXED_LLM_BASE_URL` | `""` | LLM API base URL for embeddings |
| `INDEXED_LLM_API_KEY` | `""` | LLM API key |
| `INDEXED_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model name (routed via LiteLLM) |
| `INDEXED_API_TOKEN` | `""` | Optional bearer token for `/v1/find_*` endpoints |
| `INDEXED_POLL_INTERVAL_SECONDS` | `60` | Seconds between sync cycles (commit-log poll) |
| `INDEXED_DRY_RUN` | `false` | Sync without writing to the store |
| `INDEXED_STRICT_PLUGINS` | `false` | Fail startup on plugin load/requirement failures |
| `INDEXED_MIN_CONFIDENCE` | `0.60` | Minimum score threshold for `/v1/find_*` results |
| `INDEXED_LIVENESS_FILE` | `/tmp/indexed-alive` | Path touched on each successful cycle |
| `INDEXED_DATA_DIR` | `/var/lib/firnline/index` | Directory for the sqlite index store |
| `INDEXED_LISTEN_ADDR` | `0.0.0.0:8089` | Host:port to bind |

### Consumed by ingestd (when `INGESTD_INDEXED_ENABLED=true`)

| Variable | Default | Description |
|---|---|---|
| `INGESTD_INDEXED_ENABLED` | `false` | Enable indexed-grounded entity linking |
| `INGESTD_INDEXED_URL` | `http://localhost:8089` | Base URL of the indexed service |
| `INGESTD_INDEXED_TOKEN` | `""` | Bearer token for indexed endpoints |
| `INGESTD_INDEXED_MIN_CONFIDENCE` | `0.85` | Auto-accept threshold for entity linking matches |
| `INGESTD_INDEXED_TIMEOUT_SECONDS` | `10.0` | HTTP timeout for indexed calls |

### Consumed by queryd (when `QUERYD_INDEXED_ENABLED=true`)

| Variable | Default | Description |
|---|---|---|
| `QUERYD_INDEXED_ENABLED` | `false` | Enable `find_entity`/`find_class`/`find_field` tools |
| `QUERYD_INDEXED_URL` | `http://localhost:8089` | Base URL of the indexed service |
| `QUERYD_INDEXED_TOKEN` | `""` | Bearer token for indexed endpoints |
| `QUERYD_INDEXED_MIN_CONFIDENCE` | `0.60` | Minimum score for candidates shown to the agent |
| `QUERYD_INDEXED_TIMEOUT_SECONDS` | `10.0` | HTTP timeout for indexed calls |

The compose file additionally uses:

| Variable | Default | Description |
|---|---|---|
| `INDEXED_HOST_PORT` | `8089` | Host port mapped to the container's 8089 |
| `INDEXED_URL` | `http://indexed:8089` | Service URL used by ingestd/queryd |

## queryd

Prefixed `QUERYD_`.

| Variable | Default | Description |
|---|---|---|
| `QUERYD_TDB_URL` | `http://localhost:6363` | TerminusDB base URL |
| `QUERYD_TDB_ORG` | `admin` | TerminusDB organisation |
| `QUERYD_TDB_DB` | `firnline` | TerminusDB database name |
| `QUERYD_TDB_BRANCH` | `main` | TerminusDB branch |
| `QUERYD_TDB_USER` | `admin` | TerminusDB username |
| `QUERYD_TDB_PASSWORD` | — | TerminusDB password |
| `QUERYD_API_TOKEN` | — | Bearer token for `/v1/chat` and structured API endpoints |
| `QUERYD_LLM_BASE_URL` | — | LLM API base URL |
| `QUERYD_LLM_API_KEY` | — | LLM API key |
| `QUERYD_LLM_MODEL` | — | LLM model name |
| `QUERYD_ENABLE_WRITES` | `false` | Gate write-tool plugins |
| `QUERYD_STRICT_PLUGINS` | `false` | Fail startup on plugin load/requirement failures |
| `QUERYD_MAX_TOOL_ITERATIONS` | `8` | Max tool calls per request |
| `QUERYD_REQUEST_TIMEOUT_SECONDS` | `60` | Total request timeout |
| `QUERYD_LISTEN_ADDR` | `0.0.0.0:8087` | Host:port to bind |
| `QUERYD_CORS_ORIGINS` | `[]` | Comma-separated CORS origins |

### Structured API endpoints (bearer-authed)

Beyond `/v1/chat`, queryd serves:

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/schema` | Rendered schema summary |
| `GET` | `/v1/schema/introspection` | Raw GraphQL introspection JSON |
| `GET` | `/v1/modules` | SchemaModule registry docs |
| `GET` | `/v1/documents/{iri}` | Fetch a single document by IRI |
| `POST` | `/v1/graphql` | Read-only GraphQL query (mutations rejected) |
| `POST` | `/v1/find/entity` | Semantic entity search (requires indexed) |
| `POST` | `/v1/find/class` | Semantic class search (requires indexed) |
| `POST` | `/v1/find/field` | Semantic field search (requires indexed) |

The compose file additionally uses:

| Variable | Default | Description |
|---|---|---|
| `QUERYD_HOST_PORT` | `8087` | Host port mapped to the container's 8087 |

## Extension management

| Variable | Default | Description |
|---|---|---|
| `FIRNLINE_EXTENSIONS` | (empty) | Comma-separated extension specifiers (PyPI, Git URL, or wheel filename) |
| `FIRNLINE_EXTENSIONS_PURGE` | `false` | Set `true` to wipe the overlay before reinstalling |
| `FIRNLINE_EXTENSIONS_INSTALL` | `false` | Set `true` in the bootstrap container to trigger installation |

Accepted specifier formats in `FIRNLINE_EXTENSIONS`:

- **PyPI name**: `firnline_ext_people>=0.1.0`
- **Git URL**: `git+https://github.com/user/firnline-ext-foo.git`
- **Wheel filename**: `firnline_ext_people-0.1.0-py3-none-any.whl` (resolved against `/extensions/` in the image)

First-party extension wheels are baked into service images at build time.

## webui

Prefixed `WEBUI_`.

| Variable | Default | Description |
|---|---|---|
| `WEBUI_CAPTURED_URL` | `http://captured:8088` | Base URL for the captured service |
| `WEBUI_CAPTURED_API_TOKEN` | (empty) | Bearer token for captured endpoints (server-side, never exposed to browser) |
| `WEBUI_QUERYD_URL` | `http://queryd:8087` | Base URL for the queryd service |
| `WEBUI_QUERYD_API_TOKEN` | (empty) | Bearer token for queryd `/healthz` (server-side) |
| `WEBUI_INDEXED_URL` | `http://indexed:8089` | Base URL for the indexed service |
| `WEBUI_INDEXED_API_TOKEN` | (empty) | Bearer token for indexed endpoints (reserved) |
| `WEBUI_TDB_URL` | `http://terminusdb:6363` | TerminusDB base URL |
| `WEBUI_TDB_ORG` | `admin` | TerminusDB organisation |
| `WEBUI_TDB_DB` | `firnline` | TerminusDB database name |
| `WEBUI_TDB_BRANCH` | `main` | TerminusDB branch |
| `WEBUI_TDB_USER` | `admin` | TerminusDB username |
| `WEBUI_TDB_PASSWORD` | (empty) | TerminusDB password |
| `WEBUI_PASSWORD` | (empty) | Optional UI password gate; empty = open |
| `WEBUI_REQUEST_TIMEOUT_SECONDS` | `30.0` | HTTP timeout for all backend calls |

The compose file additionally uses:

| Variable | Default | Description |
|---|---|---|
| `WEBUI_HOST_PORT` | `3000` | Host port mapped to the container's port 3000 |
| `WEBUI_API_URL` | `http://localhost:3000` | Browser-facing URL (maps to `REFLEX_API_URL` — must be absolute) |

## mcpd (Model Context Protocol server)

Prefixed `MCPD_`.

mcpd exposes firnline to external AI agents via MCP (streamable HTTP). It
talks to queryd and captured over HTTP — no direct database access.

| Variable | Default | Description |
|---|---|---|
| `MCPD_HOST` | `0.0.0.0` | Host to bind |
| `MCPD_PORT` | `8090` | Port to bind |
| `MCPD_QUERYD_URL` | `http://queryd:8087` | Base URL of the queryd service |
| `MCPD_QUERYD_TOKEN` | — | Bearer token for queryd endpoints |
| `MCPD_CAPTURED_URL` | `http://captured:8088` | Base URL of the captured service |
| `MCPD_CAPTURED_TOKEN` | — | Bearer token for captured endpoints |

### MCP tools

| Tool | Backed by |
|---|---|
| `graphql_query` | queryd `POST /v1/graphql` |
| `get_document` | queryd `GET /v1/documents/{iri}` |
| `find_entity` | queryd `POST /v1/find/entity` |
| `find_class` | queryd `POST /v1/find/class` |
| `find_field` | queryd `POST /v1/find/field` |
| `get_schema` | queryd `GET /v1/schema` |
| `list_modules` | queryd `GET /v1/modules` |
| `capture` | captured `POST /v1/capture/note` |

### MCP resources

| URI | Backed by |
|---|---|
| `firnline://schema` | queryd `GET /v1/schema` |
| `firnline://schema/introspection` | queryd `GET /v1/schema/introspection` |
| `firnline://modules` | queryd `GET /v1/modules` |

For full details see [docs/mcpd.md](mcpd.md).

## Bundled TerminusDB overlay

| Variable | Default | Description |
|---|---|---|
| `TDB_HOST_PORT` | `6363` | Host port mapped to bundled TerminusDB's 6363 |

> When using the bundled TDB overlay, set `TDB_URL=http://terminusdb:6363` in
> `.env` — the container name is hardcoded in `compose.bundled-tdb.yaml`.
