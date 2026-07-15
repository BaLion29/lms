# Local development

## Purpose

This page covers setting up a local development environment for firnline —
prerequisites, running services outside Docker, tests, linting, and the
Docker Compose dev loop.

## Prerequisites

- **Python 3.12+** — the workspace requires `>=3.12` (see root
  `pyproject.toml`).
- **uv** — the project uses [uv](https://docs.astral.sh/uv/) for dependency
  management and task running. Workspace members are declared under
  `[tool.uv.workspace]`.

### Optional: Nix shell

If you use Nix, `shell.nix` provides a development shell with Python 3.12 and
uv:

```bash
nix-shell
```

The shell hook prints a reminder to run `uv sync && uv run pytest`.

## Setup

```bash
uv sync --all-packages
```

This installs all workspace members (packages, services, extensions) and their
dependencies into a shared virtual environment.

## Running services locally

Each service exposes a console script entry point. When running outside
Docker, you must configure environment variables for the TerminusDB connection
and, for LLM-dependent services, a LiteLLM proxy. See the
[configuration reference](../reference/configuration.md) for the full env-var
table.

| Service | Entry point | Port | Notes |
|---|---|---|---|
| `captured` | `uv run captured` | 8088 | Needs `CAPTURED_TDB_*` and `CAPTURED_API_TOKEN` |
| `queryd` | `uv run queryd` | 8087 | Needs `QUERYD_TDB_*` and `QUERYD_API_TOKEN` |
| `ingestd` | `uv run ingestd` | — | Polling worker; needs `INGESTD_TDB_*` and `INGESTD_LLM_*` |
| `indexed` | `uv run indexed` | 8089 | Needs `INDEXED_TDB_*` and embedding model config |
| `mcpd` | `uv run mcpd` | 8090 | Proxies to queryd + captured; needs `MCPD_QUERYD_*` |
| `triggerd` | `uv run triggerd` | — | Polling worker; needs `TRIGGERD_TDB_*` |
| `effectd` | `uv run effectd` | — | Polling worker; needs `EFFECTD_TDB_*` |
| `apid` | `uv run apid` | 8080 | Bundles captured + queryd + indexed + mcpd on one port |
| `webui` | `uv run reflex run` | 3000 | Reflex dev server; needs `WEBUI_*` vars pointing at apid |
| `firnline-schema` | `uv run firnline-schema` | — | CLI tool; see `--help` for subcommands |

You need a running TerminusDB instance (local or remote) and, for `ingestd`
and `indexed`, a LiteLLM proxy providing an OpenAI-compatible endpoint
(`FIRNLINE_LLM_BASE_URL`).

Example: run apid with a local TerminusDB:

```bash
export TDB_URL=http://localhost:6363 TDB_ORG=admin TDB_DB=firnline TDB_BRANCH=main
export TDB_USER=admin TDB_PASSWORD=...
export CAPTURED_API_TOKEN=dev-token QUERYD_API_TOKEN=dev-token
uv run apid
```

## Running tests

```bash
# All non-integration tests (default — no network required)
uv run pytest

# Include integration tests (requires a running dev instance)
uv run pytest -m 'integration'

# Run tests for a specific package
uv run pytest packages/firnline-core
```

The root `pyproject.toml` configures pytest with:

- `asyncio_mode = "auto"` — all async tests work without decorators.
- `addopts = "--import-mode=importlib -m 'not integration'"` — integration
  tests are opt-in, skipped by default.
- `norecursedirs = ["scripts/melt_test"]` — keeps the melt test suite
  separate.

Individual service `pyproject.toml` files may override these with their own
`[tool.pytest.ini_options]` sections.

## Linting and formatting

```bash
uv run ruff check     # lint (E, F, W rules; E501 is ignored)
uv run ruff format    # format (double quotes, spaces, 120-char lines)
```

The ruff configuration lives in the root `[tool.ruff]` section of
`pyproject.toml`:

- Target: Python 3.12
- Line length: 120
- Lint rules: E (pycodestyle errors), F (pyflakes), W (pycodestyle warnings)
- Ignored: E501 (line too long — handled by the formatter)

## Docker Compose dev loop

The `compose.yaml` at the repo root provides the full stack for integration
testing and manual QA:

```bash
cp .env.example .env && vim .env    # set TDB_PASSWORD, API tokens, LLM URL
docker compose up -d                # bootstrap auto-runs (schema init), then all services
docker compose logs -f ingestd      # tail the ingestion worker
docker compose down                 # tear down
```

Key services:

| Service | Purpose |
|---|---|
| `terminusdb` | Bundled TerminusDB v12 (optional — remove if using your own) |
| `bootstrap` | One-shot: creates DB, composes/applies/validates schema, installs extensions |
| `apid` | Unified API on port 8080 (captured + queryd + indexed + mcpd) |
| `ingestd` | AI extraction worker (polls Captured documents) |
| `triggerd` | Trigger evaluation worker |
| `effectd` | Effect delivery worker |
| `webui` | Reflex dashboard on port 3000 |

The `bootstrap` service must complete before any other service starts
(`depends_on: bootstrap: service_completed_successfully`). You can toggle
extensions via `FIRNLINE_EXTENSIONS` in `.env`. An optional `litellm` service
block is commented out for running an LLM proxy inside Docker.

To iterate on a single service without rebuilding everything:

```bash
docker compose up -d --build apid    # rebuild and restart only apid
docker compose restart ingestd       # restart without rebuilding
```

## Common pitfalls

- **`uv run pytest` fails with import errors** — run `uv sync --all-packages`
  first. Workspace members may have been added since your last sync.
- **TerminusDB not reachable** — ensure the `TDB_URL` environment variable
  matches your instance. The default in compose is `http://terminusdb:6363`;
  outside Docker, use `http://localhost:6363`.
- **LLM-dependent services fail** — a LiteLLM proxy (or any
  OpenAI-compatible endpoint) must be running and `FIRNLINE_LLM_BASE_URL`
  must be set.
- **Integration tests don't run** — the default `addopts` skips them. Use
  `uv run pytest -m 'integration'` explicitly.

## Related documents

- [Configuration reference](../reference/configuration.md) — all environment variables
- [Project structure](project-structure.md) — directory layout and responsibilities
- [Release process](release-process.md) — how to validate and cut a release
