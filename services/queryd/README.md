# queryd

Conversational agent API over a TerminusDB-backed knowledge graph. Exposes a
stateless `POST /v1/chat` endpoint: clients send the full message history each
turn and receive a natural-language answer plus an observability `tool_trace`.

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
QUERYD_LLM_BASE_URL=http://localhost:4000 \
QUERYD_LLM_API_KEY=sk-placeholder \
QUERYD_LLM_MODEL=gpt-4.1-mini \
uv run queryd
```

## API

### `POST /v1/chat`

Auth: `Authorization: Bearer <token>`.

```json
{
  "messages": [
    {"role": "user", "content": "Was steht diese Woche an?"}
  ]
}
```

Response:

```json
{
  "message": "...",
  "tool_trace": [
    {"tool": "graphql_query", "input": {...}, "output_summary": "1288 chars"}
  ]
}
```

### `GET /healthz`

No auth. Returns `{"status": "ok", "terminusdb": "up", "version": "...",
"modules": {...}, "active_tools": [...]}`.

## Configuration, extensions, and tests

See the [project documentation](../../docs/):

- [Configuration](../../docs/configuration.md) — all `QUERYD_*` env vars
- [Architecture](../../docs/architecture.md) — how queryd fits into the system
- [Extensions](../../docs/extensions.md) — writing queryd write-tool plugins

Run tests from the monorepo root:

```bash
uv run pytest services/queryd/
```
