# Deployment

## Purpose

How to deploy the full firnline stack in production using Docker Compose.
Covers prerequisites, configuration, service startup, extension installation,
and upgrades.

## Prerequisites

- Docker and Docker Compose >= 2.24.
- 2–4 GB free RAM for TerminusDB plus the firnline services.
- An OpenAI-compatible LLM endpoint (e.g. LiteLLM proxy) reachable from the
  containers.

## Step 1: clone and configure

```bash
git clone https://github.com/davidsouther/firnline.git
cd firnline
cp .env.example .env
```

Edit `.env` and set these **required** values:

- `TDB_PASSWORD` — TerminusDB admin password.
- `CAPTURED_API_TOKEN` — bearer token for the capture API.
- `QUERYD_API_TOKEN` — bearer token for the queryd API.
- `FIRNLINE_LLM_BASE_URL` — OpenAI-compatible LLM endpoint (the default
  `http://host.docker.internal:4000` works with a host-local LiteLLM proxy;
  compose already maps `host.docker.internal` to the host gateway on Linux).

Generate secrets with:

```bash
openssl rand -hex 32
```

Every available variable is documented in [../reference/configuration.md](../reference/configuration.md).
Review the full reference if you need optional settings such as the WebUI
password gate, geocoding base URL, or poll intervals.

## Step 2: bundled TerminusDB (default)

The compose file includes a bundled TerminusDB v12.0.6 container that stores
data in a named volume (`terminusdb_data`). This is the zero-config default.

To use your own external TerminusDB instead:

1. Delete or comment out the `terminusdb` service block and the
   `terminusdb_data` volume in `compose.yaml`.
2. Set `TDB_URL` in `.env` to point to your instance.

## Step 3: start the stack

```bash
docker compose up -d
```

The bootstrap container runs first: it waits for TerminusDB, creates the
database if it doesn't exist, composes all schema modules (kernel + installed
extensions), applies the schema, and validates the result. Only after
bootstrap completes successfully do the runtime services start.

## Service ports

| Service | Container port | Host port (configurable) | Health endpoint |
|---|---|---|---|
| apid (captured + queryd + indexed + mcpd) | 8080 | `${APID_HOST_PORT:-8080}` | `/healthz` |
| webui | 3000 | `${WEBUI_HOST_PORT:-3000}` | `/healthz` |
| terminusdb (bundled) | 6363 | `${TDB_HOST_PORT:-6363}` | TCP connect |

All health checks are defined in `compose.yaml`. For polling workers
(ingestd, triggerd, effectd), the health check verifies that a liveness file
is fresh (< 5 min old) rather than pinging an HTTP endpoint. Verify them
manually when needed:

```bash
docker compose exec ingestd find /tmp/ingestd-alive -mmin -5
docker compose exec triggerd find /tmp/triggerd-alive -mmin -5
docker compose exec effectd find /tmp/effectd-alive -mmin -5
```

Verify apid health:

```bash
curl http://localhost:8080/healthz
```

## Step 4: installing extensions

Extensions are installed via the `FIRNLINE_EXTENSIONS` variable in `.env`.
The file `docker/entrypoint.sh` manages a shared overlay volume
(`firnline_ext_venv`) across all service containers.

How it works:

1. The **bootstrap** container mounts the overlay read-write, runs `pip
   install --target` for each extension specifier in `FIRNLINE_EXTENSIONS`,
   and then proceeds with schema composition (which discovers schema modules
   from those extensions).
2. All **service containers** mount the overlay **read-only** and verify
   extension presence at startup.

Accepted specifier formats:

- PyPI name: `firnline_ext_address_book>=0.1.0`
- Git URL: `git+https://github.com/user/firnline-ext-foo.git`
- Wheel filename: `firnline_ext_address_book-0.1.0-py3-none-any.whl` (resolved
  against `/extensions/` in the image; first-party wheels are baked into
  service images at build time).

To add an extension:

1. Edit `FIRNLINE_EXTENSIONS` in `.env` (comma-separated).
2. Run: `docker compose up -d` — the bootstrap container re-runs on restart,
   picking up the new extensions. Set `FIRNLINE_EXTENSIONS_PURGE=true` to wipe
   the overlay before reinstalling (useful when removing extensions).

For building extensions, see [Writing extensions](writing-extensions.md).

## Step 5: verifying the deployment

After all services are healthy, verify end-to-end:

```bash
# Capture a note
curl -s -X POST http://localhost:8080/v1/capture/note \
  -H "Authorization: Bearer $CAPTURED_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy milk on the way home", "kind": "note"}'

# Query your data
curl -s -X POST http://localhost:8080/v1/graphql \
  -H "Authorization: Bearer $QUERYD_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ Captured { id captured_text } }"}'
```

Open <http://localhost:3000> for the WebUI dashboard.

## Upgrading

1. Pull the latest code or images.
2. Review the [CHANGELOG](../../CHANGELOG.md) for breaking changes.
3. Rebuild images: `docker compose build --no-cache`
4. Restart: `docker compose up -d`
5. The bootstrap container re-runs and applies any pending schema migrations
   (additive only). **Always back up first** — see [Backup and restore](backup-and-restore.md).

## HTTPS behind Traefik

Run firnline behind a Traefik reverse proxy with automatic Let's Encrypt TLS
certificates.  Traefik terminates TLS on ports 80/443 and forwards requests
to firnline services over plain HTTP on the internal compose network.

### Prerequisites

- A **real, publicly-resolvable domain name** (e.g. `firnline.example.com`).
  `localhost` or internal Docker hostnames will NOT work for Let's Encrypt.
- The domain must point to the server's public IP (A/AAAA record).
- Ports 80 and 443 must be reachable from the internet on the host.

### Setup

```bash
cp .env.example .env
# Edit .env and set:
#   DOMAIN=your-domain.example.com
#   ACME_EMAIL=you@example.com
#   TDB_PASSWORD=<openssl rand -hex 32>
#   CAPTURED_API_TOKEN=<openssl rand -hex 32>
#   QUERYD_API_TOKEN=<openssl rand -hex 32>
#   FIRNLINE_LLM_BASE_URL=http://host.docker.internal:4000
```

Then start the full stack with the Traefik overlay:

```bash
docker compose -f compose.yaml -f compose.traefik.yaml up -d
```

### What happens

- **Traefik** listens on ports 80 and 443.  HTTP on port 80 is redirected
  to HTTPS on port 443.
- Let's Encrypt ACME TLS challenge automatically provisions a certificate
  for `api.${DOMAIN}` and `${DOMAIN}`.
- **api.${DOMAIN}** → Traefik → `apid:8080` (plain HTTP inside the network).
- **${DOMAIN}** → Traefik → `webui:3000` (plain HTTP inside the network).
- **TerminusDB** host ports are un-published (`compose.traefik.yaml` overrides
  `terminusdb` with `ports: []`).  The database is accessible only from
  containers on the compose network.
- **apid** and **webui** host ports are also un-published — only Traefik
  handles ingress.
- Within the Docker network, all inter-service calls (apid → terminusdb:
  `http://terminusdb:6363`, webui → apid: `http://apid:8080`) remain plain
  HTTP — no TLS overhead for internal traffic.
- `APID_PROXY_HEADERS=true` and `APID_FORWARDED_ALLOW_IPS=*` are set so
  uvicorn respects `X-Forwarded-*` headers from Traefik.  Trusting all
  forwarded IPs is safe because apid's ports are un-published.

### Accessing

After startup, navigate to `https://${DOMAIN}` for the WebUI and
`https://api.${DOMAIN}/healthz` for the API health check.

## Related documents

- [../reference/configuration.md](../reference/configuration.md) — complete env-var reference
- [Backup and restore](backup-and-restore.md) — backup procedure before upgrades
- [WebUI](webui.md) — dashboard deployment and configuration
- [Writing extensions](writing-extensions.md) — building and installing extensions
- [../getting-started/installation.md](../getting-started/installation.md) — quickstart for new users
- [../concepts/architecture.md](../concepts/architecture.md) — service architecture overview
