# Installation

## Purpose

Set up a minimal firnline instance on your local machine for evaluation and
development. This is the quickest path from zero to a running stack. For
production deployments, see the [Deployment guide](../guides/deployment.md).

## Prerequisites

- **Docker and Docker Compose** >= 2.24.
- 2–4 GB free RAM.
- An OpenAI-compatible LLM endpoint (e.g. a LiteLLM proxy or direct API key).

For development (editing source, running tests, schema work):

- **uv** (Python package manager) and **Python 3.12**.
  See [Local development](../development/local-development.md) for full dev
  setup.

## Step 1: clone and configure

```bash
git clone https://github.com/BaLion29/firnline.git
cd firnline
cp .env.example .env
```

Edit `.env` and set at minimum these **four required values**:

| Variable | Description |
|---|---|
| `TDB_PASSWORD` | TerminusDB admin password |
| `CAPTURED_API_TOKEN` | Bearer token for the capture API |
| `QUERYD_API_TOKEN` | Bearer token for queryd / GraphQL API |
| `FIRNLINE_LLM_BASE_URL` | OpenAI-compatible LLM endpoint |

Generate secrets with:

```bash
openssl rand -hex 32
```

You will also likely need `FIRNLINE_LLM_API_KEY` if your LLM endpoint requires
an API key. Every variable (including optional ones like `WEBUI_PASSWORD`,
extension lists, and poll intervals) is documented in the
[Configuration reference](../reference/configuration.md).

## Step 2: start the stack

```bash
docker compose up -d
```

The bootstrap container runs first — it waits for TerminusDB, creates the
database, composes all schema modules, applies the schema, and installs
extensions. Runtime services start only after bootstrap succeeds (1–2 minutes
on first run).

## Step 3: verify

Check API health:

```bash
curl http://localhost:8080/healthz
```

Open the WebUI (experimental in 0.1.0 — bind to loopback) at <http://localhost:3000>.

If `docker compose ps` shows all services healthy (`Up` / `healthy`), you are
ready to continue with the [Quickstart](quickstart.md).

## Common pitfalls

- **Port conflicts** — ports 8080, 3000, and 6363 must be free. Override them
  in `.env` (`APID_HOST_PORT`, `WEBUI_HOST_PORT`, `TDB_HOST_PORT`).
- **LLM unreachable** — the default `FIRNLINE_LLM_BASE_URL` is
  `http://host.docker.internal:4000`. If you are not running a local LiteLLM
  proxy, change this to your provider's base URL (and set
  `FIRNLINE_LLM_API_KEY`). Without a working LLM, `ingestd` will fail to
  process captured items.
- **Bootstrap looping** — `docker compose logs bootstrap` will show what went
  wrong. Most common: a required env var is missing, or TerminusDB didn't
  become healthy in time.

## Related documents

- [Quickstart](quickstart.md) — capture your first item
- [Deployment guide](../guides/deployment.md) — production deployment
- [Configuration reference](../reference/configuration.md) — every env var
- [Local development](../development/local-development.md) — dev toolchain setup
- [Architecture](../concepts/architecture.md) — how the services fit together
