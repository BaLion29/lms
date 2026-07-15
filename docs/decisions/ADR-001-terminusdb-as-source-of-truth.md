# ADR-001: TerminusDB as Source of Truth

**Status:** Accepted (recorded retroactively)

**Date:** 2026-07-15

## Context

Firnline is an ADHD-focused life-management system. Its core premise is a
*single source of truth* for everything — tasks, events, reminders, people,
locations, captured items. The data model is fundamentally a graph:
thoughts have multiple contexts simultaneously, entities are linked through
typed relationships, and every document must carry a traceable provenance
chain back to its origin.

The database must support:
- Strong schema enforcement (documents must conform to declared types).
- Graph queries (multi-hop relationships, not flat tables).
- Versioned history / audit trail (every write is attributable and revertible).
- Branching (schema changes can be staged and reviewed before hitting production).
- Schema-as-code (composable, versioned module fragments that can ship with
  extensions).

## Decision

**TerminusDB v12.0.6** is the single database for all firnline data. Every
service reads and writes exclusively through TerminusDB. There is no
caching layer, no secondary database, no message queue. The database *is*
the integration point.

Key properties relied upon:
- **Schema validation at push time** — TerminusDB rejects schema updates
  that would violate existing instance data, giving a clear go/no-go signal.
- **Branching for schema changes** — the `firnline-schema` toolchain
  applies schema to a staging branch first; promotion to main is the
  acceptance gate.
- **Commit graph** — every write is a distinct commit with author,
  timestamp, and message. AI writes are attributable and individually
  revertible. The commit graph is the biography — updates are tracked
  there, not on the document.
- **Document graph + WOQL** — entities link through IRIs (`Trigger → Action`,
  `Task → Context`, `Captured → derived Entity`), enabling graph queries
  and n-ary relationships without JOINs.

## Alternatives considered (reconstructed)

| Alternative | Why rejected |
|---|---|
| **PostgreSQL + SQLAlchemy/Prisma** | Relational model forces JOIN-based graph traversal. Schema changes require phased migrations (no push-time validation). No built-in commit-graph audit trail. Multiple tables lose the "single graph" mental model. |
| **SQLite** | Single-writer limitation incompatible with concurrent pollers (ingestd, triggerd, effectd, indexed). No native graph support, branching, or schema-as-code composability. |
| **MongoDB or other document stores** | Schema-optional by default — would require building schema enforcement and validation tooling from scratch. No branching or commit-graph semantics. Document-linking via manual reference fields loses graph-query ergonomics. |
| **Neo4j or other graph-only DBs** | Strong on graph queries, but lack schema-first enforcement and document-graph duality (TerminusDB is both). Would need a separate schema management layer. |

## Consequences

- **Easier:** Schema and data live in one place; extensions contribute schema
  modules that compose declaratively. The commit graph provides free audit
  logging, reversibility, and staging-branch review. Graph queries match the
  ADHD association model naturally.
- **Harder:** TerminusDB is not a general-purpose RDBMS — ad-hoc analytics,
  reporting, or external BI tooling need to go through the GraphQL/HTTP API
  rather than direct SQL. The v12 API surface has quirks that require
  empirical documentation (see terminusdb-notes).
- **Operational:** Backups are volume snapshots (not pg_dump). Branch-promote
  is the schema deployment mechanism. All services share the same TDB
  connection surface.

## References

- [Vision](../concepts/vision.md) — SSOT, commit graph as biography
- [Architecture](../concepts/architecture.md) — Principles, schema module system
- [Backup and Restore](../guides/backup-and-restore.md)
- [TerminusDB Notes](../development/terminusdb-notes.md)
