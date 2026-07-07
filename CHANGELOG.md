# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-07

### Changed

- Clean re-baseline for 0.1.0 release.
- Kernel/extension split enforced — schema modules and handlers now live in kernel
  packages, extensions only provide third-party integrations.
- Per-package generated models replace hand-written Pydantic models across all
  firnline libraries.
- Core schema: Entity base class with Provenance tracking (created_at,
  updated_at, provenance — no derived_from).
- Triggerable and Anchored marker classes for structured document time handling.
- notifyd notification delivery daemon with gotify channel extension.
- Inbox schema module (InboxNote, InboxAudio) absorbed into kernel
  (schema/modules/inbox/); capture handlers moved to captured, ingest sources to
  ingestd.
- ContextTrigger removed — replaced by ScheduleTrigger, OneShotTrigger, and
  TriggerFiring documents handled by triggerd.
- firnline-core client now exposes a change-feed API for polling services.
- All package versions reset to 0.1.0.

### Added

- New `firnline-webui` service — Reflex 0.9.x web dashboard at `services/webui/`.
  Seven introspection-driven pages: Dashboard, Capture (note + file), Inbox
  (auto-discovers Inbox* classes), Browse (generic class browser grouped by
  SchemaModule), Health (per-service healthz + plugin lists), Modules (schema
  module registry + active plugins), and Login (optional password gate).
  Plug-and-play design — any current or future firnline extension automatically
  appears in the UI without code changes.
- Docker Compose `webui` service block, two-stage Dockerfile, `.env.example`
  entries (`WEBUI_*`), and Reflex healthcheck with `start_period: 120s`.
- Triggers schema module relocated from `firnline-ext-reminders` to first-party
  `schema/modules/triggers/`.
- Triggers module 1.1.0: added `OneShotTrigger`, `TriggerFiring`, `FiringStatus`,
  `ScheduleTrigger.timezone`.
- New `triggerd` service — polling daemon that evaluates Trigger documents via
  pluggable evaluator plugins and materializes `TriggerFiring` records.
- New entry-point group `firnline.triggerd.evaluators` with `TriggerEvaluator`
  protocol.
- Reminders extractor now proposes `fire_at` → creates `Reminder` +
  `OneShotTrigger`.
- Liveness-file healthchecks for `ingestd` and `triggerd`
  (`INGESTD_LIVENESS_FILE` / `TRIGGERD_LIVENESS_FILE`).
- `triggerd` Docker image, compose service block, `.env.example` entries, and
  documentation coverage.

### Fixed

- Extension test files renamed to prevent shadowing in root `pytest` runs.

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
