# queryd

GraphQL read proxy + document lookup + schema introspection + guarded write-tool
endpoints over a TerminusDB-backed knowledge graph. Model-free — no embedded LLM.

## Quickstart

From the monorepo root:

```bash
docker compose --profile bootstrap up bootstrap --abort-on-container-exit
docker compose up -d                        # starts queryd on port 8087
curl http://localhost:8087/healthz          # verify
```

For local dev without Docker:

```bash
QUERYD_TDB_URL=http://localhost:6363 \
QUERYD_TDB_DB=dev \
QUERYD_TDB_PASSWORD=root \
QUERYD_API_TOKEN=dev-token \
uv run queryd
```

## API

### `POST /v1/graphql`

Auth: `Authorization: Bearer <token>`.

```json
{
  "query": "{ Task { id name done } }"
}
```

Response is a standard GraphQL JSON payload.

### `GET /v1/tools`

Lists write-tool specs (name, description, input_schema). Empty when
`QUERYD_ENABLE_WRITES=false`. See [mcpd API](../../docs/reference/api/mcpd.md) for how mcpd
registers these as dynamic MCP tools.

### `POST /v1/tools/{name}`

Invokes a write tool by name. Requires `QUERYD_ENABLE_WRITES=true`.

### `GET /v1/documents/{iri}`

Fetches a single document by IRI.

### `GET /v1/schema` / `GET /v1/modules`

Schema introspection and module registry.

### `POST /v1/find/entity|class|field`

Semantic search endpoints (requires indexed grounding service).

### `GET /healthz`

No auth. Returns `{"status": "ok", "terminusdb": "up", "write_tools": [...], "version": "...", "modules": {...}}`.

## Configuration, extensions, and tests

Full documentation:

- [queryd API reference](../../docs/reference/api/queryd.md)
- [Configuration reference](../../docs/reference/configuration.md) — all `QUERYD_*` env vars
- [Architecture](../../docs/concepts/architecture.md) — how queryd fits into the system
- [Extension development](../../docs/development/extension-development.md) — writing queryd write-tool plugins

Run tests from the monorepo root:

```bash
uv run pytest services/queryd/
```
