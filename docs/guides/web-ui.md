# WebUI

The Reflex 0.9.x web dashboard for firnline. It browses TerminusDB schemas and documents, inspects service health, captures notes and files, and provides an optional password gate — all without hardcoding any domain knowledge.

## Pages

The sidebar provides access to all pages. The Login page is separate (redirected when `WEBUI_PASSWORD` is set).

| Page | Route | Description |
|---|---|---|
| Dashboard | `/` | Greeting, per-service health summary (captured/queryd/indexed), quick-capture link, schema module chips |
| Capture | `/capture` | Submit notes via `POST /v1/capture/note` and upload files via `POST /v1/capture/file`. Handler names from captured `/healthz` are shown |
| Inbox | `/inbox` | Lists `Captured` documents with status badges, filter chips, and a JSON detail drawer |
| Automations | `/automations` | Read-only listing of `TriggerFiring` and `ActionExecution` documents with status filters, colored status badges, and a JSON detail drawer. Degrades gracefully when the triggers/actions schema modules are not installed |
| Browse | `/browse` | Classes grouped by `SchemaModule.exports`. Click a class → `/browse/[class_name]` paginated table with field-aware display and detail drawer |
| Calendar | `/calendar` | Month/Week/Day calendar views driven by schema introspection. Filter by class and click entries for a JSON detail drawer |
| Health | `/health` | Full health detail per service: status, version, TerminusDB connectivity, active handler/plugin lists, blob-store availability. Includes mcpd and indexed store/poller fields |
| Modules | `/modules` | `SchemaModule` registry table (name, version, description, exports, deps) plus active plugins per service (from each service's `/healthz`) |
| Login | `/login` | Centered password-gate card (only active when `WEBUI_PASSWORD` is set) |

## Plug-and-play introspection

The UI is **introspection-driven**: it discovers everything at runtime by querying the TerminusDB schema, the `SchemaModule` registry, and each service's `/healthz` endpoint. Any current or future firnline extension automatically appears with **zero UI code changes**.

| Data need | Introspection source |
|---|---|
| Available capture kinds + handlers | `GET /healthz` on captured → `handlers` field |
| Browsable document classes | `TdbClient.get_schema()` → non-abstract, non-subdocument `Class` entries |
| Class grouping by module | `TdbClient.get_documents("SchemaModule")` → `exports` field |
| Active plugins per service | `GET /healthz` on each service → `plugins` field |
| Inbox classes | `Captured` class from schema |
| Calendarable classes | Schema introspection for classes with date/time fields |

## Authentication

**Token proxying** — `WEBUI_CAPTURED_API_TOKEN` and `WEBUI_QUERYD_API_TOKEN` are injected into HTTP headers by the Reflex backend server-side. Tokens are **never exposed to the browser** JavaScript runtime.

**Optional password gate** — when `WEBUI_PASSWORD` is non-empty, every data page redirects unauthenticated visitors to `/login`. The login form validates the password server-side and sets an `firnline_webui_session` cookie (HMAC-SHA256 derived from the password, 30-day max age). Logging out clears the cookie. When `WEBUI_PASSWORD` is empty (default), all pages are open — intended for LAN-only deployments where access is controlled at the network layer.

## Configuration

All environment variables are prefixed with `WEBUI_`. For the complete reference
table (service URLs, TerminusDB connection, UI behaviour), see the
[configuration reference](../reference/configuration.md#webui).

A guide-specific callout: when `WEBUI_PASSWORD` is non-empty, every data page
redirects unauthenticated visitors to `/login`. The login form validates the
password server-side and sets an `firnline_webui_session` cookie (HMAC-SHA256
derived from the password, 30-day max age). When `WEBUI_PASSWORD` is empty
(default), all pages are open — intended for LAN-only deployments where access
is controlled at the network layer.

## Deployment

### Docker Compose

The `webui` service is defined in `compose.yaml`:

```bash
docker compose up -d webui
```

The service depends on `captured` and `queryd` (service_started) and exposes port `${WEBUI_HOST_PORT:-3000}`. All `WEBUI_*` env vars are populated from the shared `.env` file.

**First boot** takes **~30–60 seconds** — Reflex compiles the Next.js frontend at container startup. The healthcheck uses `start_period: 120s` to allow plenty of time.

When all services are running (`docker compose up -d`), the UI is available at <http://localhost:3000>.

### Local development

```bash
cd services/webui
uv run reflex run
```

Starts the Reflex dev server on port 3000 (frontend) and 8000 (backend). Set `WEBUI_*` environment variables to point to your running services. See [development/local-development.md](../development/local-development.md) for the full development setup.

## Limitations (v1)

- **Read-only browse** — the UI displays documents but has no edit/create forms outside of capture.
- **No chat page** — the conversational queryd agent is not exposed in the UI.
- **Single shared password** — the password gate uses one shared password with no per-user accounts or roles.
- **Frontend compiles at boot** — container startup takes 30–60s while Reflex builds the Next.js frontend; subsequent requests are fast.

## Related documents

- [Quickstart](../getting-started/quickstart.md) — first capture and query
- [Querying guide](querying.md) — GraphQL and REST queries
- [Configuration reference](../reference/configuration.md) — all environment variables
- [Vision](../concepts/vision.md) — entity model and design decisions
