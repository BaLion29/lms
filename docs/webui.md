# WebUI

A Reflex 0.9.x web dashboard for firnline. It browses TerminusDB schemas and
documents, inspects capture / queryd / indexed services, captures notes and
files, and provides an optional password gate — all without hardcoding any
domain knowledge.

| Page | Route | Description |
|---|---|---|
| Dashboard | `/` | Greeting, per-service health summary (captured/queryd/indexed), quick-capture link, schema module chips. |
| Capture | `/capture` | Submit notes via `POST /v1/capture/note` and upload files via `POST /v1/capture/file`. Handler names from captured `/healthz` are shown. |
| Inbox | `/inbox` | Lists `Captured` documents — rendered with status badges, filter chips, and a JSON detail drawer. |
| Automations | `/automations` | Read-only listing of `TriggerFiring` and `ActionExecution` documents with status filters, colored status badges, and a JSON detail drawer. Degrades gracefully when the triggers/actions schema modules are not installed. |
| Browse | `/browse` | Classes grouped by `SchemaModule.exports`. Click a class → `/browse/[class_name]` paginated table with field-aware display and detail drawer. |
| Health | `/health` | Full health detail per service: status, version, TerminusDB connectivity, active handler/plugin lists, blob-store availability. Includes mcpd and indexed store/poller fields. |
| Modules | `/modules` | `SchemaModule` registry table (name, version, description, exports, deps) plus active plugins by service (from each service's `/healthz`). |
| Login | `/login` | Centered password-gate card (only active when `WEBUI_PASSWORD` is set). |

## Plug-and-play mechanism

The UI is **introspection-driven**: it discovers everything at runtime by
querying the TerminusDB schema, the `SchemaModule` registry, and each
service's `/healthz` endpoint. Any current or future firnline extension
automatically appears with **zero UI code changes**.

| Data need | Introspection source |
|---|---|
| Available capture kinds + handlers | `GET /healthz` on captured → `handlers` field |
| Browsable document classes | `TdbClient.get_schema()` → non-abstract, non-subdocument `Class` entries |
| Class grouping by module | `TdbClient.get_documents("SchemaModule")` → `exports` field |
| Active plugins per service | `GET /healthz` on each service → `plugins` field |
| Inbox classes | `Captured` class from schema |

This is a deliberate design choice — extensions define their schema,
handlers, and plugins via the existing firnline-core entry-point protocols
(see [Extensions](extensions.md)); the WebUI picks them up with no new
protocol. A future `firnline.webui.pages` entry-point protocol for custom
pages is **deliberately deferred** and could be added later if needed.

## Configuration

All environment variables are prefixed with `WEBUI_`. The compose file
additionally uses `WEBUI_HOST_PORT`, `WEBUI_API_URL`, and `REFLEX_API_URL`.

| Variable | Default | Description |
|---|---|---|
| `WEBUI_CAPTURED_URL` | `http://apid:8080` | Base URL for the captured service |
| `WEBUI_CAPTURED_API_TOKEN` | (empty) | Bearer token for captured endpoints — **server-side only, never sent to the browser** |
| `WEBUI_QUERYD_URL` | `http://apid:8080` | Base URL for the queryd service |
| `WEBUI_QUERYD_API_TOKEN` | (empty) | Bearer token for queryd `/healthz` — server-side only |
| `WEBUI_INDEXED_URL` | `http://apid:8080` | Base URL for the indexed service |
| `WEBUI_INDEXED_API_TOKEN` | (empty) | Bearer token for indexed `/healthz` — server-side only |
| `WEBUI_MCPD_URL` | `http://apid:8080/mcp` | Base URL for the mcpd service — mounted at /mcp on apid (healthz monitoring) |
| `WEBUI_TDB_URL` | `http://terminusdb:6363` | TerminusDB base URL |
| `WEBUI_TDB_ORG` | `admin` | TerminusDB organisation |
| `WEBUI_TDB_DB` | `firnline` | TerminusDB database name |
| `WEBUI_TDB_BRANCH` | `main` | TerminusDB branch |
| `WEBUI_TDB_USER` | `admin` | TerminusDB username |
| `WEBUI_TDB_PASSWORD` | (empty) | TerminusDB password |
| `WEBUI_PASSWORD` | (empty) | Optional UI password gate (empty = disabled, open for LAN access) |
| `WEBUI_REQUEST_TIMEOUT_SECONDS` | `30.0` | HTTP timeout for all backend service calls |

Compose-level variables (not consumed by the Python process, but by
`compose.yaml` / Reflex):

| Variable | Default | Description |
|---|---|---|
| `WEBUI_HOST_PORT` | `3000` | Host port mapped to the container's port 3000 |
| `WEBUI_API_URL` | `http://localhost:3000` | Maps to `REFLEX_API_URL` — set to the browser-facing URL (must be absolute) |
| `REFLEX_API_URL` | `http://localhost:3000` | Reflex frontend API URL (must be absolute — Reflex parses it with `new URL()`) |

## Authentication

**Token proxying** — `WEBUI_CAPTURED_API_TOKEN` and `WEBUI_QUERYD_API_TOKEN`
are injected into HTTP headers by the Reflex backend server-side. Tokens are
**never exposed to the browser** JavaScript runtime.

**Optional password gate** — when `WEBUI_PASSWORD` is non-empty, every data
page redirects unauthenticated visitors to `/login`. The login form validates
the password server-side and sets an `firnline_webui_session` cookie (HMAC‑SHA256
derived from the password, 30‑day max age). Logging out clears the cookie.
When `WEBUI_PASSWORD` is empty (the default), all pages are open — intended
for LAN‑only deployments where access is controlled at the network layer.

## Deployment

### Docker Compose

The `webui` service is already defined in `compose.yaml`:

```bash
docker compose up -d webui
```

The service depends on `captured` and `queryd` (service_started) and exposes
port `${WEBUI_HOST_PORT:-3000}`. All `WEBUI_*` env vars are populated from the
shared `.env` file. `REFLEX_API_URL` defaults to `http://localhost:3000` —
set `WEBUI_API_URL` in `.env` to the hostname visible in the browser for remote access.

**First boot** takes **~30–60 seconds** — Reflex compiles the Next.js
frontend at container startup. The healthcheck uses `start_period: 120s` to
allow plenty of time.

When all services are running (`docker compose up -d`), the UI is available at
<http://localhost:3000>.

### Local development

```bash
cd services/webui
uv run reflex run
```

This starts the Reflex dev server on port 3000 (frontend) and 8000 (backend).
Set `WEBUI_*` environment variables to point at your running services. See the
[service README](../services/webui/README.md) for more details.

## Limitations (v1)

- **Read-only browse** — the UI displays documents but has no edit/create forms
  (outside of capture).
- **No chat page** — the conversational queryd agent is not exposed in the UI yet.
- **Single shared password** — the password gate uses one shared password with
  no per-user accounts or roles.
- **Frontend compiles at boot** — container startup takes 30–60s while Reflex
  builds the Next.js frontend; subsequent requests are fast.
