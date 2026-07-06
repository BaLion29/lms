# queryd

Conversational query agent over a TerminusDB-backed life-management system.
`queryd` exposes a **stateless** `POST /v1/chat` endpoint: clients send the
full message history each turn and receive a natural-language answer plus an
observability `tool_trace`. It shares the `lms-core` package with sibling
services `ingestd` (data ingestion) and a Reflex-based frontend.

## Requirements

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/) for dependency management
- The `lms-core` sibling checkout at `../lms-core` (editable path dependency)
- A running [TerminusDB](https://terminusdb.com/) instance (v12.0.6)
- A running LiteLLM proxy (or any OpenAI-compatible provider)

## Install

```bash
git clone <repo-url> lms-queryd
cd lms-queryd
uv sync
```

Ensure `../lms-core` exists and is installed (`uv sync` in its directory or
from this project's workspace — the `[tool.uv.sources]` in `pyproject.toml`
makes it an editable dependency).

## Environment variables

All settings are prefixed with `QUERYD_`. The service inherits TerminusDB
connection settings from `lms_core.settings.TdbSettings` (accessible under
the `QUERYD_` prefix).

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `QUERYD_API_TOKEN` | string | – | **yes** | Bearer token for `/v1/chat` auth |
| `QUERYD_LLM_BASE_URL` | string | – | **yes** | Base URL of the LiteLLM proxy (e.g. `http://localhost:4000`) |
| `QUERYD_LLM_API_KEY` | string | – | **yes** | API key for the LiteLLM proxy |
| `QUERYD_LLM_MODEL` | string | – | **yes** | Model name (e.g. `gpt-4.1-mini`) |
| `QUERYD_TDB_URL` | string | – | **yes** | TerminusDB base URL (e.g. `http://localhost:6363`) |
| `QUERYD_TDB_DB` | string | – | **yes** | TerminusDB database name (e.g. `queryd_dev`) |
| `QUERYD_TDB_ORG` | string | `admin` | no | TerminusDB organisation |
| `QUERYD_TDB_BRANCH` | string | `main` | no | TerminusDB branch |
| `QUERYD_TDB_USER` | string | `admin` | no | TerminusDB username |
| `QUERYD_TDB_PASSWORD` | string | – | no | TerminusDB password |
| `QUERYD_ENABLE_WRITES` | bool | `false` | no | If `true`, mutation tools are registered (set_task_status, create_task, etc.) |
| `QUERYD_MAX_TOOL_ITERATIONS` | int | `8` | no | Max tool calls per request (soft cap) |
| `QUERYD_REQUEST_TIMEOUT_SECONDS` | float | `60` | no | Total request timeout (seconds) |
| `QUERYD_LISTEN_ADDR` | string | `0.0.0.0:8087` | no | Host:port to bind |
| `QUERYD_CORS_ORIGINS` | string/list | `[]` | no | Comma-separated CORS origins |

## Run modes

### Local dev

```bash
QUERYD_API_TOKEN=dev-token \
QUERYD_TDB_URL=http://10.0.10.20:6364 \
QUERYD_TDB_DB=queryd_dev \
QUERYD_TDB_PASSWORD=root \
QUERYD_LLM_BASE_URL=http://10.0.10.20:4000 \
QUERYD_LLM_API_KEY=sk-... \
QUERYD_LLM_MODEL=gpt-4.1-mini \
uv run queryd
```

### Docker Compose

Use the root `compose.yaml` (repository root) for a full dockerised stack:

```bash
# From repo root:
cp .env.example .env && vim .env                    # edit secrets
docker compose --profile bootstrap up bootstrap --abort-on-container-exit
docker compose up -d                                # TerminusDB + queryd + captured + ingestd
```

The compose file starts TerminusDB on port 6363, builds queryd from the
`Dockerfile`, and exposes it on port 8087.  See the compose header comment
for extension toggling and external-TDB overlays.

### Bootstrapping the dev database

```bash
cd ../lms-ingestd
INGESTD_TDB_URL=http://10.0.10.20:6364 \
INGESTD_TDB_DB=queryd_dev \
INGESTD_TDB_PASSWORD=root \
uv run python -m schema.bootstrap

INGESTD_TDB_URL=http://10.0.10.20:6364 \
INGESTD_TDB_DB=queryd_dev \
INGESTD_TDB_PASSWORD=root \
uv run python -m seed
```

## API reference

### `POST /v1/chat`

**Auth:** `Authorization: Bearer <token>` (required).

**Request** (`application/json`):

```json
{
  "messages": [
    { "role": "user", "content": "Was steht diese Woche an?" },
    { "role": "assistant", "content": "..." },
    { "role": "user", "content": "Und welche davon sind noch offen?" }
  ]
}
```

- `role` must be `"user"` or `"assistant"`.
- The **last** message must be from the user.
- The full history is required each turn (stateless).

**Response** (`application/json`):

```json
{
  "message": "Von den drei genannten Aufgaben sind noch alle offen: ...",
  "tool_trace": [
    {
      "tool": "graphql_query",
      "input": { "query": "{ Task { ... } }" },
      "output_summary": "1288 chars"
    }
  ]
}
```

| Status | Meaning |
|---|---|
| `200` | Success |
| `401` | Missing or invalid Bearer token |
| `422` | Empty messages or last message is not from user |
| `502` | LLM provider error or iteration budget exceeded |
| `504` | Request timed out (default 60s) |

Error shape:

```json
{ "detail": "unauthorized" }
```

### `GET /healthz`

**No auth required.**

```json
// 200 — healthy:
{ "status": "ok", "terminusdb": "up", "version": "0.1.0" }

// 503 — TerminusDB unreachable:
{ "status": "degraded", "terminusdb": "down", "version": "0.1.0" }
```

## Curl walkthrough (live, 2026-07-05)

All examples use the LLM model `gpt-4.1-mini` via the LiteLLM proxy at
`http://10.0.10.20:4000`. The seed data includes three tasks (Steuererklärung,
Urlaubsantrag, Wochenbericht) and one event (Team-Meeting Q3 Planung).

### 1. German question — what's up this week?

```bash
curl -s -X POST http://localhost:8087/v1/chat \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Was steht diese Woche an?"}]}'
```

**Response (trimmed):**

```json
{
  "message": "**Diese Woche** (KW 27) ist heute schon zu Ende — hier war nichts eingetragen.\n\nFür die **kommende Woche** (KW 28, 06.07. – 12.07.) steht Folgendes an:\n\n| Di 07.07. | Urlaubsantrag einreichen | open |\n| Mi 08.07. | Steuererklärung vorbereiten | open |\n| Fr 10.07. | Wochenbericht schreiben | planned |\n\nHinweis: Einige Aufgaben sind doppelt erfasst.",
  "tool_trace": [
    {"tool": "today", "input": {}, "output_summary": "62 chars"},
    {"tool": "graphql_query", "input": {"query": "…"}, "output_summary": "error: …"},
    {"tool": "get_schema_details", "input": {}, "output_summary": "107847 chars"},
    {"tool": "graphql_query", "input": {"query": "…"}, "output_summary": "1650 chars"}
  ]
}
```

The agent used `today()` for date context, issued a GraphQL query, self-corrected
a filter syntax error via `get_schema_details()`, and retried successfully.

### 2. Follow-up with history

```bash
curl -s -X POST http://localhost:8087/v1/chat \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role":"user","content":"Was steht diese Woche an?"},
      {"role":"assistant","content":"…[previous answer]…"},
      {"role":"user","content":"Und welche davon sind noch offen?"}
    ]
  }'
```

**Response:**

```json
{
  "message": "Von den drei genannten Aufgaben sind noch alle offen:\n\n🔴 open | Urlaubsantrag einreichen | Di 07.07.\n🔴 open | Steuererklärung vorbereiten | Mi 08.07.\n🟡 planned | Wochenbericht schreiben | Fr 10.07.\n\nErledigt ist noch keine davon.",
  "tool_trace": []
}
```

No additional tool calls — the agent answered from context.

### 3. Write attempt with writes disabled

```bash
curl -s -X POST http://localhost:8087/v1/chat \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Markiere den Urlaubsantrag als erledigt"}]}'
```

**Response (trimmed):**

```json
{
  "message": "…Leider kann ich den Status nicht auf erledigt setzen: Mir stehen aktuell nur Lese-Werkzeuge zur Verfügung. Ein Schreibzugriff ist in diesem Modus nicht möglich.",
  "tool_trace": [
    {"tool": "graphql_query", "input": {"query": "{ Task { _id name status … } }"}, "output_summary": "1288 chars"}
  ]
}
```

Only `graphql_query` in the trace — no `set_task_status`.

### 4. Write with `QUERYD_ENABLE_WRITES=true`

Restart the service with `QUERYD_ENABLE_WRITES=true`, then:

```bash
curl -s -X POST http://localhost:8087/v1/chat \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Markiere den Urlaubsantrag als erledigt"}]}'
```

**Response:**

```json
{
  "message": "Beide Tasks wurden erfolgreich auf erledigt gesetzt:\n✅ Urlaubsantrag einreichen — Task/fAgi6ATGsVfQwSeA\n✅ Urlaubsantrag einreichen — Task/yRJ7camLeK6reKIq",
  "tool_trace": [
    {"tool": "graphql_query", "input": {"query": "…"}, "output_summary": "224 chars"},
    {"tool": "get_document", "input": {"iri": "Task/yRJ7camLeK6reKIq"}, "output_summary": "273 chars"},
    {"tool": "get_document", "input": {"iri": "Task/fAgi6ATGsVfQwSeA"}, "output_summary": "302 chars"},
    {"tool": "set_task_status", "input": {"task_iri": "Task/yRJ7camLeK6reKIq", "status": "done"}, "output_summary": "ok iri=Task/yRJ7camLeK6reKIq"},
    {"tool": "set_task_status", "input": {"task_iri": "Task/fAgi6ATGsVfQwSeA", "status": "done"}, "output_summary": "ok iri=Task/fAgi6ATGsVfQwSeA"}
  ]
}
```

**Before:** `"status":"open"`, `"updated_at":"2026-07-05T10:00:00Z"`  
**After:** `"status":"done"`, `"updated_at":"2026-07-05T20:45:28Z"`

### 5. Healthz degradation

```bash
# Wrong TDB URL on a separate instance:
QUERYD_TDB_URL=http://10.0.10.20:9999 \
QUERYD_LISTEN_ADDR=0.0.0.0:8088 \
… uv run queryd

curl -s http://localhost:8088/healthz
# → {"status":"degraded","terminusdb":"down","version":"0.1.0"}  (503)
```

## Reflex integration

The frontend (a [Reflex](https://reflex.dev/) app) communicates with queryd as
a **stateless** chat backend:

**Request contract:**
- `POST /v1/chat` with `Authorization: Bearer <frontend-token>`
- Body: `{ "messages": [ … ] }` — the client sends the **entire** conversation
  history every turn; queryd does not maintain sessions.

**Response contract:**
- `message` (str): the natural-language answer, safe to render directly.
- `tool_trace` (list): ordered list of tool invocations for this turn.

**Rendering the tool trace as a debug drawer:**

Each entry in `tool_trace` has three fields:

| Field | Description |
|---|---|
| `tool` | Tool name (e.g. `graphql_query`, `set_task_status`) |
| `input` | Dict of arguments, truncated at 200 chars per value |
| `output_summary` | One-line summary: `"<N> chars"` for reads, `"ok iri=…"` for writes, `"error: …"` for failures |

Render each trace entry in a collapsible row showing `tool` + `output_summary`,
with the full `input` available on expansion.

**`ENABLE_WRITES` gating**: When `QUERYD_ENABLE_WRITES=false`, only read tools
(`graphql_query`, `get_document`, `get_schema_details`, `today`) are available.
The agent will refuse writes and the `tool_trace` will contain no mutation
tools. Toggle this to control whether the frontend can modify data.

## Extension points

### Semantic search

`src/queryd/tools.py` includes a comment placeholder for a future
`semantic_search` tool that would query a separate vector-search service:

```python
# Extension point: future vector-search / RAG tools can be appended here.
# _READ_TOOLS.append(Tool(semantic_search))  # future: vector search service plugs in here
```

When implemented, the vector service would accept natural-language queries and
return relevant document IRIs from the knowledge graph.

## Testing

```bash
uv run pytest                    # Run all tests
uv run ruff check                # Lint
uv run ruff format --check       # Check formatting
```

Tests use `pydantic-ai`'s `TestModel` and `FunctionModel` to simulate LLM
responses — no live infrastructure needed.
