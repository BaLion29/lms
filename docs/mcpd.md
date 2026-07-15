# mcpd — MCP Server

mcpd exposes firnline to external AI agents via the
[Model Context Protocol](https://modelcontextprotocol.io/) (streamable HTTP).
It wraps queryd and captured over HTTP — no direct database access — and
presents firnline's capabilities as MCP tools and resources.

## Architecture

```
External AI agent ─► mcpd (streamable HTTP, :8090)
                        │
                        ├─► queryd (:8087) — GraphQL, schema, find_*, documents, write tools
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
| (dynamic) | Write tools registered at startup from queryd | queryd `GET /v1/tools` → `POST /v1/tools/{name}` |

### Dynamic write tools

At startup, mcpd calls `GET /v1/tools` on queryd. If `QUERYD_ENABLE_WRITES=true`
on queryd, queryd returns a list of write-tool specs (name, description,
input_schema) sourced from extension plugins implementing the
`firnline.queryd.tools` entry-point group. mcpd registers each one as a
dynamically-named MCP tool (gated by `MCPD_ENABLE_QUERYD_TOOLS`, default `true`).

When `QUERYD_ENABLE_WRITES=false`, `/v1/tools` returns an empty list and no
dynamic write tools appear in the MCP tool list.

Write tools are invoked via `POST /v1/tools/{name}` with the arguments
specified in each tool's `input_schema`. The tool implementation in the
extension plugin executes the write against TerminusDB and returns a result.
All calls are bearer-authed with the queryd token.

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
