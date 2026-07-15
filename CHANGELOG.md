# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **`firnline-ext-time-management` merges planning + routines.** The
  `firnline-ext-planning` and `firnline-ext-routines` extensions are combined
  into a single `time_management` schema module (9 classes: Task, TaskSpec,
  Event, TaskStatus, EventStatus, Routine, RoutineStep, Activity, ActivitySpec).
  Schema improvements: `ActivitySpec` gains `priority` and `estimated_duration`
  (mirroring TaskSpec); `Activity` gains a `routine` back-reference to `Routine`.
  The new extension provides three entry points — `firnline.schema_modules`
  (`time_management`), `firnline.ingestd.extractors`
  (`time_management_extractor` covering routines/activities in addition to
  task/event/person extraction), and `firnline.queryd.tools`
  (`time_management_tools` with `create_routine`, `update_routine`, and
  `log_activity`). The old extensions are removed. Extension migration
  discovery is now supported in `firnline-schema`.

- **Marker grammar refactored.** `Source`, `Context`, and `Anchored` are now all
  pure role markers. `Anchored` no longer carries `anchor_at`; concrete classes
  implementing it declare `@metadata.anchor_field` at the class level. Relative
  triggers with an unset anchor field are dormant — evaluators skip them
  explicitly (triggerd logs `trigger_dormant`).
- **`Remindable` removed from core.** Reminders are an extension concern;
  extensions use `Triggerable` (from triggers) or define their own markers.
- **`created_at` / `updated_at` removed from Entity base.** Timestamps on
  documents are obsolete — provenance (`prov`) metadata and the TerminusDB
  commit-graph cover creation and update tracking. All schema, models,
  production code, and tests updated. Sorting in effectd now uses document
  `@id` (deterministic). Ingestd merge identity keys use `@id`, `@type`,
  `provenance` only.
- **Provenance layering.** `Entity.provenance` is now REQUIRED (exactly one) —
  the birth certificate (agent, at, method, confidence). `Provenance.source` is
  gone; multi-source derivation lives in `Entity.derived_from: Set<Source>`
  (n-ary). The commit graph is the biography — updates are attributed there.
- **Agent naming grammar** reserved: `service:<name>`, `user:<name>`,
  `ext:<name>` (helpers `agent_id`/`parse_agent` in `firnline_core`).
- **Entity affordances**: `archived_at` soft-delete tombstone; `@metadata.label_field`
  required on exported concrete Entity subclasses (composer L4); kernel
  `Tag(name) implements Context` for frictionless cross-extension tagging.
- **Capture module replaces inbox.** Single `Captured(Entity, Source)` class
  (content_type, content, blob_sha256, file_name, captured_at, transcription,
  status). Kernel modules are now core + capture + triggers.
- **Plugin system upgraded.** `SchemaModule` registry carries `exports` (class
  @ids, written at install). Plugins may declare `requires_classes` in addition
  to `requires`; checked against registry exports at startup. All services
  boot through shared `PluginHost` with declarative `HostPolicy`.
- **queryd structured API**: new bearer-authed endpoints — `GET /v1/schema`,
  `GET /v1/schema/introspection`, `GET /v1/modules`, `GET /v1/documents/{iri}`,
  `POST /v1/graphql`, `POST /v1/find/{entity,class,field}`.
- **WebUI inbox page** now backed by `Captured` class.
- **notifyd renamed to effectd.** Service name, settings prefix (`EFFECTD_`),
  liveness file, and compose service block all use the new name. The old
  `NOTIFYD_` prefix and `notifyd` container name are fully removed.
- **Durations promoted to firnline_core.** The ISO-8601 duration parser
  (`parse_duration`) and datetime parser (`parse_iso_datetime`) moved from
  individual services into firnline_core so executor extensions can consume
  them without depending on service internals.
- **webui: indexed health card** now shows `store` and `poller` health fields;
  absent fields (indexed has no version/plugins) render as "—". Optional bearer
  auth for indexed healthz via `WEBUI_INDEXED_API_TOKEN`.
- **webui: internal cleanup.** Shared client factories, shared feedback UI
  helpers (error/empty/loading), healthz parsing updated to services' current
  flat response shape, previously swallowed exceptions now logged.

### Added

- **`actions` kernel schema module.** Introduces the `Action` hierarchy
  (`WebhookAction`, `NotifyAction`), `ActionExecution` (idempotent execution
  records with Lexical key on `[action, firing]`), `ActionMode` trust ladder
  (`dry_run → approval → auto`), and `ExecutionStatus` lifecycle with metadata
  transitions.
- **effectd action engine.** Plan/execute phases over `ActionExecution`
  documents: planner enumerates (action, firing) pairs and materialises
  executions; executor picks up pending executions, resolves the matching
  `ActionExecutor` plugin, invokes it with timeout, and persists outcomes
  through retry/backoff/dead-letter. Idempotency key is
  `<short-action-iri>#<short-firing-iri>`.
- **Trust ladder for actions.** `dry_run` records skipped executions;
  `approval` (default) requires human transition `pending_approval → pending`
  before execution; `auto` opts in to immediate execution because side effects
  are not revertible.
- **New entry-point group `firnline.effectd.executors`.** Canonical
  `ActionExecutor` protocol: `name`, `requires`, `kinds`, and an async
  `execute(action, firing, subject, ctx) → ExecutionResult` method.
- **firnline-ext-webhook** — reference `ActionExecutor` that calls arbitrary
  HTTP endpoints with template-rendered payloads, idempotency-key headers,
  and optional bearer auth.
- **Gotify native ActionExecutor.** `firnline-ext-gotify` now registers a
  native executor with kind `notify:gotify` alongside its legacy channel
  entry point.
- **mcpd** — new service exposing firnline to external AI agents via Model
  Context Protocol (streamable HTTP). Tools: graphql_query, get_document,
  find_entity/class/field, get_schema, list_modules, capture. Resources:
  firnline://schema, firnline://schema/introspection, firnline://modules.
  Talks to queryd+captured over HTTP (no direct DB access).
- `@metadata` composer validation L4 (label_field) and L5 (anchor_field).
- **webui: Automations page** at `/automations`. Read-only listing of
  `TriggerFiring` and `ActionExecution` documents from TerminusDB with status
  filters, colored status badges, pending/awaiting-approval summary counts, and
  a JSON detail drawer. Degrades gracefully when the triggers/actions schema
  modules are not installed.
- **webui: mcpd health monitoring.** The health page and home dashboard now
  include mcpd status. New env var `WEBUI_MCPD_URL` (default
  `http://mcpd:8090`).
- **webui: Responsive/mobile layout.** Sidebar collapses into a
  hamburger-triggered drawer below the `md` breakpoint; main content goes
  full-width on small screens.
- **webui: Accessibility.** Aria-labels on all icon-only buttons, `role="main"`
  on content area, `aria-current` on the active nav link, keyboard-focusable
  table rows.

### Deprecated

- **`firnline.notifyd.channels` entry-point group.** Legacy channel plugins
  are auto-adapted to executors with kind `notify:<name>` via
  `ChannelExecutorAdapter` at effectd startup. Migrate to
  `firnline.effectd.executors`. The legacy group will be removed after one
  release cycle.
- **`NotificationChannel`, `DeliveryResult`, `NotifyContext`** — aliased
  respectively to `ActionExecutor`, `ExecutionResult`, `ActionContext`.
  Existing channel implementations continue to work; new executors should
  use the canonical names directly.

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
