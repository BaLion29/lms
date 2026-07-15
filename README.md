# firnline

[![v0.1.0-alpha](https://img.shields.io/badge/version-0.1.0--alpha-blue)](CHANGELOG.md)
[![Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

An opinionated ADHD-focused Life-Management System. Capture thoughts (text
notes, voice memos, files), let the AI extraction pipeline turn them into
linked typed documents (tasks, events, people, places, reminders, routines),
and query everything through structured GraphQL and REST endpoints. Everything backed by a
TerminusDB graph database — the single source of truth.

## Quickstart

```bash
git clone https://github.com/davidsouther/firnline.git
cd firnline
cp .env.example .env && vim .env      # set the 4 required values
docker compose up -d                   # bootstrap auto-runs (idempotent), then all services
```

The bootstrap service waits for TerminusDB, creates the database (if missing),
applies the schema, and installs extensions — all idempotent, so re-running is
safe.

Services available after startup:

| Service | Port | Purpose |
|---|---|---|
| WebUI | `:3000` | Reflex dashboard — <http://localhost:3000> |
| captured | `:8088` | Capture-ingress API (`POST /v1/capture/note`) |
| queryd | `:8087` | GraphQL read proxy + document lookup (`POST /v1/graphql`) |
| indexed | `:8089` | Precision grounding / entity search |
| mcpd | `:8090` | MCP server for external AI agents |

Check health: `docker compose ps` shows health states; `docker compose logs bootstrap`
for bootstrap output.

Then capture a note:

```bash
curl -s -X POST http://localhost:8088/v1/capture/note \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy milk on the way home", "kind": "note"}'
```

Query your data (GraphQL):

```bash
curl -s -X POST http://localhost:8087/v1/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ Task { id name done } }"}'
```

Bring your own TerminusDB or LLM?  See [docs/getting-started.md](docs/getting-started.md) —
instructions for removing the bundled TerminusDB block and for running a
LiteLLM proxy inside Docker (commented-out block in compose.yaml).

Full guide: [Installation](docs/getting-started/installation.md) and [Quickstart](docs/getting-started/quickstart.md).

## Repository layout

| Directory | Description |
|---|---|
| `packages/firnline-core/` | Shared library: TerminusDB client, models, plugin protocols |
| `packages/firnline-schema/` | Schema CLI: compose, diff, apply, codegen |
| `services/captured/` | Capture-ingress daemon (`POST /v1/capture/note`, `/v1/capture/file`) |
| `services/ingestd/` | AI ingestion polling worker (LLM extraction + entity linking) |
| `services/indexed/` | Search index sidecar: entity and schema lookup over TerminusDB (SQLite + embeddings) |
| `services/queryd/` | GraphQL read proxy + document lookup, find/entity|class|field, schema introspection, write-tool endpoints |
| `services/mcpd/` | MCP server — exposes firnline to external AI agents via Model Context Protocol |
| `services/triggerd/` | Trigger evaluation daemon (poll → evaluate → insert TriggerFiring) |
| `services/effectd/` | Effect delivery daemon (pending firing → channel delivery → nag policy) |
| `services/webui/` | Reflex WebUI: capture, inbox (Captured), generic browser, health, modules |
| `extensions/` | First-party extensions (gotify, people, places, time-management, reminders, webhook) |
| `schema/modules/core/` | Kernel schema module (Entity, markers, registry, provenance) |
| `schema/modules/triggers/` | Kernel schema module (abstract Trigger and concrete trigger types) |
| `schema/modules/capture/` | Kernel schema module (Captured) |
| `schema/modules/actions/` | Kernel actions schema module |
| `docker/` | Entrypoint script for extension overlay management |
| `compose.yaml` | Docker Compose deployment (bundled TerminusDB included, removable) |

## Documentation

All docs live under [`docs/`](docs/) — start with the [documentation hub](docs/README.md).

Key entry points:

| Page | Covers |
|---|---|
| [Installation](docs/getting-started/installation.md) | Prerequisites, Docker quickstart, bootstrap, verify |
| [Quickstart](docs/getting-started/quickstart.md) | 5-minute walkthrough: capture, ingest, query, WebUI |
| [Architecture](docs/concepts/architecture.md) | Principles, components, data flow, module/plugin system |
| [Configuration reference](docs/reference/configuration.md) | Complete environment variable reference |
| [Extension development](docs/development/extension-development.md) | Writing extensions: protocols, layout, entry points, @metadata |
| [FAQ](docs/faq.md) | Frequently asked questions |

## Development

```bash
uv sync
uv run pytest          # all tests (no network required)
uv run ruff check      # lint
uv run ruff format     # format
```

## License

Apache-2.0 — see [LICENSE](LICENSE).
