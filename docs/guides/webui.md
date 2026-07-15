# WebUI

## Purpose

How to deploy, configure, and use the firnline Reflex dashboard. The WebUI
provides capture, inbox browsing, schema-aware document browsing, health
monitoring, commit log history, calendar views, and automation inspection —
all driven by runtime introspection.

## What the UI provides

The dashboard is available at <http://localhost:3000> when the stack is
running. All 10 pages are fully implemented:

| Page | Route | Description |
|---|---|---|
| Dashboard | `/` | Greeting, per-service health summary (captured/queryd/indexed), quick-capture link, schema module chips. |
| Capture | `/capture` | Submit notes via `POST /v1/capture/note` and upload files via `POST /v1/capture/file`. Handler names from captured `/healthz` are shown. |
| Inbox | `/inbox` | Lists `Captured` documents — rendered with status badges, filter chips, and a JSON detail drawer. |
| Automations | `/automations` | Read-only listing of `TriggerFiring` and `ActionExecution` documents with status filters, colored status badges, and a JSON detail drawer. Degrades gracefully when the triggers/actions schema modules are not installed. |
| Browse | `/browse` | Classes grouped by `SchemaModule.exports`. Click a class → `/browse/[class_name]` paginated table with field-aware display and detail drawer. |
| Health | `/health` | Full health detail per service: status, version, TerminusDB connectivity, active handler/plugin lists, blob-store availability. Includes mcpd and indexed store/poller fields. |
| History | `/history` | Paginated commit log browser with per-commit change lists (inserted/updated/deleted documents) and a JSON detail drawer for inspecting individual documents. |
| Calendar | `/calendar` | Schema-introspection-driven calendar with Month/Week/Day views showing anchored documents (Events, Tasks). Select which document classes to display via toggle chips. |
| Modules | `/modules` | `SchemaModule` registry table (name, version, description, exports, deps) plus active plugins by service (from each service's `/healthz`). |
| Login | `/login` | Centered password-gate card (only active when `WEBUI_PASSWORD` is set). |

## Introspection-driven plug-and-play

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

For the architecture behind this design, see
[../concepts/architecture.md](../concepts/architecture.md).

## Authentication

**Token proxying** — `WEBUI_CAPTURED_API_TOKEN` and `WEBUI_QUERYD_API_TOKEN`
are injected into HTTP headers by the Reflex backend server-side. Tokens are
**never exposed to the browser** JavaScript runtime. Indexed token
(`WEBUI_INDEXED_API_TOKEN`) falls back to `INDEXED_API_TOKEN` when unset.

**Optional password gate** — when `WEBUI_PASSWORD` is non-empty, every data
page redirects unauthenticated visitors to `/login`. The login form validates
the password server-side and sets an `firnline_webui_session` cookie
(HMAC-SHA256 derived from the password, 30-day max age). Logging out clears
the cookie.

When `WEBUI_PASSWORD` is empty (the default), all pages are open — intended
for LAN-only deployments where access is controlled at the network layer.

## Docker Compose deployment

The `webui` service is defined in `compose.yaml`:

```bash
docker compose up -d webui
```

The service depends on `bootstrap` (completed) and `apid` (started) and exposes
port `${WEBUI_HOST_PORT:-3000}`. All `WEBUI_*` env vars are populated from the
shared `.env` file.

The code-verified defaults for service URLs point to the `apid` container:

- `WEBUI_CAPTURED_URL` → `http://apid:8080`
- `WEBUI_QUERYD_URL` → `http://apid:8080`
- `WEBUI_INDEXED_URL` → `http://apid:8080`
- `WEBUI_MCPD_URL` → `http://apid:8080/mcp`

**First boot** takes **~30–60 seconds** — Reflex compiles the Next.js frontend
at container startup. The healthcheck uses `start_period: 120s` to allow
plenty of time.

For the complete list of `WEBUI_*` environment variables and their defaults,
see [../reference/configuration.md](../reference/configuration.md).

## Local development

```bash
cd services/webui
uv run reflex run
```

This starts the Reflex dev server on port 3000 (frontend) and 8000 (backend).
Set `WEBUI_*` environment variables to point at your running services.

## Current limitations

- **Read-only browse** — the UI displays documents but has no edit/create forms
  (outside of capture).
- **No chat page** — the conversational queryd agent is not exposed in the UI yet.
- **Single shared password** — the password gate uses one shared password with
  no per-user accounts or roles.
- **Frontend compiles at boot** — container startup takes 30–60s while Reflex
  builds the Next.js frontend; subsequent requests are fast.

## Related documents

- [../reference/configuration.md](../reference/configuration.md) — full `WEBUI_*` environment variable reference
- [Deployment](deployment.md) — full-stack Docker Compose deployment
- [../concepts/architecture.md](../concepts/architecture.md) — introspection mechanism and plugin system
- [Automations](automations.md) — using the `/automations` page with triggers and actions
