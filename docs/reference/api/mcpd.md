# mcpd API

MCP server (streamable HTTP) exposing firnline to external AI agents via the
[Model Context Protocol](https://modelcontextprotocol.io/). Wraps `queryd`
and `captured` over HTTP — no direct database access — and presents
firnline's capabilities as MCP tools and resources.

## Architecture

```
External AI agent ─► mcpd (streamable HTTP, :8090)
                        │
                        ├─► queryd (:8087) — GraphQL, schema, find_*, documents, write tools
                        └─► captured (:8088) — capture note, file upload
```

mcpd is a **facade**: it translates MCP requests into REST calls to
queryd/captured and returns results in MCP format. It holds no state, no
database connections, no extensions, and no schema knowledge beyond what
queryd serves.

## Configuration

All via environment variables prefixed `MCPD_`. See [configuration
reference](../configuration.md) for the full table. Key variables:

- `MCPD_QUERYD_URL` / `MCPD_QUERYD_TOKEN` — queryd backend
- `MCPD_CAPTURED_URL` / `MCPD_CAPTURED_TOKEN` — captured backend
- `MCPD_ENABLE_QUERYD_TOOLS` (default `true`) — registers queryd write tools as dynamic MCP tools
- `MCPD_REQUEST_TIMEOUT_SECONDS` (default `30.0`) — timeout for backend calls

## Tools

All tools use bearer-authenticated HTTP calls to the backend. Errors are
translated to MCP error responses.

### Static tools (9)

These are always registered regardless of backend state:

| Tool | Description | Backed by |
|---|---|---|
| `graphql_query` | Execute a read-only GraphQL query | queryd `POST /v1/graphql` |
| `get_document` | Fetch a single document by IRI | queryd `GET /v1/documents/{iri}` |
| `find_entity` | Semantic search for known entities | queryd `POST /v1/find/entity` |
| `find_class` | Semantic search for schema classes | queryd `POST /v1/find/class` |
| `find_field` | Semantic search for class fields | queryd `POST /v1/find/field` |
| `get_schema` | Rendered schema summary (string) | queryd `GET /v1/schema` |
| `list_modules` | List installed schema modules (JSON array) | queryd `GET /v1/modules` |
| `capture` | Submit a text note | captured `POST /v1/capture/note` |
| `create_document` | Create a structured document of a known class | queryd `POST /v1/documents/{class_name}` |

### Dynamic write tools

At startup, mcpd calls `GET /v1/tools` on queryd. If
`QUERYD_ENABLE_WRITES=true` on queryd (and `MCPD_ENABLE_QUERYD_TOOLS=true`
on mcpd), queryd returns a list of write-tool specs (name, description,
input_schema) sourced from extension plugins implementing the
`firnline.queryd.tools` entry-point group. mcpd registers each one as a
dynamically-named MCP tool.

When `QUERYD_ENABLE_WRITES=false`, `/v1/tools` returns an empty list and no
dynamic write tools appear.

Dynamic tools are invoked via `POST /v1/tools/{name}` with arguments
validated against the tool's `input_schema`. All calls are bearer-authed
with the queryd token.

Tool name collisions between dynamic and static tools are skipped with a
warning.

### Tool arguments

| Tool | Arguments |
|---|---|
| `graphql_query` | `query: str`, `variables: dict | None` |
| `get_document` | `iri: str` |
| `find_entity` | `text: str`, `classes: list[str] | None`, `k: int = 5` |
| `find_class` | `text: str`, `k: int = 5` |
| `find_field` | `text: str`, `class_name: str | None`, `k: int = 5` |
| `get_schema` | (none) |
| `list_modules` | (none) |
| `capture` | `text: str` |
| `create_document` | `class_name: str`, `fields: dict`, `agent: str | None` |

`create_document` sets `X-Firnline-Agent: ext:mcp` by default to correctly
attribute external-agent writes.

## Resources

Read-only, stateless — every read fetches live data from queryd.

| URI | Content | Backed by |
|---|---|---|
| `firnline://schema` | Rendered schema summary (string) | queryd `GET /v1/schema` |
| `firnline://schema/introspection` | Raw GraphQL introspection JSON | queryd `GET /v1/schema/introspection` |
| `firnline://modules` | SchemaModule registry JSON array | queryd `GET /v1/modules` |

## Health check

`GET /healthz` returns `{"status": "ok"}` with HTTP 200. Unauthenticated.

## Design notes

- **No direct database access** — mcpd only talks to queryd and captured
  over HTTP. It has no TDB credentials or connection.
- **Stateless** — every MCP request is a live call to the backend; mcpd
  caches nothing.
- **No extensions** — mcpd uses no plugin system; all capability comes
  from the backend services it wraps.
- **No MCP auth** — the streamable HTTP transport itself is unauthenticated;
  auth is enforced at the backend level via forwarded tokens.
- The `find_entity`/`find_class`/`find_field` tools require `indexed` to be
  enabled on queryd (`QUERYD_INDEXED_ENABLED=true`). When `indexed` is
  unavailable, these tools return an error instructing the agent to use
  `graphql_query` or `get_schema` instead.

## Related documents

- [Configuration reference](../configuration.md)
- [queryd API](queryd.md)
- [captured API](captured.md)
- [API overview](README.md)
