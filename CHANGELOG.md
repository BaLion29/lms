# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
for its schema modules.  Service packages (`lms-core`, `lms-schema`, `ingestd`,
`queryd`) use the monorepo version.

## [Unreleased]

### Added

- **Monorepo merge**: `lms-core`, `ingestd`, and `queryd` merged into a single
  `uv` workspace monorepo under `/home/basti/lms`.
- **Schema module system**: split the monolithic schema into composable
  fragments under `schema/modules/` (core, inbox, planning, people, routines).
- **`lms-schema` CLI**: `compose` (topological composition + lock file), `diff`
  (fragment and live-instance diffs with semver guardrails), `codegen`
  (Pydantic model generation from composed schema).
- **Registry classes** (`core` 1.1.0): `SchemaModule` and `SchemaMigration`
  lexical-key classes for tracking installed modules and applied migrations.
- **`lms-schema` branch operations**: `plan` (dry-run preview), `apply`
  (idempotent schema push + migration run + registry upsert on a branch),
  `validate` (GraphQL smoke tests + registry/lock cross-check), `promote`
  (safe fast-forward of main with ancestry verification).

### Placeholder

Steps 3–5 of the migration rollout will get their own entries when shipped:

- **Step 3** (dev): compose/diff/codegen equivalence proofs and ported golden tests.
- **Step 4** (dev): registry classes, plan/apply/validate/promote against dev instance.
- **Step 5** (production bootstrap): first production touch — backup, apply,
  validate, promote. Runbook: `docs/production-bootstrap.md`.
