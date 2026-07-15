# firnline — documentation

An opinionated ADHD-focused Life-Management System. Capture thoughts (text
notes, voice memos, files), let the AI extraction pipeline turn them into
linked typed documents (tasks, events, people, places, reminders, routines),
and query everything through structured GraphQL and REST endpoints. Everything
backed by a TerminusDB graph database — the single source of truth.

## Where to start

| You are … | Start here |
|---|---|
| **New here?** | → [Installation](getting-started/installation.md) → [Quickstart](getting-started/quickstart.md) |
| **Running it?** | → [Guides](guides/) — day-to-day operations, deployment, upgrades |
| **Understanding it?** | → [Concepts](concepts/) — architecture, entity model, plugin system, security |
| **Looking something up?** | → [Reference](reference/) — API docs, configuration, CLI, entry points |
| **Contributing?** | → [Development](development/) — local setup, extension authoring, testing, release process |

## Full page index

### Getting Started

| Page | Description |
|---|---|
| [Installation](getting-started/installation.md) | Prerequisites, Docker quickstart, bootstrap, verify |
| [Quickstart](getting-started/quickstart.md) | 5-minute walkthrough: capture, ingest, query, WebUI |

### Concepts

| Page | Description |
|---|---|
| [Vision](concepts/vision.md) | Entity model, design principles, ADHD-informed decisions |
| [Architecture](concepts/architecture.md) | System principles, component overview, data flow |
| [Entity Model](concepts/entity-model.md) | Core domain model: Entity, provenance, markers, modules |
| [Plugin System](concepts/plugin-system.md) | Entry-point plugin architecture across all services |
| [Actions and Trust](concepts/actions-and-trust.md) | Action model, trust ladder, execution lifecycle, idempotency |
| [Security](concepts/security.md) | Auth model, token management, external-agent access |

### Guides

| Page | Description |
|---|---|
| [Deployment](guides/deployment.md) | Production deployment guide |
| [Web UI](guides/web-ui.md) | Reflex dashboard: capture, inbox, browse, health, modules, automations, calendar |
| [Querying](guides/querying.md) | GraphQL queries, REST endpoints, cursors, write tools |
| [Installing Extensions](guides/installing-extensions.md) | Install and configure extensions |
| [Backup and Restore](guides/backup-and-restore.md) | TerminusDB volume backup, restore, and verification |
| [Schema Changes](guides/schema-changes.md) | Schema diff, planning, apply, promote, and rollback |
| [Upgrading](guides/upgrading.md) | Upgrade firnline across versions |
| [Troubleshooting](guides/troubleshooting.md) | Common issues and diagnostics |

### Reference

| Page | Description |
|---|---|
| [Configuration](reference/configuration.md) | Complete environment variable reference for all services |
| [CLI](reference/cli.md) | `firnline-schema` CLI command reference |
| [Schema Modules](reference/schema-modules.md) | Schema module format, manifest, exports, dependencies |
| [Entry Points](reference/entry-points.md) | All `firnline.*` entry-point groups and protocols |
| [API Overview](reference/api/README.md) | Service API catalog and auth model |
| [captured API](reference/api/captured.md) | Capture-ingress endpoints |
| [queryd API](reference/api/queryd.md) | GraphQL proxy, document lookup, schema introspection, write-tool endpoints |
| [indexed API](reference/api/indexed.md) | Precision grounding service: entity/class/field search |
| [mcpd API](reference/api/mcpd.md) | MCP server for external AI agents: tools, resources, configuration |

### Development

| Page | Description |
|---|---|
| [Contributing](development/contributing.md) | How to contribute to firnline |
| [Local Development](development/local-development.md) | Dev environment setup, running services without Docker |
| [Project Structure](development/project-structure.md) | Monorepo layout, package boundaries, conventions |
| [Extension Development](development/extension-development.md) | How to write a firnline extension: layout, entry points, protocols |
| [Testing](development/testing.md) | Test strategy, running tests, writing new tests |
| [Documentation](development/documentation.md) | How to contribute to these docs |
| [Release Process](development/release-process.md) | Release checklist and versioning |
| [TerminusDB Notes](development/terminusdb-notes.md) | Empirically verified TerminusDB v12 API behaviour |

### Decisions

| Page | Description |
|---|---|
| [ADR Index](decisions/README.md) | Architecture Decision Records catalog |
| [ADR-001](decisions/ADR-001-terminusdb-as-source-of-truth.md) | TerminusDB as Source of Truth |
| [ADR-002](decisions/ADR-002-entry-point-plugin-system.md) | Entry-Point Plugin System |
| [ADR-003](decisions/ADR-003-unified-capture-pipeline.md) | Unified Capture Pipeline |
| [ADR-004](decisions/ADR-004-trust-ladder-for-actions.md) | Trust Ladder for Automated Actions |
| [ADR-005](decisions/ADR-005-llm-via-litellm-proxy.md) | LLM Access via LiteLLM Proxy |
| [ADR template](decisions/template.md) | ADR template |

### Meta

| Page | Description |
|---|---|
| [Roadmap](roadmap.md) | Upcoming features and aspirational ideas |
| [FAQ](faq.md) | Frequently asked questions |
| [Changelog](../CHANGELOG.md) | Release history and notable changes |
