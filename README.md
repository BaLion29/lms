# firnline

[![v0.1.0-alpha](https://img.shields.io/badge/version-0.1.0--alpha-blue)](CHANGELOG.md)
[![Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

An opinionated ADHD-focused life-management system. Capture thoughts (text
notes, voice memos, files), let the AI extraction pipeline turn them into
linked typed documents (tasks, events, people, places, reminders, routines),
and query everything through structured GraphQL and REST endpoints. Backed by a
TerminusDB graph database — the single source of truth.

## Features

- **Frictionless capture** — text notes and voice memos arrive via REST
  endpoints in under 5 seconds.
- **AI extraction pipeline** — `ingestd` polls captured items, runs LLM
  extraction, and materializes typed entities with full provenance.
- **Typed graph data** — everything lives as connected documents in
  TerminusDB: tasks, events, reminders, people, places, routines.
- **GraphQL and REST APIs** — structured read/write endpoints, entity search,
  and schema introspection via `queryd`.
- **MCP server for AI agents** — `mcpd` exposes firnline tools and resources
  to external AI agents via Model Context Protocol.
- **Plugin/extension system** — schema modules, extractor plugins, and tool
  plugins ship as one installable package.
- **Trigger-to-action automations** — `triggerd` and `effectd` evaluate triggers
  and deliver effects through pluggable channels.
- **Web dashboard** — Reflex WebUI with capture, inbox, document browser, and
  health monitoring.

## Quickstart

```bash
git clone https://github.com/davidsouther/firnline.git
cd firnline
cp .env.example .env && vim .env      # set the 4 required values
docker compose up -d                   # bootstrap auto-runs, then all services
```

```bash
curl -s -X POST http://localhost:8080/v1/capture/note \
  -H "Authorization: Bearer $CAPTURED_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy milk on the way home", "kind": "note"}'
```

Port 8080 (API) and 3000 (WebUI). Full walkthrough:
[docs/getting-started/quickstart.md](docs/getting-started/quickstart.md).

## Documentation

All docs live under [`docs/`](docs/) — start at the
[docs hub](docs/README.md).

- [Installation](docs/getting-started/installation.md) — set up a local stack
- [Quickstart](docs/getting-started/quickstart.md) — first capture and query
- [Architecture](docs/concepts/architecture.md) — components, data flow, plugins
- [Configuration reference](docs/reference/configuration.md) — every env var
- [Writing extensions](docs/guides/writing-extensions.md) — build an extension

## Development

```bash
uv sync
uv run pytest          # all tests (no network required)
uv run ruff check      # lint
uv run ruff format     # format
```

See [docs/development/local-development.md](docs/development/local-development.md)
for a full dev-environment setup guide, and
[docs/development/project-structure.md](docs/development/project-structure.md)
for the monorepo layout.

## License

Apache-2.0 — see [LICENSE](LICENSE).
