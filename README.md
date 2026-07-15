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
cp .env.example .env && vim .env      # set TDB_URL + secrets
docker compose --profile bootstrap up bootstrap --abort-on-container-exit
docker compose up -d
```

The stack starts on ports 8087 (queryd), 8088 (captured), 8089 (indexed),
8090 (mcpd), and 3000 (WebUI — visit <http://localhost:3000> for the Reflex dashboard).

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

List available write tools:

```bash
curl -s http://localhost:8087/v1/tools \
  -H "Authorization: Bearer $TOKEN"
```

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
| `compose.yaml` | Docker Compose deployment (external TerminusDB) |
| `compose.bundled-tdb.yaml` | Overlay adding a bundled TerminusDB v12 container |

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
