# indexed

Precision **grounding** service for firnline. Mirrors TerminusDB documents
and schema into a hybrid vector+lexical index (SQLite FTS5 + cosine
similarity) and serves precise-lookup HTTP endpoints. `ingestd` and
`queryd` consume it to obtain exact IRIs, class names, and field names —
so LLMs never invent near-duplicate entities or hallucinate schema.

indexed is **read-only** over TDB and **dropoutable**: if it is
unavailable, callers degrade gracefully to today's behaviour
(casefold-exact match / raw GraphQL). The database remains the sole
source of truth.

## Architecture

```
TDB  ──► indexed (poller + HTTP :8089)  ──► ingestd linker
   │         │                                 queryd find_* tools
   │         └─ sqlite file (/var/lib/firnline/index/index.db)
   │
   └─ commit log (polled via /api/log)
```

One direction of trust: `indexed` only reads TDB. No write endpoints.

## How it prevents semantic drift

1. **Entity linking uses IRIs, not name guessing.** When `ingestd`
   extracts a person name that doesn't casefold-exact-match any known
   entity, it asks `indexed.find_entity`.  If the top candidate scores
   above `INGESTD_INDEXED_MIN_CONFIDENCE` (default `0.85`), the
   existing IRI is reused.  Below threshold, a new entity is created —
   same "no guessing" rule, with real recall replacing the old
   casefold-only path.
2. **Schema grounding.** `queryd`'s agent can call `find_class` and
   `find_field` before composing GraphQL.  These return only
   real class and field names from the composed schema.  The agent
   cannot invent a field that doesn't exist.
3. **Instance grounding.** `find_entity` returns verified IRIs that
   the agent must then feed into `get_document` or `graphql_query`.

## API

All endpoints are optionally protected by `INDEXED_API_TOKEN` (bearer).

```
POST /v1/find_entity
  { "text": "Anna", "classes": ["Person"], "branch": "main", "k": 5 }
→ { "candidates": [{"iri":"Person/abc","class":"Person","name":"Anna Meier","aliases":["Anna Meier"],"score":0.91}], "commit_id": "..." }

POST /v1/find_class
  { "text": "reminder about a person", "k": 5 }
→ { "candidates": [{"class":"Reminder","description":"A reminder about a task or event","score":0.86}] }

POST /v1/find_field
  { "text": "when is it due", "class": "Task", "k": 5 }
→ { "candidates": [{"class":"Task","field":"due_date","type":"xsd:dateTime","description":"","score":0.88}] }

GET  /healthz
→ 200 if last poll cycle succeeded within 5 minutes; 503 otherwise
```

## Enabling / disabling

### Ingestd

Set `INGESTD_INDEXED_ENABLED=true` and `INDEXED_URL=http://indexed:8089`
(via the compose file).  When disabled (`false`, default), entity
linking falls back to casefold-exact match only.

### Queryd

Set `QUERYD_INDEXED_ENABLED=true`.  When disabled, the `find_*` tools
return `"ERROR: index unavailable"` and the agent is instructed to fall
back to `get_schema_details` + `graphql_query`.

## Inspecting the index

The sqlite file lives at `INDEXED_DATA_DIR` (default
`/var/lib/firnline/index/index.db`):

```bash
sqlite3 /var/lib/firnline/index/index.db \
  "SELECT class, name, aliases_json FROM entities ORDER BY rowid LIMIT 20"

sqlite3 /var/lib/firnline/index/index.db \
  "SELECT kind, class, name FROM schema_items LIMIT 20"
```

## How entities get indexed

Extensions register `IndexerPlugin` instances under the
`firnline.indexed.indexers` entry-point group.  Each plugin declares
which TDB document classes to mirror and how to extract text + aliases
from each document.  At startup, `indexed` discovers all plugins,
verifies their module requirements against the `SchemaModule` registry,
and skips any with unmet requirements (WARNING log).

All six first-party extensions ship indexer plugins.  Adding a new
extension with `firnline.indexed.indexers` in its `pyproject.toml`
automatically makes its documents searchable — zero core changes.
