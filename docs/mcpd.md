# mcpd — MCP Server

mcpd exposes firnline to external AI agents via the
[Model Context Protocol](https://modelcontextprotocol.io/) (streamable HTTP).
It wraps queryd and captured over HTTP — no direct database access — and
presents firnline's capabilities as MCP tools and resources.

## Architecture

```
External AI agent ─► mcpd (streamable HTTP, :8090)
                        │
                        ├─► queryd (:8087) — GraphQL, schema, find_*, documents
                        └─► captured (:8088) — capture note
```

mcpd is a **facade**: it translates MCP requests into REST calls to
queryd/captured and returns results in MCP format. It holds no state, no
database connections, no extensions, and no schema knowledge beyond what
queryd serves.

## Configuration

All environment variables are prefixed with `MCPD_`:

| Variable | Default | Required | Description |
|---|---|---|---|
| `MCPD_HOST` | `0.0.0.0` | no | Host to bind |
| `MCPD_PORT` | `8090` | no | Port to bind |
| `MCPD_QUERYD_URL` | `http://queryd:8087` | yes | Base URL of the queryd service |
| `MCPD_QUERYD_TOKEN` | — | yes | Bearer token for queryd endpoints |
| `MCPD_CAPTURED_URL` | `http://captured:8088` | yes | Base URL of the captured service |
| `MCPD_CAPTURED_TOKEN` | — | yes | Bearer token for captured endpoints |

## Tools

| Tool | Description | Backed by |
|---|---|---|
| `graphql_query` | Execute a read-only GraphQL query against firnline | queryd `POST /v1/graphql` |
| `get_document` | Fetch a single document by IRI | queryd `GET /v1/documents/{iri}` |
| `find_entity` | Semantic search for known entities | queryd `POST /v1/find/entity` |
| `find_class` | Semantic search for schema classes | queryd `POST /v1/find/class` |
| `find_field` | Semantic search for class fields | queryd `POST /v1/find/field` |
| `get_schema` | Rendered schema summary | queryd `GET /v1/schema` |
| `list_modules` | List installed schema modules | queryd `GET /v1/modules` |
| `capture` | Submit a text note | captured `POST /v1/capture/note` |

All tools require bearer authentication — tokens are forwarded to the
backend service. Errors are translated to MCP error responses.

## Resources

| URI | Content | Backed by |
|---|---|---|
| `firnline://schema` | Rendered schema summary (string) | queryd `GET /v1/schema` |
| `firnline://schema/introspection` | Raw GraphQL introspection JSON | queryd `GET /v1/schema/introspection` |
| `firnline://modules` | SchemaModule registry JSON array | queryd `GET /v1/modules` |

Resources are read-only and stateless — every read fetches live data from
queryd.

## Deployment

mcpd runs as a standalone Docker container in the compose stack. It binds
to port 8090 (configurable via `MCPD_PORT`). The service depends on
queryd and captured (service_started).

```bash
docker compose up -d mcpd
```

Health check: ``GET /healthz`` returns ``{"status": "ok"}`` with HTTP 200.

## Design notes

- **No direct database access** — mcpd only talks to queryd and captured
  over HTTP. It has no TDB credentials or connection.
- **Stateless** — every MCP request is a live call to the backend; mcpd
  caches nothing.
- **No extensions** — mcpd uses no plugin system; all capability comes
  from the backend services it wraps.
- **Future**: `find_entity`/`find_class`/`find_field` tools require the
  `indexed` grounding service to be enabled on queryd. When `indexed` is
  unavailable, these tools return an error instructing the agent to use
  `graphql_query` or `get_schema` instead.
