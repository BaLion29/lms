# Search and grounding

## Purpose

This page explains the precision grounding service (indexed) — how it prevents
LLMs from inventing entities or hallucinating schema fields by mirroring
TerminusDB documents and schema into a hybrid vector+lexical index. It is for
anyone who needs to understand how entity linking and schema grounding work,
or who is writing an indexer plugin.

## What is precision grounding?

The `indexed` service mirrors TerminusDB documents and schema into a hybrid
vector+lexical index (SQLite FTS5 + cosine similarity) and serves
precise-lookup HTTP endpoints. `ingestd` and `queryd` consume it to obtain
exact IRIs, class names, and field names — so LLMs never invent near-duplicate
entities or hallucinate schema.

indexed is **read-only** over TDB and **dropoutable**: if it is unavailable,
callers degrade gracefully to today's behaviour (casefold-exact match / raw
GraphQL). The database remains the sole source of truth.

## Architecture

```
TDB  ──► indexed (poller + HTTP within apid :8080)  ──► ingestd linker
   │         │                                 queryd find_* tools
   │         └─ sqlite file (local index)
   │
   └─ commit log (polled via /api/log)
```

One direction of trust: `indexed` only reads TDB. No write endpoints.

## How it prevents semantic drift

1. **Entity linking uses IRIs, not name guessing.** When `ingestd` extracts a
   person name that doesn't casefold-exact-match any known entity, it asks
   `indexed.find_entity`. If the top candidate scores above a configurable
   minimum confidence, the existing IRI is reused. Below threshold, a new
   entity is created — same "no guessing" rule, with real recall replacing
   the old casefold-only path.
2. **Schema grounding.** `queryd`'s agent can call `find_class` and
   `find_field` before composing GraphQL. These return only real class and
   field names from the composed schema. The agent cannot invent a field that
   doesn't exist.
3. **Instance grounding.** `find_entity` returns verified IRIs that the agent
   must then feed into `get_document` or `graphql_query`.

The full API reference — endpoint paths, request/response schemas, and
authentication — lives in the [API reference](../reference/api.md).

## Inspecting the index

The index is a local SQLite file. Its location is configurable via the
`INDEXED_DATA_DIR` environment variable — see the [configuration
reference](../reference/configuration.md) for the default path and all
index-related settings. Standard SQLite tools can inspect the `entities` and
`schema_items` tables directly:

```bash
sqlite3 /var/lib/firnline/index/index.db \
  "SELECT class, name, aliases_json FROM entities ORDER BY rowid LIMIT 20"

sqlite3 /var/lib/firnline/index/index.db \
  "SELECT kind, class, name FROM schema_items LIMIT 20"
```

Configuration for enabling indexed in ingestd and queryd (`INGESTD_INDEXED_ENABLED`,
`QUERYD_INDEXED_ENABLED`, `INDEXED_URL`) is documented under each service's
section in the [configuration reference](../reference/configuration.md).

## How entities get indexed

Extensions register `IndexerPlugin` instances under the
`firnline.indexed.indexers` entry-point group. Each plugin declares which TDB
document classes to mirror and how to extract text + aliases from each
document. At startup, `indexed` discovers all plugins, verifies their module
requirements against the `SchemaModule` registry, and skips any with unmet
requirements (WARNING log).

All first-party extensions ship indexer plugins. Adding a new extension with
`firnline.indexed.indexers` in its `pyproject.toml` automatically makes its
documents searchable — zero core changes.

For the `IndexerPlugin` protocol and the full entry-point reference, see
[entry points](../reference/entry-points.md).

## Related documents

- [Architecture](../concepts/architecture.md) — how indexed fits into the data flow
- [API reference](../reference/api.md) — indexed endpoints and request/response schemas
- [Configuration reference](../reference/configuration.md) — `INDEXED_*` settings and index file location
- [Entry points reference](../reference/entry-points.md) — `IndexerPlugin` protocol
- [Writing extensions](../guides/writing-extensions.md) — how to ship an indexer plugin
