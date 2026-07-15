# indexed API

Precision grounding service. Mirrors TerminusDB documents and schema into a
hybrid vector+lexical index (SQLite FTS5 + cosine similarity) and serves
semantic search endpoints consumed by `ingestd` and `queryd`.

indexed is **read-only** over TDB and **dropoutable**: if unavailable,
callers degrade gracefully to casefold-exact match / raw GraphQL.

All endpoints are optionally protected by `INDEXED_API_TOKEN` (bearer).
When the token is empty (default), auth is skipped. `/healthz` is always
unauthenticated.

## Architecture

```
TDB  ──► indexed (poller + HTTP :8089)  ──► ingestd linker
   │         │                                 queryd find_* tools
   │         └─ sqlite file (INDEXED_DATA_DIR/index.db)
   │
   └─ commit log (polled via /api/log)
```

One direction of trust: `indexed` only reads TDB. No write endpoints.

## Authentication

**Bearer token** (optional) — `Authorization: Bearer <INDEXED_API_TOKEN>`.
If `INDEXED_API_TOKEN` is empty, all endpoints are open. When set, missing
or wrong token returns `401`.

## Endpoints

### `GET /healthz`

Unauthenticated health check. Returns `200` if the poller is alive
(liveness file touched within 5 minutes OR still in startup grace period)
and TDB is reachable; `503` otherwise.

**Response `200`:**

```json
{
  "status": "ok",
  "terminusdb": "up",
  "store": "ok",
  "poller": "alive"
}
```

**Response `503`:**

```json
{
  "status": "degraded",
  "terminusdb": "down",
  "store": "ok",
  "poller": "stale"
}
```

### `POST /v1/find_entity`

Semantic entity search. Optionally bearer-authed via `INDEXED_API_TOKEN`.

**Request body:**

```json
{
  "text": "Anna",
  "classes": ["Person"],
  "branch": "main",
  "k": 5
}
```

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `text` | string | yes | — | `min_length=1` | Free-text search query |
| `classes` | array of strings | no | — | — | Filter by class name |
| `branch` | string | no | `"main"` | — | TDB branch to query |
| `k` | integer | no | `5` | `1 ≤ k ≤ 50` | Max results |

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
      "commit_id": "a1b2c3d4..."
    }
  ],
  "commit_id": "a1b2c3d4..."
}
```

Results are thresholded by `INDEXED_MIN_CONFIDENCE` (default `0.60`).

### `POST /v1/find_class`

Semantic class search. Optionally bearer-authed.

**Request body:**

```json
{
  "text": "reminder about a person",
  "k": 5
}
```

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `text` | string | yes | — | `min_length=1` | Free-text search query |
| `k` | integer | no | `5` | `1 ≤ k ≤ 50` | Max results |

**Response `200`:**

```json
{
  "candidates": [
    {"class": "Reminder", "description": "A reminder about a task or event", "score": 0.86}
  ]
}
```

### `POST /v1/find_field`

Semantic field search. Optionally bearer-authed.

**Request body:**

```json
{
  "text": "when is it due",
  "class": "Task",
  "k": 5
}
```

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `text` | string | yes | — | `min_length=1` | Free-text search query |
| `class` | string | no | — | — | Scope to a specific class |
| `k` | integer | no | `5` | `1 ≤ k ≤ 50` | Max results |

**Response `200`:**

```json
{
  "candidates": [
    {"class": "Task", "field": "due_date", "type": "xsd:dateTime", "description": "", "score": 0.88}
  ]
}
```

## Enabling / disabling

### Ingestd

Set `INGESTD_INDEXED_ENABLED=true` and `INGESTD_INDEXED_URL` appropriately.
When disabled (default `false`), entity linking falls back to casefold-exact
match only.

### Queryd

Set `QUERYD_INDEXED_ENABLED=true`. When disabled, the `find_entity`,
`find_class`, and `find_field` endpoints return `503` with a descriptive
error instructing the caller to fall back to `get_schema` + `graphql_query`.

See the [configuration reference](../configuration.md) for the full set of
indexed-related variables.

## Inspecting the index

The sqlite file lives at `INDEXED_DATA_DIR/index.db` (default
`/var/lib/firnline/index/index.db`):

```bash
# List indexed entities
sqlite3 /var/lib/firnline/index/index.db \
  "SELECT class, name, aliases_json FROM entities ORDER BY rowid LIMIT 20"

# List indexed schema items
sqlite3 /var/lib/firnline/index/index.db \
  "SELECT kind, class, name FROM schema_items LIMIT 20"
```

## How entities get indexed

Extensions register `IndexerPlugin` instances under the
`firnline.indexed.indexers` entry-point group (see [entry-points
reference](../entry-points.md)). Each plugin declares which TDB document
classes to mirror and how to extract text + aliases from each document. At
startup, `indexed` discovers all plugins, verifies their module
requirements against the `SchemaModule` registry, and skips any with unmet
requirements (WARNING log). Duplicate class registrations across active
plugins are a startup error.

## Related documents

- [Configuration reference](../configuration.md)
- [Entry points reference](../entry-points.md)
- [queryd API](queryd.md)
- [API overview](README.md)
