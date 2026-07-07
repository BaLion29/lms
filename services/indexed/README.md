# indexed

Precision grounding service for firnline. Mirrors TerminusDB documents and schema
into a hybrid vector+lexical index (SQLite FTS5 + cosine similarity). Serves
grounded-lookup endpoints so `ingestd` and `queryd` never invent entity IRIs,
class names, or field names — preventing semantic drift in LLM-generated
writes and queries.

indexed is **read-only** over TDB and **dropoutable**: if it is unavailable,
consumers degrade to today's behaviour (casefold-exact match / raw GraphQL).
The database remains the sole source of truth.
