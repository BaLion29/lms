# REST API reference

## Purpose

This page lists every REST endpoint served by the firnline services, with
request/response shapes, auth requirements, and enabling flags. Use it as the
canonical API reference. Config tokens and feature flags are documented in
[reference/configuration.md](configuration.md).

## Auth

All non-healthz endpoints require `Authorization: Bearer <token>`. Each
service validates against its own token:

- captured: `CAPTURED_API_TOKEN`
- queryd: `QUERYD_API_TOKEN`
- indexed: `INDEXED_API_TOKEN` (optional — empty = no auth required)

`/healthz` requires no authentication.

## captured

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/v1/capture/note` | Bearer `CAPTURED_API_TOKEN` | Submit a text note for ingestion |
| `POST` | `/v1/capture/file` | Bearer `CAPTURED_API_TOKEN` | Upload a file with kind and metadata |
| `GET` | `/healthz` | none | Liveness + module/handler status |

### POST /v1/capture/note

The endpoint accepts two content types:

**text/plain** — frictionless raw-text submission (best for shell pipes, quick notes):

```bash
curl -X POST http://localhost:8080/v1/capture/note \
  -H "Authorization: Bearer $CAPTURED_API_TOKEN" \
  -H "Content-Type: text/plain" \
  --data-binary "Buy milk"
```

**application/json** — structured submission with kind and optional metadata:

```bash
curl -X POST http://localhost:8080/v1/capture/note \
  -H "Authorization: Bearer $CAPTURED_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy milk", "kind": "note", "metadata": {}}'
```

**Request body (application/json)** — `NoteRequest`:

| Field | Type | Default | Description |
|---|---|---|---|
| `text` | `string` | required | Free-text note content |
| `kind` | `string` | `"note"` | Handler kind (must match a registered `CaptureHandler.kinds` entry) |
| `metadata` | `object` | `{}` | Arbitrary key-value metadata |
| `captured_at` | `string` (ISO 8601) | server time | Time of capture |

**Request body (text/plain)** — raw UTF-8 text, treated as `kind: "note"` with
no metadata and server-assigned `captured_at`.

**Response** — 201:

```json
{"id": "Captured/abc123", "kind": "note"}
```

Rejects kinds that require a file upload (currently only `"file"`) with 422.

### POST /v1/capture/file

```bash
curl -X POST http://localhost:8088/v1/capture/file \
  -H "Authorization: Bearer $CAPTURED_API_TOKEN" \
  -F "file=@memo.txt" \
  -F "kind=file" \
  -F 'metadata={"source":"desktop"}'
```

**Form fields**:

| Field | Type | Default | Description |
|---|---|---|---|
| `file` | binary | required | Uploaded file (max `CAPTURED_MAX_UPLOAD_BYTES`, default 50 MB) |
| `kind` | `string` | `"file"` | Handler kind |
| `metadata` | `string` (JSON) | `"{}"` | JSON object with arbitrary metadata |
| `captured_at` | `string` (ISO 8601) | server time | Time of capture (tz-aware required) |

**Response** — 201:

```json
{"id": "Captured/abc123", "kind": "file", "sha256": "0ae4...", "size": 12345}
```

### GET /healthz

```json
{
  "status": "ok",
  "terminusdb": "up",
  "version": "0.1.0",
  "modules": {"core": "1.1.0"},
  "handlers": ["inbox_note"],
  "blob_root_writable": true
}
```

## queryd

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/v1/schema` | Bearer `QUERYD_API_TOKEN` | Rendered schema summary |
| `GET` | `/v1/schema/introspection` | Bearer `QUERYD_API_TOKEN` | Raw GraphQL introspection JSON |
| `GET` | `/v1/modules` | Bearer `QUERYD_API_TOKEN` | SchemaModule registry docs |
| `GET` | `/v1/documents/{iri}` | Bearer `QUERYD_API_TOKEN` | Fetch a document by IRI |
| `POST` | `/v1/graphql` | Bearer `QUERYD_API_TOKEN` | Read-only GraphQL query |
| `POST` | `/v1/documents/{class_name}` | Bearer `QUERYD_API_TOKEN` | Create a document (requires `QUERYD_ENABLE_WRITES=true`) |
| `GET` | `/v1/tools` | Bearer `QUERYD_API_TOKEN` | List write-tool specs (empty when writes disabled) |
| `POST` | `/v1/tools/{name}` | Bearer `QUERYD_API_TOKEN` | Invoke a write tool (requires `QUERYD_ENABLE_WRITES=true`) |
| `POST` | `/v1/find/entity` | Bearer `QUERYD_API_TOKEN` | Semantic entity search (requires `QUERYD_INDEXED_ENABLED=true`) |
| `POST` | `/v1/find/class` | Bearer `QUERYD_API_TOKEN` | Semantic class search (requires `QUERYD_INDEXED_ENABLED=true`) |
| `POST` | `/v1/find/field` | Bearer `QUERYD_API_TOKEN` | Semantic field search (requires `QUERYD_INDEXED_ENABLED=true`) |
| `GET` | `/healthz` | none | Liveness + module/plugin/tool status |

### POST /v1/graphql

```bash
curl -X POST http://localhost:8087/v1/graphql \
  -H "Authorization: Bearer $QUERYD_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ Person(limit: 5) { _id name } }"}'
```

**Request body** — `GraphQLRequest`:

| Field | Type | Description |
|---|---|---|
| `query` | `string` | GraphQL query string |
| `variables` | `object` | Optional variables |

Returns raw TerminusDB GraphQL response. Mutations are rejected (400).

### GET /v1/documents/{iri}

**Path parameter** — `iri`: document IRI (e.g. `Person/alice` or
`terminusdb:///data/Person/alice`). Path traversal (`..`) is rejected.

Returns the raw TerminusDB document JSON (404 if not found).

### POST /v1/documents/{class_name}

```bash
curl -X POST http://localhost:8087/v1/documents/Task \
  -H "Authorization: Bearer $QUERYD_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Firnline-Agent: ext:mcp" \
  -d '{"name": "Write docs", "status": "TaskStatus/todo"}'
```

**Path parameter** — `class_name`: valid `[A-Za-z][A-Za-z0-9_]*` class name.

**Request body** — JSON object (must not contain `@type` or `@id`; server assigns
both). Validated against the TerminusDB schema; 422 on validation failure, 409
on conflict.

Optional header `X-Firnline-Agent` sets the provenance agent (default `service:queryd`).

**Response** — 201:

```json
{"iri": "Task/abc123"}
```

**Gate**: requires `QUERYD_ENABLE_WRITES=true` (returns 403 otherwise).

### POST /v1/find/entity

**Request body** — `FindEntityRequest`:

| Field | Type | Default | Description |
|---|---|---|---|
| `text` | `string` | required | Search query |
| `classes` | `list[string]` | `null` (all) | Restrict to these TDB class @id values |
| `k` | `int` | `5` | Max results (1–50) |

**Response** — `{"candidates": [{"iri": "...", "class": "...", "name": "...", "aliases": [...], "score": 0.95, "commit_id": "..."}]}`.

### POST /v1/find/class

**Request body** — `FindClassRequest`: `text` (required), `k` (default 5).

**Response** — `{"candidates": [{"class": "...", "description": "...", "score": 0.87}]}`.

### POST /v1/find/field

**Request body** — `FindFieldRequest`: `text` (required), `class_name` (optional filter), `k` (default 5).

**Response** — `{"candidates": [{"class": "...", "field": "...", "type": "...", "description": "...", "score": 0.82}]}`.

### GET /v1/tools

Returns `{"tools": [{"name": "...", "description": "...", "input_schema": {...}}]}`.
Empty list when `QUERYD_ENABLE_WRITES=false`.

### POST /v1/tools/{name}

Invokes a named write tool with a JSON body validated against its `input_schema`.
Returns the tool's result object. Requires `QUERYD_ENABLE_WRITES=true`.

### GET /healthz

```json
{
  "status": "ok",
  "terminusdb": "up",
  "version": "0.1.0",
  "modules": {"core": "1.1.0"},
  "plugins": ["time_management_tools"],
  "write_tools": ["create_task"],
  "blob_root_writable": true
}
```

## indexed

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/v1/find_entity` | Bearer `INDEXED_API_TOKEN` (optional) | Semantic entity search (hybrid vector + lexical) |
| `POST` | `/v1/find_class` | Bearer `INDEXED_API_TOKEN` (optional) | Semantic class search |
| `POST` | `/v1/find_field` | Bearer `INDEXED_API_TOKEN` (optional) | Semantic field search |
| `GET` | `/healthz` | none | Poller liveness + TDB + store status |

### POST /v1/find_entity

**Request body**:

| Field | Type | Default | Description |
|---|---|---|---|
| `text` | `string` | required | Search query |
| `classes` | `list[string]` | `null` | Restrict to these class names |
| `branch` | `string` | `"main"` | TDB branch to search |
| `k` | `int` | `5` | Max results (1–50) |

**Response** — `{"candidates": [...], "commit_id": "..."}`. Each candidate:
`iri`, `class`, `name`, `aliases`, `score`, `commit_id`.

### POST /v1/find_class

**Request body**: `text` (required), `k` (default 5).

**Response**: `{"candidates": [{"class": "...", "description": "...", "score": 0.9}]}`.

### POST /v1/find_field

**Request body**: `text` (required), `class` (optional filter), `k` (default 5).

**Response**: `{"candidates": [{"class": "...", "field": "...", "type": "...", "description": "...", "score": 0.8}]}`.

`INDEXED_MIN_CONFIDENCE` (default `0.60`) filters results below the score
threshold.

### GET /healthz

```json
{
  "status": "ok",
  "terminusdb": "up",
  "store": "ok",
  "poller": "alive"
}
```

## apid (combined deployment)

The **apid** daemon binds on port 8080 and mounts `captured`, `queryd`, and
`indexed` routers under the same FastAPI app. The MCP server is mounted at
`/mcp` (see [reference/mcp.md](mcp.md)). All three services share the same
port — there is no separate service URL.

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Combined health (reports all four components) |

```json
{
  "status": "ok",
  "components": {
    "captured": "ok",
    "queryd": "ok",
    "indexed": "ok",
    "mcpd": "ok"
  }
}
```

## Related documents

- [Configuration reference](configuration.md) — tokens, feature flags, and service URLs
- [MCP reference](mcp.md) — MCP tools and resources
- [CLI reference](cli.md) — `firnline-schema` commands
- [Entry-point reference](entry-points.md) — plugin system
