# indexed

Precision grounding service for Firnline. Hybrid vector + lexical search
sidecar (SQLite FTS5 + cosine similarity) that mirrors TerminusDB documents
and schema so downstream consumers don't invent entity IRIs, class names, or
field names — preventing semantic drift in LLM-generated queries and writes.

indexed is read-only over TDB and gracefully degradable: if unavailable,
consumers fall back to casefold-exact match or raw GraphQL.

## Further reading

- [Search & Grounding](../../docs/concepts/search-and-grounding.md)
- [API Reference](../../docs/reference/api.md)
- [Configuration](../../docs/reference/configuration.md)
