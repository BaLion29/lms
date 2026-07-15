# ADR-001: TerminusDB as primary store

> **Note:** Backfilled from vision documentation; decision predates this record.

## Status

Accepted

## Date

2026-07-15

## Context

The system needs a single source of truth (SSOT) that can model an ADHD brain's
natural associations — things connected to people, places, events, and contexts
in multiple overlapping ways. At the same time, every mutation must be
attributed, auditable, and revertible, because AI agents will write documents
autonomously and trust must be gated on review.

A relational database would force joins across a web of associations that are
better expressed as a graph. A document store would lose the rich linking. A
plain RDF triple store would lack the schema enforcement needed to keep AI
outputs well-shaped.

## Decision

Use **TerminusDB** (v12) as the sole database — the single integration point
between all services. TerminusDB provides:

- **Graph/document model**: documents (entities) connected by edges, matching
  the mental model of "a task linked to a person, a location, and a context."
- **Schema enforcement**: every document is validated against a composed JSON
  schema before commit, ensuring AI-generated data and hand-written data stay
  consistent.
- **Branching**: commits land on branches; promotion to `main` is the trust
  boundary. Dry-run and staging-branch workflows are first-class.
- **Commit graph**: every write is a distinct commit with author and message.
  The commit graph is the audit trail — the "biography" of every document.
  Reverts are possible.
- **Change feed**: polling services (`indexed`, `triggerd`) consume the commit
  log to react to new documents without push-based coupling.

All database access goes through `firnline-core`'s typed async HTTP client
(`tdb.py`). No service talks to TerminusDB with raw ad-hoc code.

## Alternatives considered

- **PostgreSQL + JSONB** — mature, widely understood. Rejected because the
  graph model maps poorly to relational queries, and branching/commit-graph
  semantics would need to be built from scratch.
- **Neo4j** — strong graph model, no native schema enforcement at document
  level. Would require building a schema validation layer and a branching
  model on top.
- **Plain RDF triple store (e.g. Apache Jena)** — full semantic web stack,
  but complex tooling, no built-in branching, and schema enforcement is
  optional at best.
- **SurrealDB** — multi-model with graph edges, but schema enforcement and
  branching maturity were not verified at decision time.

## Consequences

- **Easier**: rich linked-data queries (GraphQL over the graph), audit trail
  from commit history, branching for AI trust workflows, schema enforcement
  catches malformed AI output before it lands.
- **Harder**: operational knowledge of TerminusDB required (v12 REST API,
  WOQL for advanced traversals). The async HTTP client abstraction in
  `firnline-core` encapsulates this, but debugging still needs TDB fluency.
- **Constraint**: every service must go through the `firnline-core` client;
  direct DB access by new services is forbidden.

## References

- [Architecture](../concepts/architecture.md)
- [Vision](../concepts/vision.md)
- [TerminusDB Notes](../reference/terminusdb-notes.md)
