# Local Development

Set up a firnline development environment on your machine.

## Prerequisites

- **Python ≥ 3.12**
- **[uv](https://docs.astral.sh/uv/)** — Python package manager and runner
- **Docker** (optional) — for running a development TerminusDB or the full stack
- **Nix** (optional) — a `shell.nix` dev shell is provided

## Setup

```bash
# Clone and enter the repo
git clone git@github.com:BaLion29/firnline.git
cd firnline

# Install all workspace packages (16 packages) and dev dependencies
uv sync
```

If you use Nix, drop into the dev shell instead (provides Python 3.12 and uv):

```bash
nix-shell
```

## Running tests

```bash
uv run pytest                    # all non-integration tests (~77 test files)
uv run pytest -m integration      # integration tests (requires running TerminusDB)
uv run pytest packages/firnline-schema  # run tests for a single package
```

Integration tests are excluded by default (see [testing.md](testing.md)).

## Linting and formatting

```bash
uv run ruff check          # lint (E, F, W rules, line length 120)
uv run ruff format --check # format check
uv run ruff format         # auto-fix formatting
```

## Running services against a dev TerminusDB

Start a local TerminusDB container:

```bash
docker run -d --name tdb-dev -p 6363:6363 \
  terminusdb/terminusdb-server:v12.0.6
```

Then run a service directly on the host with the required environment
variables:

```bash
# queryd example
QUERYD_TDB_URL=http://localhost:6363 \
QUERYD_TDB_DB=dev \
QUERYD_TDB_PASSWORD=root \
QUERYD_API_TOKEN=dev-token \
uv run queryd

# captured example
CAPTURED_TDB_URL=http://localhost:6363 \
CAPTURED_TDB_DB=dev \
CAPTURED_TDB_PASSWORD=root \
CAPTURED_API_TOKEN=dev-token \
uv run captured
```

Each service has its own environment variable prefix (`QUERYD_`, `CAPTURED_`,
`INGESTD_`, `TRIGGERD_`, `EFFECTD_`). See
[../reference/configuration.md](../reference/configuration.md) for the full
list.

## Workspace layout

The repo is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/):

```
members = ["packages/*", "services/*", "extensions/*"]
```

- **`packages/`** — shared libraries (`firnline-core`, `firnline-schema`)
- **`services/`** — deployable daemons (captured, queryd, ingestd, mcpd, etc.)
- **`extensions/`** — first-party extension packages (gotify, people, places,
  reminders, time-management, webhook)

All packages use `hatchling` as their build backend. Dependencies between
workspace members are declared via `[tool.uv.sources]` with
`{ workspace = true }`.

For a full walkthrough of what each directory contains and where new code
should go, see [project-structure.md](project-structure.md).

## Full stack via Docker Compose

For full integration testing with all services, use the compose setup:

```bash
cp .env.example .env && vim .env      # set TDB_URL + secrets
docker compose --profile bootstrap up bootstrap --abort-on-container-exit
docker compose up -d
```

## Related documents

- [testing.md](testing.md) — test conventions in detail
- [project-structure.md](project-structure.md) — directory responsibilities
- [../getting-started/quickstart.md](../getting-started/quickstart.md) —
  Docker-based quickstart for users
- [../reference/configuration.md](../reference/configuration.md) —
  all environment variables
