# firnline — documentation

An opinionated ADHD-focused Life-Management System that captures thoughts
(text notes, voice memos, files), runs them through AI extraction pipelines
to turn unstructured input into linked, typed documents (tasks, events,
address book (people, organizations, locations), reminders, routines), and stores everything in a TerminusDB
graph database — the single source of truth.

- **[Getting Started](getting-started.md)** — prerequisites, Docker quickstart,
  first capture, and local development setup.
- **[Architecture](architecture.md)** — system principles, component overview,
  data flow, schema module system, and plugin mechanism.
- **[Configuration](configuration.md)** — complete environment variable reference
  for all services.
- **[Actions](actions.md)** — action model, trust ladder, execution lifecycle,
  idempotency, template variables, effectd settings, and a worked Home
  Assistant webhook example.
- **[Extensions](extensions.md)** — how to write and install a firnline
  extension: package layout, entry-point groups and protocols, schema module
  format, `@metadata` keys, and a worked example.
- **[mcpd](mcpd.md)** — MCP server for external AI agents: tools, resources,
  and configuration.
- **[Operations](operations.md)** — production runbook: backup, schema
  diff/plan/apply, validation, promote, and rollback.
- **[TerminusDB API Notes](terminusdb-notes.md)** — empirically verified
  TerminusDB v12 API behaviour (schema push, branching, promote, GraphQL).
- **[WebUI](webui.md)** — Reflex dashboard: capture, inbox, generic browser,
  service health, and schema module inspection.
- **[Vision](vision.md)** — entity model, design principles, ADHD-informed
  decisions, and the extensibility promise.
