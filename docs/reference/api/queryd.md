# queryd API

FastAPI GraphQL read proxy with schema introspection, document lookup,
semantic search (via indexed), and flag-gated write-tool endpoints. All
endpoints except `/healthz` require bearer authentication.

## Authentication

**Bearer token** — `Authorization: Bearer <QUERYD_API_TOKEN>`. Token is
required on every request. Missing, malformed, or wrong token returns `401`
`{"detail": "unauthorized"}`.

## Endpoints

### `GET /healthz`

Unauthenticated health check.

**Response `200`:**

```json
{
  "status": "ok",
  "terminusdb": "up",
  "version": "0.1.0",
  "modules": {"core": "0.1.0", ...},
  "plugins": ["time_management_tools"],
  "write_tools": ["create_task", "log_activity"],
  "blob_root_writable": true
}
```

`503` when TDB is unreachable. `write_tools` is empty when
`QUERYD_ENABLE_WRITES=false` or no plugins are active.

### `GET /v1/schema`

Rendered schema summary derived from GraphQL introspection.
Requires bearer auth.

**Response `200`:**

```json
{
  "summary": "Classes:\n  Entity\n    created_at: DateTime\n..."
}
```

### `GET /v1/schema/introspection`

Raw GraphQL introspection JSON. Requires bearer auth.

**Response `200`:** Standard GraphQL introspection result (JSON object).

### `GET /v1/modules`

SchemaModule registry docs from TerminusDB. Requires bearer auth.

**Response `200`:** JSON array of module objects (`name`, `version`,
`origin`, `description`, `exports`, `depends_on`).

### `GET /v1/documents/{iri}`

Fetch a single document by IRI. Requires bearer auth.

**Response `200`:** The full document dict.

**Errors:**

| Status | Detail | Condition |
|---|---|---|
| `404` | `Document not found: <iri>` | IRI does not exist |
| `422` | Validation message | Invalid IRI (empty, path traversal, bad scheme) |

### `POST /v1/graphql`

Execute a read-only GraphQL query. Mutations are rejected by the backend.
Requires bearer auth.

**Request body:**

```json
{
  "query": "query { Entity { created_at } }",
  "variables": {"var1": "value1"}
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | GraphQL query (read-only) |
| `variables` | object | no | Variable bindings |

**Response `200`:** GraphQL result dict.

**Errors:**

| Status | Detail | Condition |
|---|---|---|
| `400` | Error message | Invalid query (value error from TDB) |
| `502` | Error message | TDB error |

### `POST /v1/find/entity`

Semantic entity search. Proxies to the `indexed` service. Requires bearer auth.
**Gated:** returns `503` when `QUERYD_INDEXED_ENABLED=false`.

**Request body:**

```json
{
  "text": "Anna",
  "classes": ["Person"],
  "k": 5
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | yes | — | Free-text search query |
| `classes` | array of strings | no | — | Filter by class name |
| `k` | integer | no | `5` | Max results |

**Response `200`:**

```json
{
  "candidates": [
    {
      "iri": "Person/abc",
      "class": "Person",
      "name": "Anna Meier",
      "aliases": ["Anna Meier"],
      "score": 0.91,
      "commit_id": "..."
    }
  ]
}
```

### `POST /v1/find/class`

Semantic class search. Proxies to `indexed`. Requires bearer auth.
**Gated:** `QUERYD_INDEXED_ENABLED=true`.

**Request body:**

```json
{
  "text": "reminder about a person",
  "k": 5
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | yes | — | Free-text search query |
| `k` | integer | no | `5` | Max results |

**Response `200`:**

```json
{
  "candidates": [
    {"class": "Reminder", "description": "A reminder about a task or event", "score": 0.86}
  ]
}
```

### `POST /v1/find/field`

Semantic field search. Proxies to `indexed`. Requires bearer auth.
**Gated:** `QUERYD_INDEXED_ENABLED=true`.

**Request body:**

```json
{
  "text": "when is it due",
  "class": "Task",
  "k": 5
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | yes | — | Free-text search query |
| `class` | string | no | — | Scope to a specific class |
| `k` | integer | no | `5` | Max results |

**Response `200`:**

```json
{
  "candidates": [
    {"class": "Task", "field": "due_date", "type": "xsd:dateTime", "description": "", "score": 0.88}
  ]
}
```

### `POST /v1/documents/{class_name}`

Create a new document of a given class. **Gated:** requires
`QUERYD_ENABLE_WRITES=true`. Requires bearer auth.

**Path parameter:**

| Parameter | Description |
|---|---|
| `class_name` | Document class name (e.g. `Task`, `Person`) — `[A-Za-z][A-Za-z0-9_]*` |

**Headers:**

| Header | Required | Default | Description |
|---|---|---|---|
| `X-Firnline-Agent` | no | `service:queryd` | Provenance agent ID (`service:<name>`, `user:<name>`, `ext:<name>`) |

**Request body:** JSON object with field values. Must NOT include `@type` or
`@id` — both are server-assigned.

**Response `201`:**

```json
{
  "iri": "Task/abc123"
}
```

**Errors:**

| Status | Detail | Condition |
|---|---|---|
| `400` | `Invalid class name: "..."` | `class_name` does not match pattern |
| `400` | Agent parse error | `X-Firnline-Agent` invalid grammar |
| `403` | `Writes are disabled` | `QUERYD_ENABLE_WRITES=false` |
| `409` | Conflict message | `TdbConflictError` (optimistic concurrency) |
| `422` | Errors list | Body validation (JSON parse, non-object, `@type`/`@id` present, schema violation) |
| `502` | TDB error message | Backend error |

### `GET /v1/tools`

List available write-tool specs (name, description, input_schema). Requires
bearer auth. Returns an empty list when `QUERYD_ENABLE_WRITES=false` or no
plugins are active.

**Response `200`:**

```json
{
  "tools": [
    {
      "name": "create_task",
      "description": "Create a new task",
      "input_schema": {"type": "object", "properties": {...}}
    }
  ]
}
```

### `POST /v1/tools/{name}`

Invoke a write tool by name. **Gated:** requires
`QUERYD_ENABLE_WRITES=true`. Requires bearer auth.

**Path parameter:** `name` — tool name from `GET /v1/tools`.

**Request body:** JSON object validated against the tool's `input_schema`.

**Response `200`:** Tool-specific result dict.

**Errors:**

| Status | Detail | Condition |
|---|---|---|
| `404` | `unknown tool: <name>` | Tool name not registered |
| `422` | Validation errors | Body does not match input_schema |
| `502` | `tool execution failed` | Handler raised exception |
| `504` | `request timed out` | Execution exceeded `QUERYD_REQUEST_TIMEOUT_SECONDS` |

## Related documents

- [Configuration reference](../configuration.md)
- [indexed API](indexed.md)
- [Entry points reference](../entry-points.md)
- [API overview](README.md)
