# Configuration

Canonical environment-variable reference for firnline v0.1.0-alpha. All
configuration is done via environment variables — there are no config files.
Copy `.env.example` to `.env` and edit as needed.

## Shared TerminusDB settings

Every service subclasses `firnline_core.settings.TdbSettings`, using its
own prefix (`CAPTURED_`, `INGESTD_`, `QUERYD_`, `TRIGGERD_`, `EFFECTD_`,
`INDEXED_`, `WEBUI_`).

The `tdb_db` and `tdb_password` fields have no default and **must** be set.

| Name | Default | Description |
|---|---|---|
| `{PREFIX}_TDB_URL` | `http://localhost:6363` | TerminusDB base URL |
| `{PREFIX}_TDB_ORG` | `admin` | TerminusDB organisation |
| `{PREFIX}_TDB_DB` | — (required) | TerminusDB database name |
| `{PREFIX}_TDB_BRANCH` | `main` | TerminusDB branch |
| `{PREFIX}_TDB_USER` | `admin` | TerminusDB username |
| `{PREFIX}_TDB_PASSWORD` | — (required) | TerminusDB password |

In `compose.yaml`, these are populated from shared `TDB_*` variables
(e.g. `CAPTURED_TDB_URL: ${TDB_URL:?}`).

## LLM settings

Shared `FIRNLINE_LLM_*` variables are mapped to per-service prefixes in
`compose.yaml`. When running services directly on the host, set the
prefixed versions instead.

| Name | Default | Description | Consumed by |
|---|---|---|---|
| `FIRNLINE_LLM_BASE_URL` | `http://host.docker.internal:4000` | LLM API base URL (LiteLLM proxy) | ingestd, indexed |
| `FIRNLINE_LLM_API_KEY` | (empty) | LLM API key | ingestd, indexed |
| `FIRNLINE_LLM_MODEL` | `gpt-4.1-mini` | LLM model name | ingestd |

The per-service forms are `INGESTD_LLM_BASE_URL`, `INGESTD_LLM_API_KEY`,
`INGESTD_LLM_MODEL`, `INDEXED_LLM_BASE_URL`, `INDEXED_LLM_API_KEY`, and
`INDEXED_EMBEDDING_MODEL`.

## Auth tokens

Generate with `openssl rand -hex 32`.

| Name | Default | Description | Consumed by |
|---|---|---|---|
| `CAPTURED_API_TOKEN` | — (required) | Bearer token for capture endpoints | captured |
| `QUERYD_API_TOKEN` | — (required) | Bearer token for all queryd API endpoints | queryd |

## Blob storage

| Name | Default | Description |
|---|---|---|
| `FIRNLINE_BLOB_ROOT` | — | Root directory for content-addressed blob storage (captured, queryd) |

## captured

Prefix `CAPTURED_`. Inherits TDB settings.

| Name | Default | Description |
|---|---|---|
| `CAPTURED_API_TOKEN` | — (required) | Bearer token for capture endpoints |
| `CAPTURED_LISTEN_ADDR` | `0.0.0.0:8088` | Host:port to bind |
| `CAPTURED_STRICT_PLUGINS` | `false` | Fail startup on plugin load/requirement failures |
| `CAPTURED_MAX_UPLOAD_BYTES` | `50000000` | Max file upload size for `/v1/capture/file` (50 MB) |

Compose-level additional variables:

| Name | Default | Description |
|---|---|---|
| `CAPTURED_HOST_PORT` | `8088` | Host port mapped to container port 8088 |

## ingestd

Prefix `INGESTD_`. Inherits TDB settings.

| Name | Default | Description |
|---|---|---|
| `INGESTD_LLM_BASE_URL` | `""` | LLM API base URL |
| `INGESTD_LLM_API_KEY` | `""` | LLM API key |
| `INGESTD_LLM_MODEL` | `""` | LLM model name |
| `INGESTD_POLL_INTERVAL_SECONDS` | `60` | Seconds between poll cycles |
| `INGESTD_MAX_LLM_RETRIES` | `3` | Max retries on schema-rejection per inbox item |
| `INGESTD_DRY_RUN` | `false` | Extract without writing to database |
| `INGESTD_STRICT_PLUGINS` | `false` | Fail startup on plugin load/requirement failures |
| `INGESTD_LIVENESS_FILE` | `/tmp/ingestd-alive` | Path touched on each successful cycle |

### Consumed when `INGESTD_INDEXED_ENABLED=true`

| Name | Default | Description |
|---|---|---|
| `INGESTD_INDEXED_ENABLED` | `false` | Enable indexed-grounded entity linking |
| `INGESTD_INDEXED_URL` | `http://localhost:8089` | Base URL of the indexed service |
| `INGESTD_INDEXED_TOKEN` | `""` | Bearer token for indexed endpoints |
| `INGESTD_INDEXED_MIN_CONFIDENCE` | `0.85` | Auto-accept threshold for entity linking matches |
| `INGESTD_INDEXED_TIMEOUT_SECONDS` | `10.0` | HTTP timeout for indexed calls |

## triggerd

Prefix `TRIGGERD_`. Inherits TDB settings.

| Name | Default | Description |
|---|---|---|
| `TRIGGERD_POLL_INTERVAL_SECONDS` | `60` | Seconds between evaluation cycles |
| `TRIGGERD_LOOKBACK_SECONDS` | `900` | How far back to look for Trigger changes |
| `TRIGGERD_DEFAULT_TIMEZONE` | `Europe/Zurich` | Fallback timezone for date parsing |
| `TRIGGERD_DRY_RUN` | `false` | Evaluate but skip writes |
| `TRIGGERD_STRICT_PLUGINS` | `false` | Fail startup on plugin load/requirement failures |
| `TRIGGERD_LIVENESS_FILE` | `/tmp/triggerd-alive` | Path touched on each successful cycle |
| `TRIGGERD_STATE_FILE` | `/tmp/triggerd-state.json` | File to persist last-seen commit ID across restarts |

## effectd

Prefix `EFFECTD_`. Inherits TDB settings.

| Name | Default | Description |
|---|---|---|
| `EFFECTD_POLL_INTERVAL_SECONDS` | `30` | Seconds between poll cycles |
| `EFFECTD_LIVENESS_FILE` | `/tmp/effectd-alive` | Path touched on each successful cycle |
| `EFFECTD_DRY_RUN` | `false` | Global override: forces all executions to `skipped` |
| `EFFECTD_LEGACY_NOTIFICATION_LOOP` | `true` | Run the zero-config default notify path (nag policy renotify/expire/snooze) |
| `EFFECTD_DEFAULT_NOTIFY_EXECUTOR` | `notify:gotify` | Executor kind for the legacy notify loop |
| `EFFECTD_PLANNING_LOOKBACK` | `P7D` | ISO-8601 duration bounding the planner query window |
| `EFFECTD_MAX_EXECUTIONS_PER_CYCLE` | `50` | Max pending executions processed per poll cycle |
| `EFFECTD_DEFAULT_MAX_ATTEMPTS` | `3` | Default retry limit per execution |
| `EFFECTD_DEFAULT_RETRY_BACKOFF` | `PT1M` | Base backoff, doubled per attempt |
| `EFFECTD_DEFAULT_TIMEOUT` | `PT30S` | Default per-execution timeout |
| `EFFECTD_STRICT_PLUGINS` | `false` | Fail startup on plugin load/requirement failures |

## indexed

Prefix `INDEXED_`. Inherits TDB settings.

| Name | Default | Description |
|---|---|---|
| `INDEXED_LLM_BASE_URL` | `""` | LLM API base URL for embeddings |
| `INDEXED_LLM_API_KEY` | `""` | LLM API key |
| `INDEXED_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model name (routed via LiteLLM) |
| `INDEXED_API_TOKEN` | `""` | Optional bearer token for `/v1/find_*` endpoints |
| `INDEXED_POLL_INTERVAL_SECONDS` | `60` | Seconds between sync cycles |
| `INDEXED_DRY_RUN` | `false` | Sync without writing to the store |
| `INDEXED_STRICT_PLUGINS` | `false` | Fail startup on plugin load/requirement failures |
| `INDEXED_MIN_CONFIDENCE` | `0.60` | Minimum score threshold for `/v1/find_*` results |
| `INDEXED_LIVENESS_FILE` | `/tmp/indexed-alive` | Path touched on each successful cycle |
| `INDEXED_DATA_DIR` | `/var/lib/firnline/index` | Directory for the sqlite index store |
| `INDEXED_LISTEN_ADDR` | `0.0.0.0:8089` | Host:port to bind |

Compose-level additional variables:

| Name | Default | Description |
|---|---|---|
| `INDEXED_HOST_PORT` | `8089` | Host port mapped to container port 8089 |
| `INDEXED_URL` | `http://indexed:8089` | Service URL used by ingestd/queryd |

## queryd

Prefix `QUERYD_`. Inherits TDB settings.

| Name | Default | Description |
|---|---|---|
| `QUERYD_API_TOKEN` | — (required) | Bearer token for all API endpoints |
| `QUERYD_ENABLE_WRITES` | `false` | Gate write-tool plugins; exposes `GET /v1/tools` and `POST /v1/tools/{name}` |
| `QUERYD_STRICT_PLUGINS` | `false` | Fail startup on plugin load/requirement failures |
| `QUERYD_REQUEST_TIMEOUT_SECONDS` | `60` | Total request timeout |
| `QUERYD_LISTEN_ADDR` | `0.0.0.0:8087` | Host:port to bind |
| `QUERYD_CORS_ORIGINS` | `[]` | Comma-separated CORS origins |

### Consumed when `QUERYD_INDEXED_ENABLED=true`

| Name | Default | Description |
|---|---|---|
| `QUERYD_INDEXED_ENABLED` | `false` | Enable `find_entity`/`find_class`/`find_field` endpoints |
| `QUERYD_INDEXED_URL` | `http://localhost:8089` | Base URL of the indexed service |
| `QUERYD_INDEXED_TOKEN` | `""` | Bearer token for indexed endpoints |
| `QUERYD_INDEXED_MIN_CONFIDENCE` | `0.60` | Minimum score for candidates |
| `QUERYD_INDEXED_TIMEOUT_SECONDS` | `10.0` | HTTP timeout for indexed calls |

See [queryd API reference](api/queryd.md) for endpoint details.

Compose-level additional variables:

| Name | Default | Description |
|---|---|---|
| `QUERYD_HOST_PORT` | `8087` | Host port mapped to container port 8087 |

## webui

Prefix `WEBUI_`.

| Name | Default | Description |
|---|---|---|
| `WEBUI_CAPTURED_URL` | `http://captured:8088` | Base URL for the captured service |
| `WEBUI_CAPTURED_API_TOKEN` | (empty) | Bearer token for captured endpoints (server-side) |
| `WEBUI_QUERYD_URL` | `http://queryd:8087` | Base URL for the queryd service |
| `WEBUI_QUERYD_API_TOKEN` | (empty) | Bearer token for queryd endpoints (server-side) |
| `WEBUI_INDEXED_URL` | `http://indexed:8089` | Base URL for the indexed service |
| `WEBUI_INDEXED_API_TOKEN` | (empty) | Bearer token for indexed endpoints |
| `WEBUI_MCPD_URL` | `http://mcpd:8090` | Base URL for the mcpd service |
| `WEBUI_TDB_URL` | `http://terminusdb:6363` | TerminusDB base URL |
| `WEBUI_TDB_ORG` | `admin` | TerminusDB organisation |
| `WEBUI_TDB_DB` | `firnline` | TerminusDB database name |
| `WEBUI_TDB_BRANCH` | `main` | TerminusDB branch |
| `WEBUI_TDB_USER` | `admin` | TerminusDB username |
| `WEBUI_TDB_PASSWORD` | (empty) | TerminusDB password |
| `WEBUI_PASSWORD` | (empty) | Optional UI password gate; empty = open |
| `WEBUI_REQUEST_TIMEOUT_SECONDS` | `30.0` | HTTP timeout for all backend calls |

Compose-level additional variables:

| Name | Default | Description |
|---|---|---|
| `WEBUI_HOST_PORT` | `3000` | Host port mapped to container port 3000 |
| `WEBUI_API_URL` | `http://localhost:3000` | Browser-facing URL (maps to `REFLEX_API_URL`) |

## mcpd

Prefix `MCPD_`. mcpd exposes firnline to external AI agents via MCP (streamable HTTP).
It talks to queryd and captured over HTTP — no direct database access.

| Name | Default | Description |
|---|---|---|
| `MCPD_HOST` | `0.0.0.0` | Host to bind |
| `MCPD_PORT` | `8090` | Port to bind |
| `MCPD_QUERYD_URL` | `http://localhost:8087` | Base URL of the queryd service |
| `MCPD_QUERYD_TOKEN` | `""` | Bearer token for queryd endpoints |
| `MCPD_CAPTURED_URL` | `http://localhost:8088` | Base URL of the captured service |
| `MCPD_CAPTURED_TOKEN` | `""` | Bearer token for captured endpoints |
| `MCPD_REQUEST_TIMEOUT_SECONDS` | `30.0` | HTTP timeout for backend calls |
| `MCPD_ENABLE_QUERYD_TOOLS` | `true` | Register queryd write tools as dynamic MCP tools at startup |

See [mcpd API reference](api/mcpd.md) for full MCP tool/resource listing.

## `firnline-schema`

The schema CLI reads the TerminusDB password from this variable when
`--tdb-password` is not passed on the command line.

| Name | Default | Description |
|---|---|---|
| `FIRNLINE_SCHEMA_TDB_PASSWORD` | (empty) | TerminusDB password for firnline-schema CLI commands that talk to TDB |

See [CLI reference](cli.md) for `firnline-schema` subcommands.

## gotify extension (`firnline-ext-gotify`)

Prefix `GOTIFY_`.

| Name | Default | Description |
|---|---|---|
| `GOTIFY_URL` | `""` | Gotify server URL |
| `GOTIFY_TOKEN` | `""` | Gotify app token |
| `GOTIFY_PRIORITY` | `5` | Message priority (0–10) |
| `GOTIFY_TIMEOUT_SECONDS` | `10.0` | HTTP timeout for Gotify API calls |

## webhook extension (`firnline-ext-webhook`)

Prefix `WEBHOOK_`.

| Name | Default | Description |
|---|---|---|
| `WEBHOOK_DEFAULT_TOKEN` | `""` | Optional bearer token sent as `Authorization: Bearer <token>` |
| `WEBHOOK_TIMEOUT_SECONDS` | `10.0` | HTTP timeout for webhook calls |

## Extension management

| Name | Default | Description |
|---|---|---|
| `FIRNLINE_EXTENSIONS` | (empty) | Comma-separated extension specifiers (PyPI name, Git URL, or wheel filename) |
| `FIRNLINE_EXTENSIONS_PURGE` | `false` | Set `true` to wipe overlay before reinstalling |
| `FIRNLINE_EXTENSIONS_INSTALL` | `false` | Set `true` in the bootstrap container to trigger installation |

Accepted specifier formats in `FIRNLINE_EXTENSIONS`:
- **PyPI name**: `firnline_ext_people>=0.1.0`
- **Git URL**: `git+https://github.com/user/firnline-ext-foo.git`
- **Wheel filename**: `firnline_ext_people-0.1.0-py3-none-any.whl` (resolved against `/extensions/` in the image)

## Bundled TerminusDB overlay

| Name | Default | Description |
|---|---|---|
| `TDB_HOST_PORT` | `6363` | Host port mapped to bundled TerminusDB's 6363 |

> When using the bundled TDB overlay, set `TDB_URL=http://terminusdb:6363` in
> `.env` — the container name is hardcoded in `compose.bundled-tdb.yaml`.

## Related documents

- [CLI reference](cli.md)
- [Getting started: Installation](../getting-started/installation.md)
- [Guides: Deployment](../guides/deployment.md)
