# MCP tools and resources

## Purpose

This page is the single source of truth for all MCP tools and resources
exposed by mcpd. For conceptual background, see
[concepts/architecture.md](../concepts/architecture.md). For configuration
variables, see [reference/configuration.md](configuration.md).

## Endpoint

mcpd is mounted at `/mcp` on the **apid** daemon (port 8080). When running
standalone, mcpd binds on `0.0.0.0:8090` (configurable via `MCPD_HOST` /
`MCPD_PORT`). Clients should connect to:

```
http://<host>:8080/mcp
```

Health check: `GET /healthz` returns `{"status": "ok"}` with HTTP 200.

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
| `create_document` | Create a typed document directly | queryd `POST /v1/documents/{class_name}` |

### Dynamic write tools

At startup, mcpd calls `GET /v1/tools` on queryd. When
`QUERYD_ENABLE_WRITES=true`, queryd returns a list of write-tool specs (name,
description, `input_schema`) sourced from extension plugins implementing the
`firnline.queryd.tools` entry-point group. mcpd registers each one as a
dynamically-named MCP tool (gated by `MCPD_ENABLE_QUERYD_TOOLS`, default `true`).

When `QUERYD_ENABLE_WRITES=false`, `/v1/tools` returns an empty list and no
dynamic write tools appear in the MCP tool list.

Dynamic write tools are invoked via `POST /v1/tools/{name}` with arguments
matching each tool's `input_schema`. All calls are bearer-authed with the queryd
token.

The `find_entity`, `find_class`, and `find_field` tools require
`QUERYD_INDEXED_ENABLED=true`. When `indexed` is unavailable, they return an
error instructing the agent to use `graphql_query` or `get_schema` instead.

## Resources

| URI | Content | Backed by |
|---|---|---|
| `firnline://schema` | Rendered schema summary (string) | queryd `GET /v1/schema` |
| `firnline://schema/introspection` | Raw GraphQL introspection JSON | queryd `GET /v1/schema/introspection` |
| `firnline://modules` | SchemaModule registry JSON array | queryd `GET /v1/modules` |

Resources are read-only and stateless — every read fetches live data from
queryd.

## Related documents

- [Configuration reference](configuration.md) — `MCPD_*` env vars
- [API reference](api.md) — backend endpoints backing each tool/resource
- [Entry-point reference](entry-points.md) — `firnline.queryd.tools` group
