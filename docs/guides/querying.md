# Querying Data

Task-oriented guide to querying your firnline data through queryd. Every request requires a bearer token (`QUERYD_API_TOKEN` from your `.env`).

## GraphQL queries

**Endpoint:** `POST /v1/graphql`

Queries are branch-scoped — queryd targets the TerminusDB branch configured via `TDB_BRANCH` (default `main`). Mutations are rejected (read-only).

```bash
curl -s -X POST http://localhost:8087/v1/graphql \
  -H "Authorization: Bearer $QUERYD_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ Task { id name done } }"}'
```

Response is a standard GraphQL JSON payload:

```json
{
  "data": {
    "Task": [
      {"id": "doc:task/abc123", "name": "Buy milk on the way home", "done": false}
    ]
  }
}
```

### Discovering the schema

Use the introspection endpoint to explore the GraphQL schema:

```bash
curl -s http://localhost:8087/v1/schema/introspection \
  -H "Authorization: Bearer $QUERYD_API_TOKEN"
```

For a human-readable schema summary:

```bash
curl -s http://localhost:8087/v1/schema \
  -H "Authorization: Bearer $QUERYD_API_TOKEN"
```

## Structured REST endpoints

All endpoints require the bearer token.

### Schema and modules

| Endpoint | Description |
|---|---|
| `GET /v1/schema` | Rendered schema summary (human-readable) |
| `GET /v1/schema/introspection` | Raw GraphQL introspection JSON |
| `GET /v1/modules` | SchemaModule registry documents (name, version, description, exports, deps) |

```bash
# List all installed schema modules
curl -s http://localhost:8087/v1/modules \
  -H "Authorization: Bearer $QUERYD_API_TOKEN"
```

### Document lookup

| Endpoint | Description |
|---|---|
| `GET /v1/documents/{iri}` | Fetch a single document by IRI |

```bash
curl -s http://localhost:8087/v1/documents/doc:task/abc123 \
  -H "Authorization: Bearer $QUERYD_API_TOKEN"
```

### Write tools (gated)

| Endpoint | Description |
|---|---|
| `GET /v1/tools` | List available write-tool specs (name, description, input_schema) |
| `POST /v1/tools/{name}` | Invoke a write tool by name |

Write tools are gated by `QUERYD_ENABLE_WRITES`. When set to `false` (default), `GET /v1/tools` returns an empty list and `POST /v1/tools/{name}` is unavailable.

```bash
# Enable writes in .env:
# QUERYD_ENABLE_WRITES=true

# List tools
curl -s http://localhost:8087/v1/tools \
  -H "Authorization: Bearer $QUERYD_API_TOKEN"

# Invoke a tool
curl -s -X POST http://localhost:8087/v1/tools/complete_task \
  -H "Authorization: Bearer $QUERYD_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"id": "doc:task/abc123"}'
```

### Semantic search (requires indexed)

When `QUERYD_INDEXED_ENABLED=true`, queryd provides three semantic search endpoints backed by the indexed service:

| Endpoint | Description |
|---|---|
| `POST /v1/find/entity` | Semantic entity search |
| `POST /v1/find/class` | Semantic class search |
| `POST /v1/find/field` | Semantic field search |

```bash
curl -s -X POST http://localhost:8087/v1/find/entity \
  -H "Authorization: Bearer $QUERYD_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "grocery shopping", "limit": 5}'
```

> These endpoints require the indexed service to be running and `QUERYD_INDEXED_ENABLED=true`.

## Authentication

Every queryd endpoint requires a `Authorization: Bearer <token>` header where the token matches `QUERYD_API_TOKEN`. There is no fine-grained access control — a single token protects all endpoints.

## Common pitfalls

- **401 Unauthorized**: the bearer token is missing or does not match `QUERYD_API_TOKEN`. Verify your `.env` value.
- **Empty GraphQL results**: ensure ingestd has processed your captures and written documents to the branch queryd is querying (check `TDB_BRANCH`).
- **Empty `/v1/tools` response**: `QUERYD_ENABLE_WRITES` is `false`. Set it to `true` in `.env` and restart queryd.
- **Indexed search returns nothing**: confirm `QUERYD_INDEXED_ENABLED=true`, the indexed service is healthy (`curl localhost:8089/healthz`), and the index has synced (first sync takes one poll cycle).

## Related documents

- [queryd API reference](../reference/api/queryd.md) — full endpoint table
- [Configuration reference](../reference/configuration.md) — queryd and indexed env vars
- [WebUI guide](web-ui.md) — browse documents through the Reflex dashboard
