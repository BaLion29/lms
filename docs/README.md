# firnline — Documentation

firnline is an ADHD-focused life-management system: capture text, voice, and
files with minimal friction; let AI extract and link them into typed documents
(Tasks, Events, Reminders, People); query everything through GraphQL and REST
APIs; and store it all in a versioned, branchable TerminusDB graph backend
where every change is traceable and revertible.

## Start here

- [Installation](getting-started/installation.md) — set up firnline on your machine
- [Quickstart](getting-started/quickstart.md) — capture your first item and see it land in the graph

## Doc tiers

### Concepts — why things work

| Page | Description |
|---|---|
| [Vision](concepts/vision.md) | Why firnline exists and the ADHD-first design principles |
| [Architecture](concepts/architecture.md) | Service topology, data flow, and inter-component contracts |
| [Data model](concepts/data-model.md) | Entity hierarchy, markers (Source, Context, Anchored), schema modules |
| [Actions](concepts/actions.md) | The action engine: triggers, executors, and the firing pipeline |
| [Search & grounding](concepts/search-and-grounding.md) | How queryd uses indexed mirrors to keep agents honest |

### Guides — task-oriented how-tos

| Page | Description |
|---|---|
| [Deployment](guides/deployment.md) | Run firnline in production with Docker Compose |
| [Schema changes](guides/schema-changes.md) | Add a field, class, or module; diff, plan, apply, promote |
| [Backup & restore](guides/backup-and-restore.md) | TerminusDB backups, disaster recovery, branch surgery |
| [Writing extensions](guides/writing-extensions.md) | Ship a schema module + extractor + tools as one installable package |
| [Automations](guides/automations.md) | Configure triggerd, effectd, and custom action executors |
| [Web UI](guides/webui.md) | Run and customise the Reflex frontend |
| [Publishing images](guides/publishing-images.md) | Build and push Docker images to Docker Hub |

### Reference — exhaustive technical facts

| Page | Description |
|---|---|
| [Actions](reference/actions.md) | Action field reference, template variables, and secrets rule |
| [Configuration](reference/configuration.md) | Every env var, default, and constraint (single source of truth) |
| [API](reference/api.md) | GraphQL and REST endpoint reference with request/response examples |
| [CLI](reference/cli.md) | firnline-schema and service CLIs: commands, flags, subcommands |
| [Entry points](reference/entry-points.md) | Plugin discovery, protocols, and the HostPolicy contract |
| [MCP](reference/mcp.md) | Model Context Protocol interface: tools, resources, and transport |
| [TerminusDB notes](reference/terminusdb-notes.md) | WOQL patterns, branching model, commit-graph conventions |

### Development — contributing to firnline

| Page | Description |
|---|---|
| [Local development](development/local-development.md) | Repo setup, dev loop, running services locally |
| [Project structure](development/project-structure.md) | Monorepo layout, package map, dependency graph |
| [Release process](development/release-process.md) | Versioning, changelog, melt test, publishing |
| [Documentation guidelines](development/documentation-guidelines.md) | How docs are authored, reviewed, and kept current |

## Design decisions

Architecturally significant choices are recorded as ADRs in
[decisions/README.md](decisions/README.md). Each ADR captures the context, the
decision, alternatives considered, and consequences.

## Roadmap

From the [vision](concepts/vision.md), work not yet implemented:

- **Nag-policy consolidation** — reimplement renotify/expire/snooze on top of
  ActionExecution documents
- **Routine engine** — Routines spawning Tasks/Activities from their steps
- **Branch review tooling** — comfortable per-commit review + promote flow
- **Transcriber service** — first-class replacement for the n8n STT hop
- **Time-Block & Schedule**, **TimeLog**, **Location-based reminders**,
  **Escalation chains**
