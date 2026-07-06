# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.1.0-alpha] - 2026-07-06

### Added

- Initial alpha release of the firnline project (renamed from former working
  name "lms").
- Monorepo layout: `firnline-core` shared domain library, `firnline-schema`
  schema toolchain CLI, `captured` capture-ingress daemon, `ingestd` AI
  ingestion polling worker, `queryd` conversational agent service.
- Six first-party extensions: inbox, people, places, planning, reminders,
  routines — each providing schema modules, capture handlers, ingest
  extractors, or queryd tools via the plugin architecture.
- Schema module system with `compose`, `diff`, `plan`, `apply`, `validate`,
  `promote`, and `codegen` CLI commands.
- Plugin architecture via Python entry points (`firnline.schema_modules`,
  `firnline.captured.handlers`, `firnline.ingestd.sources`,
  `firnline.ingestd.extractors`, `firnline.queryd.tools`).
- Docker Compose deployment with bundled and external TerminusDB profiles,
  bootstrap service for schema initialization, and extension management.
- Registry classes (`SchemaModule`, `SchemaMigration`) for tracking installed
  schema modules and applied migrations.
